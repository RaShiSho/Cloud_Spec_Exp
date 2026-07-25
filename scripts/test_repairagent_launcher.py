from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

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
            self.assertEqual(interface["goals_accomplished"], ["reason"])
            fix_format = (run_dir / "fix_format").read_text(encoding="utf-8")
            self.assertIn("new_lines MUST be a JSON list of strings", fix_format)
            self.assertIn(
                '"new_lines":["first inserted line","second inserted line"]',
                fix_format,
            )
            self.assertIn("Do not return new_lines as one multiline string", fix_format)
            hyperparams = json.loads((run_dir / "hyperparams.json").read_text(encoding="utf-8"))
            self.assertEqual(hyperparams["external_fix_strategy"], 0)

    def test_completion_hook_stops_after_original_execute_retains_diff(self) -> None:
        events = []

        def original_execute(agent, command_name, command_args, user_input):
            del agent, command_args, user_input
            events.append(f"executed:{command_name}")
            return "Candidate retained; build validation reports 0 failing tests."

        wrapped = launch.completion_aware_execute(
            original_execute,
            lambda: "diff --git a/runtime.c b/runtime.c\n",
        )

        with self.assertRaises(launch.CandidatePatchReady) as raised:
            wrapped(object(), "write_fix", {"changes_dicts": []}, None)

        self.assertEqual(events, ["executed:write_fix"])
        self.assertEqual(raised.exception.command_name, "write_fix")
        self.assertTrue(raised.exception.patch.strip())

    def test_completion_hook_ignores_failed_empty_and_non_fix_commands(self) -> None:
        def original_execute(agent, command_name, command_args, user_input):
            del agent, command_args, user_input
            return f"result:{command_name}"

        empty_patch_wrapper = launch.completion_aware_execute(
            original_execute,
            lambda: "",
        )
        self.assertEqual(
            empty_patch_wrapper(object(), "write_fix", {}, None),
            "result:write_fix",
        )

        non_fix_wrapper = launch.completion_aware_execute(
            original_execute,
            lambda: "diff --git a/runtime.c b/runtime.c\n",
        )
        self.assertEqual(
            non_fix_wrapper(object(), "read_range", {}, None),
            "result:read_range",
        )

    def test_completion_and_termination_metadata_are_explicit(self) -> None:
        completion = launch.CandidatePatchReady(
            "try_fixes",
            "candidate retained",
            "patch",
        )
        completed = {"status": "starting"}
        launch.update_completed_metadata(completed, completion, "é\n")

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(
            completed["completion_reason"],
            "retained_candidate_build_passed",
        )
        self.assertEqual(
            completed["behavioral_validation"],
            "pending_outer_oracle",
        )
        self.assertEqual(completed["successful_command"], "try_fixes")
        self.assertEqual(completed["patch_size_bytes"], 3)

        terminated = {"status": "starting"}
        launch.update_terminated_metadata(terminated, 15, "partial\n")

        self.assertEqual(terminated["status"], "terminated")
        self.assertEqual(terminated["termination_signal"], "SIGTERM")
        self.assertEqual(terminated["behavioral_validation"], "not_started")
        self.assertTrue(terminated["patch_is_partial"])

    def test_run_converts_candidate_ready_into_successful_launcher_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline_repo = root / "RepairAgent"
            baseline_root = baseline_repo / "repair_agent"
            upstream_agent = baseline_root / "autogpt" / "agents" / "base.py"
            upstream_agent.parent.mkdir(parents=True)
            upstream_agent.write_text("# fixture\n", encoding="utf-8")
            (baseline_root / "prompt_settings.yaml").write_text(
                "constraints: []\nresources: []\nbest_practices: []\n",
                encoding="utf-8",
            )
            repo = root / "runtime"
            repo.mkdir()
            source = repo / "runtime.c"
            source.write_text("original\n", encoding="utf-8")
            subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "runtime.c"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=RepairAgent Test",
                    "-c",
                    "user.email=repairagent@example.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "test(repairagent): initialize launcher fixture",
                ],
                check=True,
            )
            task = root / "task.md"
            task.write_text("Repair runtime.\n", encoding="utf-8")
            output = root / "output"
            args = types.SimpleNamespace(
                baseline_repo=str(baseline_repo),
                repo=str(repo),
                task_file=str(task),
                output_dir=str(output),
                model="fixture-model",
                test_command="true",
                source_extensions=".c,.h",
                max_cycles=4,
                test_timeout_seconds=10,
                base_url="",
            )

            fake_autogpt = types.ModuleType("autogpt")
            fake_autogpt.__path__ = []
            fake_app = types.ModuleType("autogpt.app")
            fake_app.__path__ = []
            fake_main = types.ModuleType("autogpt.app.main")

            def run_auto_gpt(**kwargs):
                del kwargs
                source.write_text("candidate\n", encoding="utf-8")
                patch = launch.git_diff(repo)
                raise launch.CandidatePatchReady("write_fix", "retained", patch)

            fake_main.run_auto_gpt = run_auto_gpt
            modules = {
                "autogpt": fake_autogpt,
                "autogpt.app": fake_app,
                "autogpt.app.main": fake_main,
            }
            with (
                mock.patch.object(launch, "parse_args", return_value=args),
                mock.patch.object(launch, "install_oci_tool_layer"),
                mock.patch.dict(sys.modules, modules),
            ):
                returncode = launch.run()

            metadata = json.loads(
                (output / "launcher_metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(returncode, 0)
            self.assertEqual(metadata["status"], "completed")
            self.assertEqual(
                metadata["completion_reason"],
                "retained_candidate_build_passed",
            )
            self.assertEqual(
                metadata["behavioral_validation"],
                "pending_outer_oracle",
            )
            self.assertGreater(metadata["patch_size_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
