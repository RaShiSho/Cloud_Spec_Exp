from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ADAPTER_DIR = Path(__file__).resolve().parents[1] / "baselines" / "repairagent"
LAUNCHER_PATH = ADAPTER_DIR / "launch.py"
SPEC = importlib.util.spec_from_file_location("repairagent_oci_launch", LAUNCHER_PATH)
assert SPEC is not None and SPEC.loader is not None
launch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = launch
SPEC.loader.exec_module(launch)


class RepairAgentLauncherTests(unittest.TestCase):
    def test_prepares_isolated_upstream_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            baseline_root = root / "RepairAgent" / "repair_agent"
            baseline_root.mkdir(parents=True)
            (baseline_root / "prompt_settings.yaml").write_text(
                "constraints: []\nresources: []\nbest_practices: []\n", encoding="utf-8"
            )
            task = root / "task.md"
            task.write_text("Repair OCI behavior.\n", encoding="utf-8")

            run_dir = launch.prepare_run_layout(output, baseline_root, task)

            self.assertTrue((run_dir / "auto_gpt_workspace" / "oci_1_buggy").is_dir())
            self.assertEqual((run_dir / "task.md").read_text(encoding="utf-8"), "Repair OCI behavior.\n")
            ai_settings = yaml.safe_load((run_dir / "ai_settings.yaml").read_text(encoding="utf-8"))
            self.assertEqual(
                ai_settings["ai_goals"][0],
                'Locate the Bug: systematically identify the bug within the project "oci" and bug index "1".',
            )
            previous_cwd = Path.cwd()
            try:
                os.chdir(run_dir)
                cycle_instruction = Path("cycle_instruction_text.txt").read_text(encoding="utf-8")
            finally:
                os.chdir(previous_cwd)
            self.assertIn("Respond with exactly one JSON object", cycle_instruction)
            self.assertIn("current state's Commands section", cycle_instruction)
            self.assertIn("exact argument names", cycle_instruction)
            self.assertNotIn("Chart", cycle_instruction)
            self.assertNotIn("Java", cycle_instruction)
            self.assertNotIn("Defects4J", cycle_instruction)
            self.assertNotIn("run_tests", cycle_instruction)
            interface = json.loads((run_dir / "commands_interface.json").read_text(encoding="utf-8"))
            self.assertEqual(
                interface["write_fix"],
                ["project_name", "bug_index", "changes_dicts"],
            )
            fix_format = (run_dir / "fix_format").read_text(encoding="utf-8")
            self.assertIn("new_lines MUST be a JSON list of strings", fix_format)
            self.assertIn(
                '"new_lines":["first inserted line","second inserted line"]',
                fix_format,
            )
            self.assertIn("Do not return new_lines as one multiline string", fix_format)
            hyperparams = json.loads((run_dir / "hyperparams.json").read_text(encoding="utf-8"))
            self.assertEqual(hyperparams["external_fix_strategy"], 0)


if __name__ == "__main__":
    unittest.main()
