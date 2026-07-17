from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from oci_common import build_task_text


class OciTaskPromptTests(unittest.TestCase):
    def test_includes_absolute_reproduction_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dataset_dir = Path(tmp) / "dataset"
            case_dir = dataset_dir / "cases" / "crun-13"
            case_dir.mkdir(parents=True)
            (case_dir / "README.md").write_text("case readme", encoding="utf-8")
            (case_dir / "expected_diff.txt").write_text(
                "expected behavior", encoding="utf-8"
            )

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
            )

        self.assertIn(str(case_dir.resolve()), text)
        self.assertIn(str((dataset_dir / "alpine-base.tar.gz").resolve()), text)
        self.assertIn("Reproduction bundle absolute path (read-only):", text)


if __name__ == "__main__":
    unittest.main()
