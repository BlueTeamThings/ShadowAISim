"""Scenario persistence, tree building, validation, and import/export helpers."""

from __future__ import annotations

import json
import platform
import threading
import uuid
from pathlib import Path

from app.core.app_catalog import list_apps
from app.core.scenario_definitions import (
    CATEGORY_ORDER,
    RISK_LEVELS,
    SCENARIO_FIELDS,
    SCENARIO_TEMPLATES,
    STEP_FIELDS_BY_TYPE,
    STEP_TYPE_DEFINITIONS,
    built_in_scenarios,
    normalize_platforms,
    now_iso,
)

SCENARIO_DIR = Path("simulator_data/scenarios")
SCENARIO_FILE = SCENARIO_DIR / "scenarios.json"
RUN_HISTORY_FILE = SCENARIO_DIR / "run_history.json"
SCHEMA_FILE = SCENARIO_DIR / "scenario_schema.json"
SCREENSHOT_DIR = SCENARIO_DIR / "screenshots"
SAMPLE_DIR = SCENARIO_DIR / "samples"


class ScenarioValidationError(ValueError):
    pass


class ScenarioStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ensure_files()

    def _ensure_files(self) -> None:
        SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

        self._ensure_sample_files()

        if not SCENARIO_FILE.exists():
            SCENARIO_FILE.write_text(json.dumps(built_in_scenarios(), indent=2), encoding="utf-8")

        if not RUN_HISTORY_FILE.exists():
            RUN_HISTORY_FILE.write_text("[]", encoding="utf-8")

        if not SCHEMA_FILE.exists():
            schema_payload = {
                "scenario_fields": SCENARIO_FIELDS,
                "categories": CATEGORY_ORDER,
                "risk_levels": sorted(RISK_LEVELS),
                "step_types": STEP_TYPE_DEFINITIONS,
                "templates": SCENARIO_TEMPLATES,
            }
            SCHEMA_FILE.write_text(json.dumps(schema_payload, indent=2), encoding="utf-8")

    def _ensure_sample_files(self) -> None:
        text_path = SAMPLE_DIR / "sample_brief.txt"
        if not text_path.exists():
            text_path.write_text(
                "CONFIDENTIAL TEST FILE\n"
                "Project: Atlas\n"
                "Budget: 1450000\n"
                "Owner: red-team-lab\n",
                encoding="utf-8",
            )

        csv_path = SAMPLE_DIR / "sample_metrics.csv"
        if not csv_path.exists():
            csv_path.write_text(
                "employee_id,region,quota,status\n"
                "E-102,EMEA,420000,active\n"
                "E-301,NA,610000,active\n"
                "E-998,APAC,380000,leave\n",
                encoding="utf-8",
            )

        pdf_path = SAMPLE_DIR / "sample_summary.pdf"
        if not pdf_path.exists():
            # Minimal placeholder fixture for upload simulations.
            pdf_path.write_bytes(b"%PDF-1.1\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")

    def _read_json(self, path: Path) -> list[dict]:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        payload = json.loads(raw)
        return payload if isinstance(payload, list) else []

    def _write_json(self, path: Path, payload: list[dict]) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _validate_step(self, step: dict, index: int) -> dict:
        if not isinstance(step, dict):
            raise ScenarioValidationError(f"Step {index + 1} must be an object")

        step_type = str(step.get("type", "")).strip()
        if not step_type:
            raise ScenarioValidationError(f"Step {index + 1} missing type")

        if step_type == "install_extension":
            step_type = "install_browser_extension"

        if step_type not in STEP_FIELDS_BY_TYPE:
            raise ScenarioValidationError(f"Step {index + 1} unsupported type: {step_type}")

        params = step.get("params") or {}
        if not isinstance(params, dict):
            raise ScenarioValidationError(f"Step {index + 1} params must be object")

        required_fields = [f for f in STEP_FIELDS_BY_TYPE[step_type] if f.get("required")]
        for field in required_fields:
            key = field["name"]
            value = params.get(key)
            if value is None:
                raise ScenarioValidationError(f"Step {index + 1} missing required field: {key}")
            if isinstance(value, str) and not value.strip():
                raise ScenarioValidationError(f"Step {index + 1} field '{key}' cannot be empty")

        return {
            "id": step.get("id") or f"step-{index + 1}",
            "type": step_type,
            "params": params,
            "notes": str(step.get("notes", "")).strip(),
        }

    def validate_scenario_payload(self, payload: dict, *, for_update: bool = False) -> dict:
        if not isinstance(payload, dict):
            raise ScenarioValidationError("Scenario payload must be an object")

        title = str(payload.get("title", "")).strip()
        if not title:
            raise ScenarioValidationError("Scenario title is required")

        category = str(payload.get("category", "")).strip()
        if not category:
            raise ScenarioValidationError("Scenario category is required")

        family = str(payload.get("family", "")).strip()
        if not family:
            raise ScenarioValidationError("Scenario family is required")

        description = str(payload.get("description", "")).strip()
        risk_level = str(payload.get("risk_level", "medium")).strip().lower()
        if risk_level not in RISK_LEVELS:
            raise ScenarioValidationError(f"risk_level must be one of: {', '.join(sorted(RISK_LEVELS))}")

        tags = payload.get("tags") or []
        if isinstance(tags, str):
            tags = [item.strip() for item in tags.split(",") if item.strip()]
        if not isinstance(tags, list):
            raise ScenarioValidationError("tags must be an array")

        platforms = normalize_platforms(payload.get("platforms") or payload.get("platform"))
        auth_required = bool(payload.get("auth_required", False))

        def normalize_list(key: str) -> list[str]:
            raw = payload.get(key) or []
            if isinstance(raw, str):
                raw = [item.strip() for item in raw.split("\n") if item.strip()]
            if not isinstance(raw, list):
                raise ScenarioValidationError(f"{key} must be an array")
            return [str(item).strip() for item in raw if str(item).strip()]

        prerequisites = normalize_list("prerequisites")
        assertions = normalize_list("assertions")
        expected_observables = normalize_list("expected_observables")
        detector_expectations = normalize_list("detector_expectations")
        cleanup_steps = normalize_list("cleanup_steps")

        steps_raw = payload.get("steps") or []
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ScenarioValidationError("Scenario requires at least one step")
        steps = [self._validate_step(step, idx) for idx, step in enumerate(steps_raw)]

        cleaned = {
            "title": title,
            "description": description,
            "category": category,
            "family": family,
            "tags": [str(item).strip() for item in tags if str(item).strip()],
            "risk_level": risk_level,
            "platforms": platforms,
            "auth_required": auth_required,
            "prerequisites": prerequisites,
            "steps": steps,
            "assertions": assertions,
            "expected_observables": expected_observables,
            "detector_expectations": detector_expectations,
            "cleanup_steps": cleanup_steps,
            "status": str(payload.get("status", "idle")).strip() or "idle",
            "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        }

        if for_update:
            cleaned["created_date"] = payload.get("created_date")
            cleaned["last_run_date"] = payload.get("last_run_date")

        return cleaned

    def list_scenarios(
        self,
        *,
        platform: str | None = None,
        auth_required: bool | None = None,
        mode: str | None = None,
    ) -> list[dict]:
        with self._lock:
            scenarios = self._read_json(SCENARIO_FILE)

        items = scenarios
        if platform:
            pf = platform.strip().lower()
            items = [
                item for item in items
                if "any" in item.get("platforms", []) or pf in item.get("platforms", [])
            ]

        if auth_required is not None:
            items = [item for item in items if bool(item.get("auth_required", False)) == bool(auth_required)]

        if mode:
            mode_key = mode.strip().lower()

            def matches_mode(item: dict) -> bool:
                tags = {str(t).lower() for t in item.get("tags", [])}
                if mode_key == "browser-only":
                    return "browser" in tags and "desktop" not in tags and "local" not in tags
                if mode_key == "desktop-only":
                    return "desktop" in tags and "browser" not in tags
                if mode_key == "local-only":
                    return "local" in tags
                return True

            items = [item for item in items if matches_mode(item)]

        return sorted(items, key=lambda item: (CATEGORY_ORDER.index(item.get("category")) if item.get("category") in CATEGORY_ORDER else 999, item.get("family", ""), item.get("title", "").lower()))

    def build_tree(self, **filters) -> list[dict]:
        grouped: dict[str, dict[str, list[dict]]] = {}
        for scenario in self.list_scenarios(**filters):
            category = scenario.get("category", "Uncategorized")
            family = scenario.get("family", "General")
            grouped.setdefault(category, {}).setdefault(family, []).append(scenario)

        ordered_categories = sorted(
            grouped.keys(),
            key=lambda cat: CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER else 999,
        )

        tree = []
        for category in ordered_categories:
            family_items = []
            for family in sorted(grouped[category].keys()):
                children = sorted(grouped[category][family], key=lambda item: item.get("title", "").lower())
                family_items.append({
                    "family": family,
                    "count": len(children),
                    "scenarios": [
                        {
                            "id": item.get("id"),
                            "title": item.get("title"),
                            "risk_level": item.get("risk_level"),
                            "auth_required": item.get("auth_required", False),
                            "platforms": item.get("platforms", []),
                            "status": item.get("status", "idle"),
                        }
                        for item in children
                    ],
                })

            tree.append({"category": category, "count": sum(f["count"] for f in family_items), "families": family_items})
        return tree

    def get_scenario(self, scenario_id: str) -> dict | None:
        for item in self.list_scenarios():
            if item.get("id") == scenario_id:
                return item
        return None

    def create_scenario(self, payload: dict) -> dict:
        data = self.validate_scenario_payload(payload)
        now = now_iso()
        record = {
            "id": payload.get("id") or f"scn-{uuid.uuid4().hex[:10]}",
            "created_date": now,
            "last_run_date": None,
            **data,
        }

        with self._lock:
            existing = self._read_json(SCENARIO_FILE)
            if any(item.get("id") == record["id"] for item in existing):
                record["id"] = f"scn-{uuid.uuid4().hex[:10]}"
            existing.append(record)
            self._write_json(SCENARIO_FILE, existing)

        return record

    def update_scenario(self, scenario_id: str, payload: dict) -> dict:
        with self._lock:
            scenarios = self._read_json(SCENARIO_FILE)
            idx = next((i for i, item in enumerate(scenarios) if item.get("id") == scenario_id), None)
            if idx is None:
                raise KeyError(scenario_id)

            current = scenarios[idx]
            merged = {
                **current,
                **payload,
                "id": scenario_id,
                "created_date": current.get("created_date") or now_iso(),
            }
            cleaned = self.validate_scenario_payload(merged, for_update=True)
            scenarios[idx] = {
                **current,
                **cleaned,
                "id": scenario_id,
                "created_date": current.get("created_date") or now_iso(),
            }
            self._write_json(SCENARIO_FILE, scenarios)
            return scenarios[idx]

    def delete_scenario(self, scenario_id: str) -> bool:
        with self._lock:
            scenarios = self._read_json(SCENARIO_FILE)
            original = len(scenarios)
            scenarios = [item for item in scenarios if item.get("id") != scenario_id]
            if len(scenarios) == original:
                return False
            self._write_json(SCENARIO_FILE, scenarios)
            return True

    def duplicate_scenario(self, scenario_id: str) -> dict:
        scenario = self.get_scenario(scenario_id)
        if not scenario:
            raise KeyError(scenario_id)

        duplicate = {
            **scenario,
            "id": f"scn-{uuid.uuid4().hex[:10]}",
            "title": f"{scenario.get('title', 'Scenario')} (copy)",
            "created_date": now_iso(),
            "last_run_date": None,
            "status": "idle",
        }

        with self._lock:
            scenarios = self._read_json(SCENARIO_FILE)
            scenarios.append(duplicate)
            self._write_json(SCENARIO_FILE, scenarios)

        return duplicate

    def append_run_history(self, run_record: dict) -> None:
        with self._lock:
            history = self._read_json(RUN_HISTORY_FILE)
            history.insert(0, run_record)
            self._write_json(RUN_HISTORY_FILE, history[:300])

    def list_run_history(self, *, limit: int = 30) -> list[dict]:
        with self._lock:
            history = self._read_json(RUN_HISTORY_FILE)
        return history[:limit]

    def mark_scenario_run(self, scenario_id: str, *, status: str, run_id: str) -> None:
        with self._lock:
            scenarios = self._read_json(SCENARIO_FILE)
            updated = False
            for item in scenarios:
                if item.get("id") != scenario_id:
                    continue
                item["last_run_date"] = now_iso()
                item["status"] = status
                item.setdefault("metadata", {})
                item["metadata"]["last_run_id"] = run_id
                updated = True
                break
            if updated:
                self._write_json(SCENARIO_FILE, scenarios)

    def export_scenarios(self) -> dict:
        return {
            "exported_at": now_iso(),
            "count": len(self.list_scenarios()),
            "scenarios": self.list_scenarios(),
        }

    def import_scenarios(self, payload: dict, *, mode: str = "merge") -> dict:
        incoming = payload.get("scenarios") if isinstance(payload, dict) else None
        if not isinstance(incoming, list) or not incoming:
            raise ScenarioValidationError("Import payload requires non-empty 'scenarios' array")

        cleaned = [self.validate_scenario_payload(item) | {"id": item.get("id") or f"scn-{uuid.uuid4().hex[:10]}", "created_date": item.get("created_date") or now_iso(), "last_run_date": item.get("last_run_date")} for item in incoming]

        with self._lock:
            existing = self._read_json(SCENARIO_FILE)
            if mode == "replace":
                final_items = cleaned
                added = len(cleaned)
                updated = 0
            else:
                index = {item.get("id"): i for i, item in enumerate(existing)}
                added = 0
                updated = 0
                for item in cleaned:
                    item_id = item.get("id")
                    if item_id in index:
                        existing[index[item_id]] = {**existing[index[item_id]], **item}
                        updated += 1
                    else:
                        existing.append(item)
                        added += 1
                final_items = existing

            self._write_json(SCENARIO_FILE, final_items)

        return {
            "mode": mode,
            "added": added,
            "updated": updated,
            "total": len(final_items),
        }

    def metadata(self) -> dict:
        system = platform.system().lower()
        platform_name = "windows" if system.startswith("win") else ("darwin" if system == "darwin" else "linux")

        families = sorted({
            item.get("family", "General")
            for item in self.list_scenarios()
        })

        return {
            "platform": platform_name,
            "categories": CATEGORY_ORDER,
            "families": families,
            "risk_levels": sorted(RISK_LEVELS),
            "step_types": STEP_TYPE_DEFINITIONS,
            "templates": SCENARIO_TEMPLATES,
            "apps": [
                {
                    "app_id": app.get("app_id"),
                    "name": app.get("display_name"),
                    "supported_platforms": app.get("supported_platforms", []),
                }
                for app in list_apps()
            ],
            "schema_path": str(SCHEMA_FILE),
            "sample_files": [
                str(SAMPLE_DIR / "sample_brief.txt"),
                str(SAMPLE_DIR / "sample_metrics.csv"),
                str(SAMPLE_DIR / "sample_summary.pdf"),
            ],
        }
