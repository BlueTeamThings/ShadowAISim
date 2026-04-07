"""Tests for sequential workflow runner behavior."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import app.core.workflow_store as workflow_store_module
from app.automation.workflow_runner import ExecutionContext, WorkflowRunner


def _run(coro):
    return asyncio.run(coro)


class TestWorkflowRunner(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)

        self.patches = [
            patch.object(workflow_store_module, "WORKFLOW_DIR", root / "workflows"),
            patch.object(workflow_store_module, "WORKFLOW_FILE", root / "workflows" / "workflows.json"),
            patch.object(workflow_store_module, "RUN_HISTORY_FILE", root / "workflows" / "run_history.json"),
            patch.object(workflow_store_module, "SCHEMA_FILE", root / "workflows" / "workflow_schema.json"),
            patch.object(workflow_store_module, "SCREENSHOT_DIR", root / "workflows" / "screenshots"),
        ]
        for p in self.patches:
            p.start()

        self.store = workflow_store_module.WorkflowStore()
        self.runner = WorkflowRunner(self.store)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp_dir.cleanup()

    def test_wait_only_workflow_passes(self):
        workflow = {
            "id": "wf-test-wait",
            "name": "Wait Workflow",
            "steps": [
                {"id": "s1", "type": "wait", "params": {"seconds": 0.01}},
            ],
        }

        out = _run(self.runner.run_workflow(workflow))
        self.assertEqual(out["status"], "passed")
        self.assertEqual(out["completed_steps"], 1)

        history = self.store.list_run_history(limit=5)
        self.assertGreaterEqual(len(history), 1)
        self.assertEqual(history[0]["workflow_id"], "wf-test-wait")

    def test_vscode_install_uses_linux_fallback(self):
        async def _case():
            context = ExecutionContext(emit=AsyncMock())

            def _which(name: str):
                if name == "code":
                    return None
                if name == "snap":
                    return "/usr/bin/snap"
                return None

            with patch.object(self.runner, "_resolve_app", return_value=None), \
                 patch("app.automation.workflow_runner.platform.system", return_value="Linux"), \
                 patch("app.automation.workflow_runner.shutil.which", side_effect=_which), \
                 patch.object(self.runner, "_run_command", new=AsyncMock(return_value=(0, "ok"))):
                ok, message, details = await self.runner._step_install_application({"app_name": "VS Code"}, context)

            self.assertTrue(ok)
            self.assertIn("VS Code install", message)
            self.assertEqual(details.get("classification"), "INSTALLED_OK")

        _run(_case())

    def test_close_ollama_uses_daemon_handler(self):
        async def _case():
            context = ExecutionContext(emit=AsyncMock())
            with patch.object(self.runner, "_resolve_app", return_value={"app_id": "ollama"}), \
                 patch.object(self.runner, "_close_ollama_daemon", new=AsyncMock(return_value={"stopped": True, "message": "Ollama daemon was not running"})):
                ok, message, details = await self.runner._step_close_application({"app_name": "Ollama"}, context)

            self.assertTrue(ok)
            self.assertIn("Ollama", message)
            self.assertTrue(details.get("stopped"))

        _run(_case())


if __name__ == "__main__":
    unittest.main()
