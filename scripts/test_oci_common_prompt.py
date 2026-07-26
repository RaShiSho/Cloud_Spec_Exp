from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from oci_common import build_task_text


class OciTaskPromptTests(unittest.TestCase):
    def make_task_text(self, *, baseline_kind: str | None = None) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            dataset_dir = Path(tmp) / "dataset"
            case_dir = dataset_dir / "cases" / "crun-13"
            case_dir.mkdir(parents=True)
            (case_dir / "README.md").write_text("case readme", encoding="utf-8")
            (case_dir / "expected_diff.txt").write_text(
                "expected behavior", encoding="utf-8"
            )
            worktree_dir = Path(tmp) / "worktrees" / "crun-13"

            text = build_task_text(
                {
                    "case_id": "crun-13",
                    "runtime": "crun",
                    "case_dir": str(case_dir),
                    "title": "PATH lookup",
                    "url": "https://example.invalid/crun-13",
                    "category": "Process & Execution",
                },
                {
                    "build_command": "make",
                    "runtime_path": "crun",
                },
                worktree_dir,
                baseline_kind=baseline_kind,
            )

        return text

    def test_includes_absolute_reproduction_paths(self) -> None:
        text = self.make_task_text()

        self.assertIn("Reproduction bundle absolute path (read-only):", text)
        self.assertIn("Rootfs tar absolute path:", text)
        self.assertIn("Required first command:", text)
        self.assertIn("external/subjects", text)
        self.assertIn("the only location where source changes are allowed", text)

    def test_generic_baseline_keeps_absolute_editor_path_instruction(self) -> None:
        text = self.make_task_text(baseline_kind="generic_repair_agent")

        self.assertIn("Use absolute paths when calling Editor tools", text)
        self.assertNotIn("Do not use absolute paths in `### <file>` headers.", text)

    def test_agentless_uses_repository_relative_edit_paths(self) -> None:
        text = self.make_task_text(baseline_kind="agentless_oci")

        self.assertIn(
            "use repository-relative file paths exactly as shown in the localized source files",
            text,
        )
        self.assertIn("Do not use absolute paths in `### <file>` headers.", text)
        self.assertNotIn("Use absolute paths when calling Editor tools", text)

    def test_resolves_dataset_and_worktree_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dataset_dir = Path(tmp) / "dataset"
            case_dir = dataset_dir / "cases" / "crun-13"
            case_dir.mkdir(parents=True)
            (case_dir / "README.md").write_text("case readme", encoding="utf-8")
            (case_dir / "expected_diff.txt").write_text(
                "expected behavior", encoding="utf-8"
            )
            worktree_dir = Path(tmp) / "worktrees" / "crun-13"
            text = build_task_text(
                {
                    "case_id": "crun-13",
                    "runtime": "crun",
                    "case_dir": str(case_dir),
                    "title": "PATH lookup",
                    "url": "https://example.invalid/crun-13",
                    "category": "Process & Execution",
                },
                {
                    "build_command": "make",
                    "runtime_path": "crun",
                },
                worktree_dir,
            )

        self.assertIn(str(case_dir.resolve()), text)
        self.assertIn(str((dataset_dir / "alpine-base.tar.gz").resolve()), text)
        self.assertIn(str(worktree_dir.resolve()), text)


if __name__ == "__main__":
    unittest.main()
