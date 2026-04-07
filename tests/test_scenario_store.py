"""Tests for scenario storage, hierarchy model, and CRUD behavior."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.core.scenario_store as scenario_store_module
from app.core.scenario_definitions import SCENARIO_TEMPLATES


class TestScenarioStore(unittest.TestCase):

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

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp_dir.cleanup()

    def test_built_in_scenarios_seeded(self):
        items = self.store.list_scenarios()
        self.assertGreaterEqual(len(items), 12)
        ids = {item.get("id") for item in items}
        self.assertIn("scn-vscode-copilot-no-login", ids)
        self.assertIn("scn-upload-file-summary", ids)

    def test_tree_hierarchy_category_family_scenario(self):
        tree = self.store.build_tree()
        self.assertGreaterEqual(len(tree), 1)
        first = tree[0]
        self.assertIn("category", first)
        self.assertIn("families", first)

        # Every family node contains scenario children.
        any_family = first["families"][0]
        self.assertIn("family", any_family)
        self.assertIn("scenarios", any_family)

    def test_template_catalog_maps_to_seed_template_scenarios(self):
        items = self.store.list_scenarios()
        ids = {item.get("id") for item in items}

        for template in SCENARIO_TEMPLATES:
            scenario_id = template.get("scenario_id")
            self.assertIsInstance(scenario_id, str)
            self.assertTrue(scenario_id)
            self.assertIn(scenario_id, ids)

    def test_create_update_duplicate_delete(self):
        payload = {
            "title": "Scenario CRUD test",
            "description": "desc",
            "category": "IDE Assistants",
            "family": "Unit",
            "tags": ["desktop"],
            "risk_level": "medium",
            "platforms": ["linux"],
            "auth_required": False,
            "prerequisites": ["none"],
            "steps": [{"id": "s1", "type": "wait", "params": {"seconds": 0.1}}],
            "assertions": ["a"],
            "expected_observables": ["o"],
            "detector_expectations": ["d"],
            "cleanup_steps": ["c"],
            "metadata": {},
        }

        created = self.store.create_scenario(payload)
        self.assertTrue(created["id"].startswith("scn-"))

        updated = self.store.update_scenario(created["id"], {
            **created,
            "title": "Scenario CRUD updated",
        })
        self.assertEqual(updated["title"], "Scenario CRUD updated")

        cloned = self.store.duplicate_scenario(created["id"])
        self.assertNotEqual(cloned["id"], created["id"])
        self.assertIn("copy", cloned["title"].lower())

        removed = self.store.delete_scenario(created["id"])
        self.assertTrue(removed)

    def test_validation_rejects_missing_required_step_field(self):
        with self.assertRaises(scenario_store_module.ScenarioValidationError):
            self.store.create_scenario({
                "title": "Bad Scenario",
                "description": "bad",
                "category": "IDE Assistants",
                "family": "Bad",
                "tags": [],
                "risk_level": "high",
                "platforms": ["linux"],
                "auth_required": False,
                "prerequisites": [],
                "steps": [{"id": "s1", "type": "open_website", "params": {}}],
                "assertions": [],
                "expected_observables": [],
                "detector_expectations": [],
                "cleanup_steps": [],
            })


if __name__ == "__main__":
    unittest.main()
