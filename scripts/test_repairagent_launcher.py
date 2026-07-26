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
WRAPPER_PATH = ADAPTER_DIR / "run_oci_repair.sh"
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

            with mock.patch.dict(
                os.environ,
                {"REPAIRAGENT_OCI_MAX_CYCLES": "40"},
            ):
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
            commands_by_state = json.loads(
                (run_dir / "commands_by_state.json").read_text(encoding="utf-8")
            )
            candidate_commands = commands_by_state["trying out candidate fixes"]
            self.assertIn("write_fix", candidate_commands)
            self.assertIn("try_fixes", candidate_commands)
            self.assertIn("goals_accomplished", candidate_commands)
            self.assertNotIn("read_range", candidate_commands)
            self.assertNotIn("go_back_to_collect_more_info", candidate_commands)
            self.assertNotIn("discard_hypothesis", candidate_commands)
            fix_format = (run_dir / "fix_format").read_text(encoding="utf-8")
            self.assertIn("new_lines MUST be a JSON list of strings", fix_format)
            self.assertIn(
                '"new_lines":["first inserted line","second inserted line"]',
                fix_format,
            )
            self.assertIn("Do not return new_lines as one multiline string", fix_format)
            hyperparams = json.loads((run_dir / "hyperparams.json").read_text(encoding="utf-8"))
            self.assertEqual(hyperparams["budget_control"]["name"], "FORCED")
            self.assertEqual(hyperparams["budget_control"]["T1"], 8)
            self.assertEqual(hyperparams["budget_control"]["T2"], 20)
            self.assertEqual(hyperparams["external_fix_strategy"], 0)

    def test_adapts_generic_task_for_repairagent_commands(self) -> None:
        generic = (
            "Writable target repository:\n"
            "/tmp/runtime\n\n"
            "Required first command:\n"
            "cd /tmp/runtime && git rev-parse HEAD && git status --short\n\n"
            "Inspect and repair the runtime.\n"
        )

        adapted = launch.adapt_task_text(generic)

        self.assertNotIn("Required first command:", adapted)
        self.assertNotIn("git rev-parse", adapted)
        self.assertIn("verified by the launcher", adapted)
        self.assertIn("Use only the commands exposed", adapted)
        self.assertIn("Inspect and repair the runtime.", adapted)

    def test_compacts_validation_and_read_context(self) -> None:
        self.assertEqual(
            launch.compact_validation_result(True, "warning\n" * 10_000),
            "0 failing tests.\nBuild validation passed.",
        )
        failed = launch.compact_validation_result(False, "x" * 20_000)
        self.assertIn("[validation output truncated]", failed)
        self.assertLess(len(failed), 7_000)

        read_files = {
            f"src/file_{index}.c": {f"{index},{index + 10}": "x" * 2_000}
            for index in range(10)
        }
        context = launch.compact_read_files_context(
            types.SimpleNamespace(read_files=read_files)
        )
        self.assertIn("4 older read result(s) were omitted", context)
        self.assertNotIn("src/file_0.c", context)
        self.assertIn("src/file_9.c", context)
        self.assertLessEqual(
            len(context),
            launch.MAX_READ_CONTEXT_CHARS + 500,
        )

    def test_forced_state_thresholds_scale_to_cycle_budget(self) -> None:
        self.assertEqual(launch.forced_state_thresholds(40), (8, 20))
        self.assertEqual(launch.forced_state_thresholds(4), (1, 2))
        self.assertEqual(launch.forced_state_thresholds(2), (1, 1))

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

    def test_installs_oci_functions_over_cached_defects4j_bindings(self) -> None:
        def original_static_tool(*args, **kwargs):
            del args, kwargs
            return "defects4j"

        fake_autogpt = types.ModuleType("autogpt")
        fake_autogpt.__path__ = []
        fake_commands = types.ModuleType("autogpt.commands")
        fake_commands.__path__ = []
        fake_static = types.ModuleType("autogpt.commands.defects4j_static")
        fake_agents = types.ModuleType("autogpt.agents")
        fake_agents.__path__ = []
        fake_base = types.ModuleType("autogpt.agents.base")
        fake_agent = types.ModuleType("autogpt.agents.agent")
        fake_oci_tools = types.ModuleType("oci_tools")

        fake_static.get_info = original_static_tool
        fake_static.run_tests = original_static_tool
        fake_static.create_fix_template = original_static_tool
        fake_static.get_detailed_list_of_buggy_lines = original_static_tool
        fake_static.query_for_mutants = original_static_tool
        fake_base.get_info = original_static_tool
        fake_base.run_tests = original_static_tool
        fake_base.create_fix_template = original_static_tool
        fake_agent.get_detailed_list_of_buggy_lines = original_static_tool
        fake_agent.query_for_mutants = original_static_tool

        class FakeAgent:
            def execute(self, command_name, command_args, user_input):
                del self, command_args, user_input
                return f"executed:{command_name}"

        class FakeBaseAgent:
            pass

        fake_agent.Agent = FakeAgent
        fake_base.BaseAgent = FakeBaseAgent
        fake_oci_tools.task_text = lambda: "OCI task"
        fake_oci_tools.source_inventory = lambda: "runtime.c"
        fake_oci_tools.run_validation = lambda: (True, "build passed")
        fake_oci_tools.repository = lambda: Path("unused")

        fake_autogpt.commands = fake_commands
        fake_autogpt.agents = fake_agents
        fake_commands.defects4j_static = fake_static
        fake_agents.base = fake_base
        fake_agents.agent = fake_agent
        modules = {
            "autogpt": fake_autogpt,
            "autogpt.commands": fake_commands,
            "autogpt.commands.defects4j_static": fake_static,
            "autogpt.agents": fake_agents,
            "autogpt.agents.base": fake_base,
            "autogpt.agents.agent": fake_agent,
            "oci_tools": fake_oci_tools,
        }

        with mock.patch.dict(sys.modules, modules):
            launch.install_oci_tool_layer()

            self.assertIs(fake_base.get_info, fake_static.get_info)
            self.assertIs(fake_base.run_tests, fake_static.run_tests)
            self.assertIs(fake_base.create_fix_template, fake_static.create_fix_template)
            self.assertIs(
                fake_agent.get_detailed_list_of_buggy_lines,
                fake_static.get_detailed_list_of_buggy_lines,
            )
            self.assertIs(fake_agent.query_for_mutants, fake_static.query_for_mutants)
            self.assertIs(
                FakeBaseAgent.construct_read_files_context,
                launch.compact_read_files_context,
            )
            self.assertEqual(
                json.loads(fake_base.create_fix_template("oci", 1)),
                [
                    {
                        "file_name": "path/to/source",
                        "insertions": [],
                        "deletions": [],
                        "modifications": [],
                    }
                ],
            )
            self.assertEqual(
                fake_agent.get_detailed_list_of_buggy_lines("oci", 1),
                "OCI task",
            )
            self.assertEqual(fake_agent.query_for_mutants("prompt", object()), "[]")

            wrapped_execute = FakeAgent.execute
            launch.install_oci_tool_layer()
            self.assertIs(FakeAgent.execute, wrapped_execute)

    def test_wrapper_timeout_finalizes_launcher_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
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
                    "test(repairagent): initialize timeout fixture",
                ],
                check=True,
            )
            source.write_text("partial candidate\n", encoding="utf-8")
            metadata_path = root / "launcher_metadata.json"
            metadata_path.write_text('{"status":"starting"}\n', encoding="utf-8")

            finalized = launch.finalize_timeout_metadata(
                metadata_path,
                repo,
                3300,
            )
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

            self.assertTrue(finalized)
            self.assertEqual(metadata["status"], "terminated")
            self.assertEqual(metadata["termination_signal"], "SIGTERM")
            self.assertEqual(metadata["termination_source"], "wrapper_timeout")
            self.assertEqual(metadata["timeout_seconds"], 3300)
            self.assertTrue(metadata["patch_is_partial"])
            self.assertGreater(metadata["patch_size_bytes"], 0)
            self.assertFalse(
                launch.finalize_timeout_metadata(metadata_path, repo, 3300)
            )

        wrapper = WRAPPER_PATH.read_text(encoding="utf-8")
        self.assertIn('if [ "$EXIT_CODE" -eq 124 ]', wrapper)
        self.assertIn("finalize_launcher_timeout_metadata", wrapper)
        self.assertIn('update_wrapper_metadata "timed_out"', wrapper)

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
