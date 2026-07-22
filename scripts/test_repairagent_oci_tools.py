from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ADAPTER_DIR = Path(__file__).resolve().parents[1] / "baselines" / "repairagent"
sys.path.insert(0, str(ADAPTER_DIR))
import oci_tools  # noqa: E402


class RepairAgentOciToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._environment = os.environ.copy()
        self._temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self._temporary.name).resolve()
        os.environ["REPAIRAGENT_OCI_REPO"] = str(self.repo)
        os.environ["REPAIRAGENT_OCI_SOURCE_EXTENSIONS"] = ".c,.h"
        os.environ["REPAIRAGENT_OCI_TEST_TIMEOUT"] = "10"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._environment)
        self._temporary.cleanup()

    def validation_command(self, expected: str) -> str:
        script = (
            "import pathlib,sys;"
            f"sys.exit(0 if pathlib.Path('runtime.c').read_text(encoding='utf-8') == {expected!r} else 3)"
        )
        return subprocess.list2cmdline([sys.executable, "-c", script])

    def test_applies_line_edits_and_retains_passing_candidate(self) -> None:
        source = self.repo / "runtime.c"
        source.write_text("one\ntwo\nthree\n", encoding="utf-8")
        expected = "zero\nTWO\nthree\n"
        os.environ["REPAIRAGENT_OCI_TEST_COMMAND"] = self.validation_command(expected)

        result = oci_tools.apply_and_validate(
            [
                {
                    "file_name": "runtime.c",
                    "insertions": [{"line_number": 1, "new_lines": ["zero"]}],
                    "deletions": [1],
                    "modifications": [{"line_number": 2, "modified_line": "TWO"}],
                }
            ]
        )

        self.assertIn("0 failing tests", result)
        self.assertEqual(source.read_text(encoding="utf-8"), expected)

    def test_reverts_candidate_when_validation_fails(self) -> None:
        source = self.repo / "runtime.c"
        original = "one\ntwo\n"
        source.write_text(original, encoding="utf-8")
        os.environ["REPAIRAGENT_OCI_TEST_COMMAND"] = self.validation_command(original)

        result = oci_tools.apply_and_validate(
            [
                {
                    "file_name": "runtime.c",
                    "insertions": [],
                    "deletions": [],
                    "modifications": [{"line_number": 2, "modified_line": "broken"}],
                }
            ]
        )

        self.assertIn("reverted", result)
        self.assertEqual(source.read_text(encoding="utf-8"), original)

    def test_restores_tracked_build_side_effects_but_keeps_candidate(self) -> None:
        source = self.repo / "runtime.c"
        generated = self.repo / "generated.c"
        source.write_text("old\n", encoding="utf-8")
        generated.write_text("canonical\n", encoding="utf-8")
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "runtime.c", "generated.c"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "-c",
                "user.name=RepairAgent Test",
                "-c",
                "user.email=repairagent@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "test(repairagent): initialize fixture",
            ],
            check=True,
        )
        script = "import pathlib;pathlib.Path('generated.c').write_text('regenerated\\n', encoding='utf-8')"
        os.environ["REPAIRAGENT_OCI_TEST_COMMAND"] = subprocess.list2cmdline(
            [sys.executable, "-c", script]
        )

        result = oci_tools.apply_and_validate(
            [
                {
                    "file_name": "runtime.c",
                    "insertions": [],
                    "deletions": [],
                    "modifications": [{"line_number": 1, "modified_line": "candidate"}],
                }
            ]
        )

        self.assertIn("0 failing tests", result)
        self.assertEqual(source.read_text(encoding="utf-8"), "candidate\n")
        self.assertEqual(generated.read_text(encoding="utf-8"), "canonical\n")

    def test_reverts_earlier_file_when_later_change_is_invalid(self) -> None:
        first = self.repo / "first.c"
        second = self.repo / "second.c"
        first.write_text("first\n", encoding="utf-8")
        second.write_text("second\n", encoding="utf-8")

        with self.assertRaises(ValueError):
            oci_tools.apply_change_set(
                [
                    {
                        "file_name": "first.c",
                        "insertions": [],
                        "deletions": [],
                        "modifications": [{"line_number": 1, "modified_line": "changed"}],
                    },
                    {
                        "file_name": "second.c",
                        "insertions": [],
                        "deletions": [99],
                        "modifications": [],
                    },
                ]
            )

        self.assertEqual(first.read_text(encoding="utf-8"), "first\n")
        self.assertEqual(second.read_text(encoding="utf-8"), "second\n")

    def test_rejects_path_outside_repository(self) -> None:
        outside = self.repo.parent / "outside.c"
        outside.write_text("outside\n", encoding="utf-8")
        try:
            with self.assertRaises(ValueError):
                oci_tools.resolve_repo_path(outside)
        finally:
            outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
