from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
import run_oci_experiment as runner  # noqa: E402
from oci_common import CommandResult  # noqa: E402


class RunOciExperimentGitDiffTests(unittest.TestCase):
    def test_collects_staged_tracked_changes_against_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            source = repo / "runtime.c"
            subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
            source.write_text("original\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "runtime.c"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Runner Test",
                    "-c",
                    "user.email=runner-test@example.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "test(runner): initialize fixture",
                ],
                check=True,
            )
            source.write_text("changed\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "runtime.c"], check=True)

            patch = runner.git_diff(repo)

        self.assertIn("-original", patch)
        self.assertIn("+changed", patch)


class RunOciExperimentResumeTests(unittest.TestCase):
    def test_does_not_skip_when_result_directory_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            config = {"experiment": {"output_dir": str(output_root)}}
            baseline = {"name": "autocoderover"}
            case = {"case_id": "crun-13"}

            result = runner.load_terminal_result(config, baseline, case)

        self.assertIsNone(result)

    def test_skips_existing_results_regardless_of_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            config = {"experiment": {"output_dir": str(output_root)}}
            baseline = {"name": "autocoderover"}

            for status in ("done", "error", "running"):
                with self.subTest(status=status):
                    case = {"case_id": f"crun-{status}"}
                    output_dir = output_root / "autocoderover" / case["case_id"]
                    output_dir.mkdir(parents=True)
                    (output_dir / "metadata.json").write_text(
                        json.dumps({"status": status}), encoding="utf-8"
                    )

                    result = runner.load_terminal_result(config, baseline, case)

                    self.assertIsNotNone(result)
                    assert result is not None
                    self.assertEqual(result["status"], status)
                    self.assertTrue(result["resumed_skip"])
                    self.assertEqual(
                        result["resume_reason"], "output_directory_exists"
                    )

    def test_skips_empty_or_partial_result_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            config = {"experiment": {"output_dir": str(output_root)}}
            baseline = {"name": "autocoderover"}

            for case_id, fixture_name, fixture_content in (
                ("crun-empty", None, None),
                ("crun-task", "task.md", "partial task"),
                ("crun-invalid", "metadata.json", "{invalid"),
            ):
                with self.subTest(case_id=case_id):
                    case = {"case_id": case_id}
                    output_dir = output_root / "autocoderover" / case_id
                    output_dir.mkdir(parents=True)
                    if fixture_name is not None:
                        (output_dir / fixture_name).write_text(
                            fixture_content or "", encoding="utf-8"
                        )

                    result = runner.load_terminal_result(config, baseline, case)

                    self.assertIsNotNone(result)
                    assert result is not None
                    self.assertEqual(result["status"], "skipped_existing")
                    self.assertEqual(result["case"], case)
                    self.assertEqual(result["baseline"], "autocoderover")
                    self.assertEqual(result["output_dir"], str(output_dir))
                    self.assertTrue(result["resumed_skip"])
                    self.assertEqual(
                        result["resume_reason"], "output_directory_exists"
                    )

    def test_resume_does_not_run_or_clean_an_existing_case(self) -> None:
        case = {"case_id": "crun-13"}
        baseline = {"name": "metagpt"}
        existing_result = {
            "case": case,
            "baseline": "metagpt",
            "status": "error",
            "resumed_skip": True,
            "resume_reason": "output_directory_exists",
        }
        args = mock.Mock(
            clean=False,
            resume=True,
            config="experiment.yaml",
            case=None,
            baseline=None,
            limit=None,
            dry_run=False,
        )

        with (
            mock.patch.object(runner, "parse_args", return_value=args),
            mock.patch.object(runner, "load_config", return_value={}),
            mock.patch.object(runner, "selected_cases", return_value=([case], [])),
            mock.patch.object(runner, "enabled_baselines", return_value=[baseline]),
            mock.patch.object(runner, "preflight", return_value=[]),
            mock.patch.object(
                runner, "load_terminal_result", return_value=existing_result
            ),
            mock.patch.object(runner, "run_one") as run_one,
            mock.patch.object(runner, "clean_previous_run") as clean_previous_run,
            mock.patch("builtins.print"),
        ):
            exit_code = runner.main()

        self.assertEqual(exit_code, 0)
        run_one.assert_not_called()
        clean_previous_run.assert_not_called()


class RunOciExperimentFailureTests(unittest.TestCase):
    def test_classifies_child_return_code_124_as_timeout(self) -> None:
        failure = CommandResult(
            command="run-baseline",
            cwd=None,
            returncode=124,
            stdout="",
            stderr="misleading last line",
        )

        message = runner.command_failure_message("baseline command", failure)

        self.assertIn("timed out", message)
        self.assertNotIn("misleading last line", message)

    def test_stops_after_baseline_command_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source"
            source_dir.mkdir()
            case_dir = root / "case"
            case_dir.mkdir()
            output_root = root / "results"
            config = {
                "experiment": {
                    "name": "test-experiment",
                    "output_dir": str(output_root),
                    "worktree_root": str(root / "worktrees"),
                    "timeout_seconds": 30,
                },
                "model": {"name": "test-model"},
                "benchmark": {},
                "runtimes": {
                    "crun": {
                        "source_dir": str(source_dir),
                        "build_command": "build-runtime",
                        "runtime_path": "crun",
                        "reference_runtime": "runc",
                        "source_extensions": [".c", ".h"],
                    }
                },
            }
            case = {
                "case_id": "crun-13",
                "runtime": "crun",
                "case_dir": str(case_dir),
                "title": "test case",
                "url": "https://example.invalid/13",
                "category": "test",
            }
            baseline = {
                "name": "autocoderover",
                "kind": "generic_repair_agent",
                "command": "run-baseline",
                "timeout_seconds": 30,
            }
            failure = CommandResult(
                command="run-baseline",
                cwd=str(source_dir),
                returncode=1,
                stdout="",
                stderr="traceback\nfatal detail\n",
            )

            with (
                mock.patch.object(runner, "create_worktree"),
                mock.patch.object(runner, "run_command", return_value=failure) as run,
                mock.patch.object(
                    runner, "git_diff", return_value="partial diff\n"
                ) as git_diff,
            ):
                result = runner.run_one(
                    config=config,
                    case=case,
                    baseline=baseline,
                )

            metadata = json.loads(
                (output_root / "autocoderover" / "crun-13" / "metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            oracle = json.loads(
                (output_root / "autocoderover" / "crun-13" / "oracle.json").read_text(
                    encoding="utf-8"
                )
            )
            candidate_patch = (
                output_root / "autocoderover" / "crun-13" / "candidate.patch"
            ).read_text(encoding="utf-8")

        self.assertEqual(run.call_count, 1)
        git_diff.assert_called_once()
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["patch_is_partial"])
        self.assertGreater(result["patch_size_bytes"], 0)
        self.assertIn("return code 1: fatal detail", result["error"])
        self.assertGreater(result["started_at_unix"], 1_000_000_000)
        self.assertEqual(metadata["error"], result["error"])
        self.assertTrue(metadata["patch_is_partial"])
        self.assertIn("metrics", metadata)
        self.assertEqual(
            metadata["elapsed_seconds"],
            metadata["metrics"]["pipeline_elapsed_seconds"],
        )
        self.assertIsNotNone(metadata["metrics"]["agent_elapsed_seconds"])
        self.assertEqual(candidate_patch, "partial diff\n")
        self.assertEqual(oracle["error_type"], "baseline")
        self.assertEqual(oracle["message"], result["error"])

    def test_agentless_task_uses_repository_relative_edit_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source"
            source_dir.mkdir()
            case_dir = root / "case"
            case_dir.mkdir()
            output_root = root / "results"
            config = {
                "experiment": {
                    "name": "agentless-prompt-test",
                    "output_dir": str(output_root),
                    "worktree_root": str(root / "worktrees"),
                    "timeout_seconds": 30,
                },
                "model": {"name": "test-model"},
                "benchmark": {},
                "runtimes": {
                    "crun": {
                        "source_dir": str(source_dir),
                        "build_command": "build-runtime",
                        "runtime_path": "crun",
                        "reference_runtime": "runc",
                        "source_extensions": [".c", ".h"],
                    }
                },
            }
            case = {
                "case_id": "crun-13",
                "runtime": "crun",
                "case_dir": str(case_dir),
                "title": "test case",
                "url": "https://example.invalid/13",
                "category": "test",
            }
            baseline = {
                "name": "agentless-oci-adapted",
                "kind": "agentless_oci",
                "command": "run-baseline",
                "top_n_files": 5,
            }
            failure = CommandResult(
                command="run-baseline",
                cwd=None,
                returncode=1,
                stdout="",
                stderr="expected test failure",
            )

            def create_worktree(
                _source_dir: Path, worktree_dir: Path, _ref: str
            ) -> None:
                worktree_dir.mkdir(parents=True)
                (worktree_dir / "runtime.c").write_text(
                    "int main(void) { return 0; }\n", encoding="utf-8"
                )

            with (
                mock.patch.object(
                    runner, "create_worktree", side_effect=create_worktree
                ),
                mock.patch.object(runner, "run_command", return_value=failure),
                mock.patch.object(runner, "git_diff", return_value=""),
            ):
                runner.run_one(config=config, case=case, baseline=baseline)

            task_text = (
                output_root / "agentless-oci-adapted" / "crun-13" / "task.md"
            ).read_text(encoding="utf-8")
            task_row = json.loads(
                (
                    output_root
                    / "agentless-oci-adapted"
                    / "crun-13"
                    / "agentless_task.jsonl"
                )
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )

        self.assertIn(
            "use repository-relative file paths exactly as shown in the localized source files",
            task_text,
        )
        self.assertIn("Do not use absolute paths in `### <file>` headers.", task_text)
        self.assertNotIn("Use absolute paths when calling Editor tools", task_text)
        self.assertEqual(task_row["problem_statement"], task_text)


class RunOciExperimentMetricsTests(unittest.TestCase):
    @staticmethod
    def command_result(
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> CommandResult:
        return CommandResult(
            command="baseline",
            cwd=None,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def test_extracts_mini_swe_trajectory_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            trajectory = {
                "info": {
                    "model_stats": {
                        "instance_cost": 0.25,
                        "api_calls": 2,
                    }
                },
                "messages": [
                    {
                        "role": "assistant",
                        "extra": {
                            "response": {
                                "usage": {
                                    "prompt_tokens": 100,
                                    "completion_tokens": 10,
                                    "total_tokens": 110,
                                }
                            }
                        },
                    },
                    {
                        "role": "assistant",
                        "extra": {
                            "response": {
                                "usage": {
                                    "prompt_tokens": 200,
                                    "completion_tokens": 20,
                                    "total_tokens": 220,
                                }
                            }
                        },
                    },
                ],
            }
            (output_dir / "trajectory.json").write_text(
                json.dumps(trajectory), encoding="utf-8"
            )

            metrics = runner.collect_llm_metrics(
                baseline={"name": "mini-swe-agent", "kind": "mini_swe_agent"},
                output_dir=output_dir,
                baseline_result=self.command_result(),
            )

        self.assertEqual(metrics["tokens"]["prompt_tokens"], 300)
        self.assertEqual(metrics["tokens"]["completion_tokens"], 30)
        self.assertEqual(metrics["tokens"]["total_tokens"], 330)
        self.assertEqual(metrics["cost_usd"], 0.25)
        self.assertEqual(metrics["llm_calls"], 2)
        self.assertEqual(metrics["sources"], ["trajectory.json"])

    def test_agentless_deduplicates_completion_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            repair_logs = output_dir / "agentless-output" / "repair_logs"
            repair_logs.mkdir(parents=True)
            first = (
                "API response ChatCompletion(id='response-1', choices=[], "
                "usage=CompletionUsage(completion_tokens=10, "
                "prompt_tokens=100, total_tokens=110))"
            )
            second = (
                "API response ChatCompletion(id='response-2', choices=[], "
                "usage=CompletionUsage(completion_tokens=20, "
                "prompt_tokens=200, total_tokens=220))"
            )
            (repair_logs / "case.log").write_text(
                f"{first}\n{first}\n{second}\n", encoding="utf-8"
            )

            metrics = runner.collect_llm_metrics(
                baseline={
                    "name": "agentless-oci-adapted",
                    "kind": "agentless_oci",
                },
                output_dir=output_dir,
                baseline_result=self.command_result(),
            )

        self.assertEqual(metrics["tokens"]["total_tokens"], 330)
        self.assertEqual(metrics["llm_calls"], 2)
        self.assertIsNone(metrics["cost_usd"])
        self.assertIn("cost_usd", metrics["missing"])

    def test_extracts_metagpt_launcher_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            baseline_output = output_dir / "metagpt-output"
            baseline_output.mkdir()
            (baseline_output / "launcher_metadata.json").write_text(
                json.dumps(
                    {
                        "llm_metrics": {
                            "tokens": {
                                "prompt_tokens": 300,
                                "completion_tokens": 30,
                                "total_tokens": 330,
                            },
                            "cost_usd": 0.00036,
                            "llm_calls": 2,
                            "warnings": [],
                        }
                    }
                ),
                encoding="utf-8",
            )

            metrics = runner.collect_llm_metrics(
                baseline={
                    "name": "metagpt",
                    "kind": "generic_repair_agent",
                    "output_dir_name": "metagpt-output",
                },
                output_dir=output_dir,
                baseline_result=self.command_result(),
            )

        self.assertEqual(metrics["tokens"]["prompt_tokens"], 300)
        self.assertEqual(metrics["tokens"]["completion_tokens"], 30)
        self.assertEqual(metrics["tokens"]["total_tokens"], 330)
        self.assertEqual(metrics["cost_usd"], 0.00036)
        self.assertEqual(metrics["llm_calls"], 2)
        self.assertEqual(
            metrics["sources"], [str(Path("metagpt-output") / "launcher_metadata.json")]
        )

    def test_metagpt_unknown_model_price_keeps_cost_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            baseline_output = output_dir / "metagpt-output"
            baseline_output.mkdir()
            (baseline_output / "launcher_metadata.json").write_text(
                json.dumps(
                    {
                        "llm_metrics": {
                            "tokens": {
                                "prompt_tokens": 100,
                                "completion_tokens": 20,
                                "total_tokens": 120,
                            },
                            "cost_usd": None,
                            "llm_calls": 1,
                            "warnings": ["missing_model_price:gpt-5.5"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            metrics = runner.collect_llm_metrics(
                baseline={"name": "metagpt", "kind": "generic_repair_agent"},
                output_dir=output_dir,
                baseline_result=self.command_result(),
            )

        self.assertEqual(metrics["tokens"]["total_tokens"], 120)
        self.assertEqual(metrics["llm_calls"], 1)
        self.assertIsNone(metrics["cost_usd"])
        self.assertIn("cost_usd", metrics["missing"])
        self.assertIn(
            "metagpt:missing_model_price:gpt-5.5", metrics["warnings"]
        )

    def test_autocoderover_zero_cost_is_marked_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            log_dir = output_dir / "autocoderover-output" / "run"
            log_dir.mkdir(parents=True)
            (log_dir / "info.log").write_text(
                "API request cost info: input_tokens=100, "
                "output_tokens=20, cost=0.000000\n",
                encoding="utf-8",
            )

            metrics = runner.collect_llm_metrics(
                baseline={"name": "autocoderover", "kind": "generic_repair_agent"},
                output_dir=output_dir,
                baseline_result=self.command_result(),
            )

        self.assertEqual(metrics["tokens"]["total_tokens"], 120)
        self.assertEqual(metrics["llm_calls"], 1)
        self.assertIsNone(metrics["cost_usd"])
        self.assertIn("zero_cost_with_nonzero_tokens", metrics["warnings"])

    def test_repairagent_uses_last_cumulative_snapshot(self) -> None:
        stdout = "\n".join(
            [
                "Tokens: 1,000 prompt + 100 completion | Cost: $0.1000",
                "Tokens: 2,500 prompt + 250 completion | Cost: $0.2500",
            ]
        )
        metrics = runner.collect_llm_metrics(
            baseline={"name": "repairagent", "kind": "generic_repair_agent"},
            output_dir=Path("."),
            baseline_result=self.command_result(stdout=stdout),
        )

        self.assertEqual(metrics["tokens"]["prompt_tokens"], 2500)
        self.assertEqual(metrics["tokens"]["completion_tokens"], 250)
        self.assertEqual(metrics["tokens"]["total_tokens"], 2750)
        self.assertEqual(metrics["cost_usd"], 0.25)
        self.assertEqual(metrics["llm_calls"], 2)

    def test_invalid_trajectory_is_best_effort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "trajectory.json").write_text("{invalid", encoding="utf-8")

            metrics = runner.collect_llm_metrics(
                baseline={"name": "mini-swe-agent", "kind": "mini_swe_agent"},
                output_dir=output_dir,
                baseline_result=self.command_result(),
            )

        self.assertIsNone(metrics["tokens"]["total_tokens"])
        self.assertIsNone(metrics["cost_usd"])
        self.assertIsNone(metrics["llm_calls"])
        self.assertIn("tokens", metrics["missing"])
        self.assertTrue(
            any(item.startswith("invalid_trajectory:") for item in metrics["warnings"])
        )

    def test_finalize_metadata_preserves_elapsed_compatibility(self) -> None:
        metadata = {"status": "error"}
        metrics = runner.empty_metrics()
        metrics["agent_elapsed_seconds"] = 2.0
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            with mock.patch.object(runner.time, "monotonic", return_value=15.5):
                result = runner.finalize_metadata(
                    metadata,
                    metrics=metrics,
                    started_monotonic=10.0,
                    output_dir=output_dir,
                )
            written = json.loads(
                (output_dir / "metadata.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result["elapsed_seconds"], 5.5)
        self.assertEqual(result["metrics"]["pipeline_elapsed_seconds"], 5.5)
        self.assertEqual(written["metrics"], result["metrics"])

    def test_oracle_pass_and_fail_are_completed_verdicts(self) -> None:
        for oracle_status, returncode in (("pass", 0), ("fail", 1)):
            with self.subTest(oracle_status=oracle_status), tempfile.TemporaryDirectory() as tmp:
                output_dir = Path(tmp)
                (output_dir / "oracle.json").write_text(
                    json.dumps({"status": oracle_status}),
                    encoding="utf-8",
                )
                metadata: dict[str, object] = {}

                runner.update_metadata_from_oracle(
                    metadata=metadata,
                    output_dir=output_dir,
                    oracle_result=self.command_result(returncode=returncode),
                )

            self.assertEqual(metadata["status"], "done")
            self.assertEqual(metadata["oracle_status"], oracle_status)
            self.assertNotIn("error", metadata)

    def test_oracle_error_marks_experiment_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "oracle.json").write_text(
                json.dumps(
                    {
                        "status": "error",
                        "error_type": "environment",
                        "message": "rootfs setup failed",
                    }
                ),
                encoding="utf-8",
            )
            metadata: dict[str, object] = {}

            runner.update_metadata_from_oracle(
                metadata=metadata,
                output_dir=output_dir,
                oracle_result=self.command_result(returncode=2),
            )

        self.assertEqual(metadata["status"], "error")
        self.assertEqual(metadata["oracle_status"], "error")
        self.assertEqual(metadata["error"], "rootfs setup failed")

    def test_missing_or_invalid_oracle_result_marks_experiment_error(self) -> None:
        for fixture, expected_status in (
            (None, "missing"),
            ("{invalid", "invalid"),
            ("[]", "invalid"),
            ('{"status": "unexpected"}', "invalid"),
        ):
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory() as tmp:
                output_dir = Path(tmp)
                if fixture is not None:
                    (output_dir / "oracle.json").write_text(
                        fixture,
                        encoding="utf-8",
                    )
                metadata: dict[str, object] = {}

                runner.update_metadata_from_oracle(
                    metadata=metadata,
                    output_dir=output_dir,
                    oracle_result=self.command_result(returncode=1),
                )

            self.assertEqual(metadata["status"], "error")
            self.assertEqual(metadata["oracle_status"], expected_status)
            self.assertIn("error", metadata)

    def test_no_patch_build_failure_and_success_record_timings(self) -> None:
        for scenario in ("no_patch", "build_failure", "oracle_failure", "success"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source_dir = root / "source"
                source_dir.mkdir()
                case_dir = root / "case"
                case_dir.mkdir()
                output_root = root / "results"
                worktree_root = root / "worktrees"
                config = {
                    "experiment": {
                        "name": "metrics-test",
                        "output_dir": str(output_root),
                        "worktree_root": str(worktree_root),
                        "timeout_seconds": 30,
                    },
                    "model": {"name": "test-model"},
                    "benchmark": {"rootfs_tar": str(root / "rootfs.tar.gz")},
                    "oracle": {"timeout_seconds": 1},
                    "runtimes": {
                        "crun": {
                            "source_dir": str(source_dir),
                            "build_command": "build-runtime",
                            "runtime_path": "crun",
                            "reference_runtime": "runc",
                            "source_extensions": [".c", ".h"],
                        }
                    },
                }
                case = {
                    "case_id": "crun-13",
                    "runtime": "crun",
                    "case_dir": str(case_dir),
                    "title": "test",
                    "url": "https://example.invalid/13",
                    "category": "test",
                }
                baseline = {
                    "name": "generic",
                    "kind": "generic_repair_agent",
                    "command": "run-baseline",
                }
                success = self.command_result()
                build_failure = self.command_result(returncode=1)
                oracle_failure = self.command_result(
                    returncode=1,
                    stderr="PermissionError: permission denied: floppy",
                )
                side_effects = {
                    "no_patch": [success],
                    "build_failure": [success, build_failure],
                    "oracle_failure": [success, success, oracle_failure],
                    "success": [success, success, success],
                }[scenario]
                side_effects_iter = iter(side_effects)

                def create_worktree(
                    _source_dir: Path, worktree_dir: Path, _ref: str
                ) -> None:
                    worktree_dir.mkdir(parents=True)
                    (worktree_dir / "crun").write_text("", encoding="utf-8")

                def run_command(command: object, **_kwargs: object) -> CommandResult:
                    result = next(side_effects_iter)
                    if (
                        scenario == "success"
                        and isinstance(command, list)
                        and "--output" in command
                    ):
                        output_index = command.index("--output") + 1
                        Path(command[output_index]).write_text(
                            json.dumps({"status": "pass"}),
                            encoding="utf-8",
                        )
                    return result

                patch = "" if scenario == "no_patch" else "diff\n"
                if scenario == "oracle_failure":
                    stale_output_dir = output_root / "generic" / "crun-13"
                    stale_output_dir.mkdir(parents=True)
                    (stale_output_dir / "oracle.json").write_text(
                        json.dumps({"status": "pass"}),
                        encoding="utf-8",
                    )
                with (
                    mock.patch.object(
                        runner, "create_worktree", side_effect=create_worktree
                    ),
                    mock.patch.object(
                        runner, "run_command", side_effect=run_command
                    ),
                    mock.patch.object(runner, "git_diff", return_value=patch),
                ):
                    result = runner.run_one(
                        config=config,
                        case=case,
                        baseline=baseline,
                    )

                metadata = json.loads(
                    (
                        output_root / "generic" / "crun-13" / "metadata.json"
                    ).read_text(encoding="utf-8")
                )

            expected_status = "done" if scenario == "success" else "error"
            self.assertEqual(result["status"], expected_status)
            self.assertEqual(metadata["status"], expected_status)
            if scenario == "oracle_failure":
                self.assertEqual(metadata["oracle_status"], "missing")
                self.assertFalse(
                    (
                        output_root / "generic" / "crun-13" / "oracle.json"
                    ).exists()
                )
            self.assertEqual(
                metadata["elapsed_seconds"],
                metadata["metrics"]["pipeline_elapsed_seconds"],
            )
            self.assertIsNotNone(metadata["metrics"]["agent_elapsed_seconds"])


if __name__ == "__main__":
    unittest.main()
