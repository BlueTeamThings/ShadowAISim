"""Tests for scenario runner sequencing and manual checkpoint behavior."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import app.core.scenario_store as scenario_store_module
from app.automation.scenario_runner import ExecutionContext, ScenarioRunner


def _run(coro):
    return asyncio.run(coro)


class TestScenarioRunner(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)

        self.patches = [
            patch.object(scenario_store_module, "SCENARIO_DIR", root / "scenarios"),
            patch.object(scenario_store_module, "SCENARIO_FILE", root / "scenarios" / "scenarios.json"),
            patch.object(scenario_store_module, "RUN_HISTORY_FILE", root / "scenarios" / "run_history.json"),
            patch.object(scenario_store_module, "SCHEMA_FILE", root / "scenarios" / "scenario_schema.json"),
            patch.object(scenario_store_module, "SCREENSHOT_DIR", root / "scenarios" / "screenshots"),
            patch.object(scenario_store_module, "SAMPLE_DIR", root / "scenarios" / "samples"),
        ]
        for p in self.patches:
            p.start()

        self.store = scenario_store_module.ScenarioStore()
        self.runner = ScenarioRunner(self.store)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp_dir.cleanup()

    def test_wait_only_scenario_passes(self):
        scenario = {
            "id": "scn-test-wait",
            "title": "Wait Scenario",
            "steps": [
                {"id": "s1", "type": "wait", "params": {"seconds": 0.01}},
            ],
            "assertions": [],
            "expected_observables": [],
            "detector_expectations": [],
        }

        out = _run(self.runner.run_scenario(scenario))
        self.assertEqual(out["status"], "passed")
        self.assertEqual(out["completed_steps"], 1)

    def test_manual_checkpoint_resume(self):
        async def _case():
            scenario = {
                "id": "scn-test-manual",
                "title": "Manual checkpoint scenario",
                "steps": [
                    {
                        "id": "s1",
                        "type": "manual_checkpoint",
                        "params": {
                            "instruction": "Resume this checkpoint",
                            "timeout_seconds": 5,
                        },
                    },
                    {"id": "s2", "type": "wait", "params": {"seconds": 0.01}},
                ],
                "assertions": [],
                "expected_observables": [],
                "detector_expectations": [],
            }

            task = asyncio.create_task(self.runner.run_scenario(scenario))
            await asyncio.sleep(0.15)
            status = self.runner.status()
            self.assertTrue(status["paused"])
            resumed = self.runner.resume_manual_checkpoint(note="ack")
            self.assertTrue(resumed)
            result = await task
            self.assertEqual(result["status"], "passed")

        _run(_case())

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
                 patch("app.automation.scenario_runner.platform.system", return_value="Linux"), \
                 patch("app.automation.scenario_runner.shutil.which", side_effect=_which), \
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
