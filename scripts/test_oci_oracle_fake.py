from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ORACLE = REPO_ROOT / "oracles" / "run_oci_oracle.py"


def bash_is_usable() -> bool:
    if shutil.which("bash") is None:
        return False
    result = subprocess.run(
        ["bash", "-lc", "true"],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    return result.returncode == 0


@unittest.skipIf(not bash_is_usable(), "usable bash is required for OCI oracle tests")
class FakeOciOracleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.case_dir = self.root / "case"
        self.case_dir.mkdir()
        (self.case_dir / "expected_diff.txt").write_text("fake expected diff\n", encoding="utf-8")
        (self.case_dir / "base_config.json").write_text("{}\n", encoding="utf-8")
        (self.case_dir / "buggy_config.json").write_text("{}\n", encoding="utf-8")
        (self.case_dir / "repro.sh").write_text('bash "$RUNTIME" "$CONFIG"\n', encoding="utf-8")
        self.rootfs = self.root / "alpine-base.tar.gz"
        self.rootfs.write_text("fake-rootfs\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_runtime(self, name: str, body: str) -> Path:
        path = self.root / name
        path.write_text(body, encoding="utf-8")
        return path

    def run_oracle(self, candidate: Path, reference: Path, timeout: int = 3) -> dict:
        output = self.root / "oracle.json"
        subprocess.run(
            [
                sys.executable,
                str(ORACLE),
                "--case",
                "fake-1",
                "--case-dir",
                str(self.case_dir),
                "--candidate",
                str(candidate),
                "--reference",
                str(reference),
                "--rootfs-tar",
                str(self.rootfs),
                "--output",
                str(output),
                "--timeout",
                str(timeout),
            ],
            text=True,
            capture_output=True,
        )
        return json.loads(output.read_text(encoding="utf-8"))

    def test_pass_when_candidate_matches_reference(self) -> None:
        runtime = self.write_runtime("same.sh", 'echo "$1"\n')
        payload = self.run_oracle(runtime, runtime)
        self.assertEqual(payload["status"], "pass")

    def test_fail_when_candidate_differs(self) -> None:
        reference = self.write_runtime("reference.sh", 'echo "$1"\n')
        candidate = self.write_runtime(
            "candidate.sh",
            'if [ "$1" = "buggy_config.json" ]; then echo changed; else echo "$1"; fi\n',
        )
        payload = self.run_oracle(candidate, reference)
        self.assertEqual(payload["status"], "fail")

    def test_error_when_reference_missing(self) -> None:
        candidate = self.write_runtime("candidate.sh", 'echo "$1"\n')
        payload = self.run_oracle(candidate, self.root / "missing.sh")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error_type"], "environment")

    def test_error_when_candidate_times_out(self) -> None:
        reference = self.write_runtime("reference.sh", 'echo "$1"\n')
        candidate = self.write_runtime("candidate.sh", "sleep 5\n")
        payload = self.run_oracle(candidate, reference, timeout=1)
        self.assertEqual(payload["status"], "error")
        self.assertIn("timeout", payload["message"])


if __name__ == "__main__":
    unittest.main()
