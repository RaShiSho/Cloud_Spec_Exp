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
    def test_loads_only_completed_results_with_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            config = {"experiment": {"output_dir": str(output_root)}}
            baseline = {"name": "autocoderover"}
            case = {"case_id": "crun-13"}
            output_dir = output_root / "autocoderover" / "crun-13"
            output_dir.mkdir(parents=True)
            metadata_path = output_dir / "metadata.json"
            oracle_path = output_dir / "oracle.json"

            metadata_path.write_text(json.dumps({"status": "done"}), encoding="utf-8")
            self.assertIsNone(runner.load_terminal_result(config, baseline, case))

            oracle_path.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
            result = runner.load_terminal_result(config, baseline, case)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["resumed_skip"])

    def test_does_not_skip_failed_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            config = {"experiment": {"output_dir": str(output_root)}}
            baseline = {"name": "autocoderover"}
            case = {"case_id": "crun-13"}
            output_dir = output_root / "autocoderover" / "crun-13"
            output_dir.mkdir(parents=True)
            (output_dir / "metadata.json").write_text(
                json.dumps({"status": "error"}), encoding="utf-8"
            )
            (output_dir / "oracle.json").write_text(
                json.dumps({"status": "error"}), encoding="utf-8"
            )

            result = runner.load_terminal_result(config, baseline, case)

        self.assertIsNone(result)

    def test_does_not_skip_incomplete_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            config = {"experiment": {"output_dir": str(output_root)}}
            baseline = {"name": "autocoderover"}
            case = {"case_id": "runc-2430"}
            output_dir = output_root / "autocoderover" / "runc-2430"
            output_dir.mkdir(parents=True)
            (output_dir / "metadata.json").write_text(
                json.dumps({"status": "running"}), encoding="utf-8"
            )
            (output_dir / "oracle.json").write_text("{}", encoding="utf-8")

            result = runner.load_terminal_result(config, baseline, case)

        self.assertIsNone(result)


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
        self.assertEqual(candidate_patch, "partial diff\n")
        self.assertEqual(oracle["error_type"], "baseline")
        self.assertEqual(oracle["message"], result["error"])


if __name__ == "__main__":
    unittest.main()
