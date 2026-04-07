"""Tests for workflow storage, validation, and CRUD operations."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.core.workflow_store as workflow_store_module


class TestWorkflowStore(unittest.TestCase):

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

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp_dir.cleanup()

    def test_default_workflows_exist(self):
        items = self.store.list_workflows()
        self.assertGreaterEqual(len(items), 3)
        ids = {w.get("id") for w in items}
        self.assertIn("wf-vscode-copilot-basic", ids)

    def test_create_update_duplicate_delete(self):
        payload = {
            "name": "Test Flow",
            "description": "desc",
            "platform": "linux",
            "enabled": True,
            "tags": ["a", "b"],
            "steps": [
                {"id": "s1", "type": "wait", "params": {"seconds": 1}},
            ],
            "assertions": [],
            "metadata": {},
        }

        created = self.store.create_workflow(payload)
        self.assertTrue(created["id"].startswith("wf-"))

        updated = self.store.update_workflow(created["id"], {
            **created,
            "name": "Updated Flow",
        })
        self.assertEqual(updated["name"], "Updated Flow")

        cloned = self.store.duplicate_workflow(created["id"])
        self.assertNotEqual(cloned["id"], created["id"])
        self.assertIn("copy", cloned["name"].lower())

        removed = self.store.delete_workflow(created["id"])
        self.assertTrue(removed)

    def test_validation_requires_step_fields(self):
        with self.assertRaises(workflow_store_module.WorkflowValidationError):
            self.store.create_workflow({
                "name": "Bad Flow",
                "steps": [
                    {"id": "s1", "type": "open_website", "params": {}},
                ],
            })


if __name__ == "__main__":
    unittest.main()
