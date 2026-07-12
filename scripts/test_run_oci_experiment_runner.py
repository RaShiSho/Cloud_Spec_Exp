from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
import run_oci_experiment as runner  # noqa: E402


class RunOciExperimentResumeTests(unittest.TestCase):
    def test_loads_only_terminal_results_with_oracle(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
