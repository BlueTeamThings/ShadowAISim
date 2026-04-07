"""Workflow persistence and validation over JSON files."""

from __future__ import annotations

import json
import platform
import threading
import uuid
from pathlib import Path

from app.core.app_catalog import list_apps
from app.core.workflow_definitions import (
    STEP_FIELDS_BY_TYPE,
    STEP_TYPE_DEFINITIONS,
    default_workflows,
    normalize_platform,
    now_iso,
)

WORKFLOW_DIR = Path("simulator_data/workflows")
WORKFLOW_FILE = WORKFLOW_DIR / "workflows.json"
RUN_HISTORY_FILE = WORKFLOW_DIR / "run_history.json"
SCHEMA_FILE = WORKFLOW_DIR / "workflow_schema.json"
SCREENSHOT_DIR = WORKFLOW_DIR / "screenshots"


class WorkflowValidationError(ValueError):
    pass


class WorkflowStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ensure_files()

    def _ensure_files(self) -> None:
        WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        if not WORKFLOW_FILE.exists():
            WORKFLOW_FILE.write_text(json.dumps(default_workflows(), indent=2), encoding="utf-8")

        if not RUN_HISTORY_FILE.exists():
            RUN_HISTORY_FILE.write_text("[]", encoding="utf-8")

        if not SCHEMA_FILE.exists():
            schema = {
                "workflow_fields": [
                    "id",
                    "name",
                    "description",
                    "platform",
                    "enabled",
                    "tags",
                    "steps",
                    "assertions",
                    "metadata",
                    "created_date",
                    "last_run_date",
                    "status",
                ],
                "step_types": STEP_TYPE_DEFINITIONS,
            }
            SCHEMA_FILE.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    def _read_json(self, path: Path) -> list[dict]:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        data = json.loads(text)
        return data if isinstance(data, list) else []

    def _write_json(self, path: Path, payload: list[dict]) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _validate_step(self, step: dict, index: int) -> dict:
        if not isinstance(step, dict):
            raise WorkflowValidationError(f"Step {index + 1} must be an object")

        step_type = str(step.get("type", "")).strip()
        params = step.get("params") or {}
        if not step_type:
            raise WorkflowValidationError(f"Step {index + 1} is missing type")

        if step_type == "install_extension":
            step_type = "install_browser_extension"

        if step_type not in STEP_FIELDS_BY_TYPE:
            raise WorkflowValidationError(f"Step {index + 1} has unsupported type: {step_type}")

        if not isinstance(params, dict):
            raise WorkflowValidationError(f"Step {index + 1} params must be an object")

        required_fields = [f for f in STEP_FIELDS_BY_TYPE[step_type] if f.get("required")]
        for field in required_fields:
            name = field["name"]
            value = params.get(name)
            if value is None:
                raise WorkflowValidationError(f"Step {index + 1} missing required field: {name}")
            if isinstance(value, str) and not value.strip():
                raise WorkflowValidationError(f"Step {index + 1} field '{name}' cannot be empty")

        return {
            "id": step.get("id") or f"step-{index + 1}",
            "type": step_type,
            "params": params,
            "notes": str(step.get("notes", "")).strip(),
        }

    def validate_workflow_payload(self, payload: dict, *, for_update: bool = False) -> dict:
        if not isinstance(payload, dict):
            raise WorkflowValidationError("Workflow payload must be an object")

        name = str(payload.get("name", "")).strip()
        if not name:
            raise WorkflowValidationError("Workflow name is required")

        description = str(payload.get("description", "")).strip()
        tags = payload.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        if not isinstance(tags, list):
            raise WorkflowValidationError("Workflow tags must be an array of strings")

        platform = normalize_platform(str(payload.get("platform", "any")))
        enabled = bool(payload.get("enabled", True))
        assertions = payload.get("assertions") or []
        metadata = payload.get("metadata") or {}

        steps_raw = payload.get("steps") or []
        if not isinstance(steps_raw, list) or not steps_raw:
            raise WorkflowValidationError("Workflow must include at least one step")

        steps = [self._validate_step(step, idx) for idx, step in enumerate(steps_raw)]

        cleaned = {
            "name": name,
            "description": description,
            "platform": platform,
            "enabled": enabled,
            "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
            "steps": steps,
            "assertions": assertions if isinstance(assertions, list) else [],
            "metadata": metadata if isinstance(metadata, dict) else {},
            "status": str(payload.get("status", "idle")),
        }

        if for_update:
            cleaned["last_run_date"] = payload.get("last_run_date")
            cleaned["created_date"] = payload.get("created_date")

        return cleaned

    def list_workflows(self) -> list[dict]:
        with self._lock:
            workflows = self._read_json(WORKFLOW_FILE)
        return sorted(workflows, key=lambda w: w.get("name", "").lower())

    def get_workflow(self, workflow_id: str) -> dict | None:
        for workflow in self.list_workflows():
            if workflow.get("id") == workflow_id:
                return workflow
        return None

    def create_workflow(self, payload: dict) -> dict:
        data = self.validate_workflow_payload(payload)
        now = now_iso()
        workflow = {
            "id": payload.get("id") or f"wf-{uuid.uuid4().hex[:10]}",
            "created_date": now,
            "last_run_date": None,
            **data,
        }

        with self._lock:
            workflows = self._read_json(WORKFLOW_FILE)
            if any(w.get("id") == workflow["id"] for w in workflows):
                workflow["id"] = f"wf-{uuid.uuid4().hex[:10]}"
            workflows.append(workflow)
            self._write_json(WORKFLOW_FILE, workflows)

        return workflow

    def update_workflow(self, workflow_id: str, payload: dict) -> dict:
        with self._lock:
            workflows = self._read_json(WORKFLOW_FILE)
            idx = next((i for i, w in enumerate(workflows) if w.get("id") == workflow_id), None)
            if idx is None:
                raise KeyError(workflow_id)

            current = workflows[idx]
            merged = {
                **current,
                **payload,
                "id": workflow_id,
                "created_date": current.get("created_date") or now_iso(),
            }
            cleaned = self.validate_workflow_payload(merged, for_update=True)
            workflows[idx] = {
                **current,
                **cleaned,
                "id": workflow_id,
                "created_date": current.get("created_date") or now_iso(),
            }
            self._write_json(WORKFLOW_FILE, workflows)
            return workflows[idx]

    def delete_workflow(self, workflow_id: str) -> bool:
        with self._lock:
            workflows = self._read_json(WORKFLOW_FILE)
            original = len(workflows)
            workflows = [w for w in workflows if w.get("id") != workflow_id]
            if len(workflows) == original:
                return False
            self._write_json(WORKFLOW_FILE, workflows)
            return True

    def duplicate_workflow(self, workflow_id: str) -> dict:
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            raise KeyError(workflow_id)

        payload = {
            **workflow,
            "id": f"wf-{uuid.uuid4().hex[:10]}",
            "name": f"{workflow.get('name', 'Workflow')} (copy)",
            "created_date": now_iso(),
            "last_run_date": None,
            "status": "idle",
        }

        with self._lock:
            workflows = self._read_json(WORKFLOW_FILE)
            workflows.append(payload)
            self._write_json(WORKFLOW_FILE, workflows)

        return payload

    def append_run_history(self, run_record: dict) -> None:
        with self._lock:
            history = self._read_json(RUN_HISTORY_FILE)
            history.insert(0, run_record)
            self._write_json(RUN_HISTORY_FILE, history[:200])

    def list_run_history(self, *, limit: int = 25) -> list[dict]:
        with self._lock:
            history = self._read_json(RUN_HISTORY_FILE)
        return history[:limit]

    def mark_workflow_run(self, workflow_id: str, *, status: str, run_id: str) -> None:
        with self._lock:
            workflows = self._read_json(WORKFLOW_FILE)
            changed = False
            for workflow in workflows:
                if workflow.get("id") != workflow_id:
                    continue
                workflow["last_run_date"] = now_iso()
                workflow["status"] = status
                workflow.setdefault("metadata", {})
                workflow["metadata"]["last_run_id"] = run_id
                changed = True
                break

            if changed:
                self._write_json(WORKFLOW_FILE, workflows)

    def metadata(self) -> dict:
        apps = list_apps()
        system = platform.system().lower()
        platform_name = "windows" if system.startswith("win") else "linux"
        return {
            "platform": platform_name,
            "step_types": STEP_TYPE_DEFINITIONS,
            "apps": [
                {
                    "app_id": app.get("app_id"),
                    "name": app.get("display_name"),
                    "supported_platforms": app.get("supported_platforms", []),
                }
                for app in apps
            ],
            "schema_path": str(SCHEMA_FILE),
        }
