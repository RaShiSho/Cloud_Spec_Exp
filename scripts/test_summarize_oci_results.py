from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oci_common import CommandResult
from run_oci_experiment import update_metadata_from_oracle
from summarize_oci_results import build_summary, collect, render_markdown


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / "baseline" / "case-1"
        self.output.mkdir(parents=True)

    def write(self, filename, data):
        (self.output / filename).write_text(json.dumps(data))

    def test_legacy_error_without_oracle_is_counted(self):
        self.write("metadata.json", {"case_id": "case-1", "status": "error", "oracle_status": "missing", "error": "oracle timed out: timeout after 1200s", "elapsed_seconds": 1234})
        rows = collect(self.root)
        summary = build_summary(rows)
        self.assertEqual(summary["total_results"], 1)
        self.assertEqual(summary["by_baseline"], {"baseline": {"error": 1}})
        self.assertIn("1200s", rows[0]["message"])
        self.assertEqual(rows[0]["elapsed_seconds"], 1234)
        self.assertEqual(rows[0]["result_source"], "metadata")
        self.assertIsNone(rows[0]["oracle_path"])
        self.assertFalse((self.output / "oracle.json").exists())

    def test_runner_timeout_writes_a_summarizable_error(self):
        metadata = {"case_id": "case-1"}
        update_metadata_from_oracle(metadata=metadata, output_dir=self.output,
            oracle_result=CommandResult(command=["oracle"], cwd=None, returncode=124,
                stdout="", stderr="", timed_out=True, error="timeout after 4s"))
        self.write("metadata.json", metadata)
        rows = collect(self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "error")
        self.assertEqual(rows[0]["result_source"], "oracle")
        self.assertIn("timed out", rows[0]["message"])

    def test_existing_oracle_and_metadata_are_not_counted_twice(self):
        self.write("oracle.json", {"case_id": "case-1", "status": "pass"})
        self.write("metadata.json", {"case_id": "case-1", "status": "done"})
        rows = collect(self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "pass")

    def test_in_progress_metadata_is_incomplete_not_a_failed_verdict(self):
        self.write("metadata.json", {"case_id": "case-1", "status": "starting"})
        summary = build_summary(collect(self.root))
        self.assertEqual(summary["by_baseline"], {"baseline": {"incomplete": 1}})
        self.assertIn("| incomplete |", render_markdown(summary))

    def test_done_without_verdict_is_an_error(self):
        self.write("metadata.json", {"case_id": "case-1", "status": "done"})
        self.assertEqual(collect(self.root)[0]["status"], "error")

    def test_malformed_result_shapes_are_counted_as_errors(self):
        for value in ([], None, {"status": "unknown"}):
            with self.subTest(value=value):
                self.write("oracle.json", value)
                rows = collect(self.root)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["status"], "error")
                self.assertEqual(rows[0]["error_type"], "summary")

    def test_malformed_metadata_is_not_omitted(self):
        (self.output / "metadata.json").write_text("{broken")
        rows = collect(self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "error")


if __name__ == "__main__":
    unittest.main()
