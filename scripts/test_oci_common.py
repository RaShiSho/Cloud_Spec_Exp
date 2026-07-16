from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from oci_common import configured_buggy_ref_case_ids, load_oci_cases  # noqa: E402


class BuggyRefSelectionTests(unittest.TestCase):
    def test_collects_non_empty_dict_and_list_entries(self) -> None:
        config = {
            "runtimes": {
                "runc": {"buggy_ref_by_case": {"runc-1": "abc", "runc-2": None}},
                "crun": {"buggy_refs": ["crun-3"]},
            }
        }

        self.assertEqual(configured_buggy_ref_case_ids(config), {"runc-1", "crun-3"})

    def test_load_oci_cases_filters_metadata_by_configured_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_file = root / "metadata.json"
            cases_dir = root / "cases"
            metadata_file.write_text(
                json.dumps(
                    [
                        {"number": "youki-1", "title": "selected"},
                        {"number": "youki-2", "title": "not selected"},
                    ]
                ),
                encoding="utf-8",
            )
            case_dir = cases_dir / "youki-1"
            case_dir.mkdir(parents=True)
            for name in (
                "base_config.json",
                "buggy_config.json",
                "repro.sh",
                "expected_diff.txt",
                "README.md",
            ):
                (case_dir / name).write_text("", encoding="utf-8")

            config = {
                "benchmark": {
                    "metadata_file": str(metadata_file),
                    "cases_dir": str(cases_dir),
                    "selection": {"mode": "buggy_refs"},
                },
                "runtimes": {
                    "youki": {"buggy_ref_by_case": {"youki-1": "deadbeef^"}},
                },
            }

            cases, problems = load_oci_cases(config)

        self.assertEqual([case["case_id"] for case in cases], ["youki-1"])
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
