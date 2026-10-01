from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from oci_common import run_command
from oracles import run_oci_oracle as oracle
from process_control import ORACLE_TERMINATION_GRACE


def alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, ProcessLookupError):
        return False


def await_stopped(pid: int) -> bool:
    deadline = time.monotonic() + 2
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    return not alive(pid)


@unittest.skipUnless(sys.platform == "linux", "Process-group lifecycle assertions use /proc")
class ProcessControlTests(unittest.TestCase):
    def test_timeout_kills_descendants_even_when_they_close_pipes_and_ignore_term(self):
        for use_shell in (False, True):
            with self.subTest(shell=use_shell), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                child_pid = root / "child.pid"
                child = root / "child.py"
                child.write_text(textwrap.dedent(f"""
                    import os, signal, time
                    from pathlib import Path
                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    Path({str(child_pid)!r}).write_text(str(os.getpid()))
                    time.sleep(30)
                """))
                parent = root / "parent.py"
                parent.write_text(textwrap.dedent(f"""
                    import subprocess, sys, time
                    from pathlib import Path
                    subprocess.Popen([sys.executable, {str(child)!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    while not Path({str(child_pid)!r}).exists(): time.sleep(0.01)
                    print('output before timeout', flush=True)
                    time.sleep(30)
                """))
                command = [sys.executable, str(parent)]
                try:
                    result = run_command(shlex.join(command) if use_shell else command, timeout=1)
                    self.assertTrue(result.timed_out)
                    self.assertEqual(result.returncode, 124)
                    self.assertIn("output before timeout", result.stdout)
                    self.assertTrue(await_stopped(int(child_pid.read_text())))
                finally:
                    if child_pid.exists() and alive(int(child_pid.read_text())):
                        os.kill(int(child_pid.read_text()), signal.SIGKILL)

    def runtime_fixture(self, root: Path, delete_status: int = 0):
        case = root / "case"
        case.mkdir()
        for name in ("base_config.json", "buggy_config.json"):
            (case / name).write_text("{}")
        (case / "repro.sh").write_text('mkdir -p "$BUNDLE"\n"$RUNTIME" run\n')
        archive = root / "rootfs.tar.gz"
        archive.touch()
        record = root / "runtime.json"
        deleted = root / "deleted.json"
        runtime = root / "runtime"
        runtime.write_text("#!" + sys.executable + "\n" + textwrap.dedent(f"""
            import json, os, signal, sys, time
            from pathlib import Path
            record = Path({str(record)!r})
            if sys.argv[1] == 'delete':
                value = json.loads(record.read_text())
                Path({str(deleted)!r}).write_text(json.dumps({{'bundle_present': Path(value['bundle']).exists()}}))
                if {delete_status}: print('cleanup deliberately failed', file=sys.stderr)
                sys.exit({delete_status})
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            record.write_text(json.dumps({{'pid': os.getpid(), 'bundle': os.environ['BUNDLE']}}))
            time.sleep(30)
        """))
        runtime.chmod(0o700)
        return case, archive, runtime, record, deleted

    def assert_runtime_cleaned(self, record, deleted):
        value = json.loads(record.read_text())
        self.assertTrue(await_stopped(value["pid"]))
        self.assertTrue(json.loads(deleted.read_text())["bundle_present"])
        self.assertFalse(Path(value["bundle"]).exists())

    def test_oracle_timeout_cleans_container_before_removing_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            case, archive, runtime, record, deleted = self.runtime_fixture(Path(tmp))
            result = oracle.run_repro(case_id="timeout-test", case_dir=case, rootfs_tar=archive,
                                      runtime=str(runtime), runtime_label="candidate",
                                      config_name="base_config.json", timeout=1)
            self.assertTrue(result["timed_out"])
            self.assertIsNone(result["cleanup_warning"])
            self.assert_runtime_cleaned(record, deleted)

    def test_outer_runner_timeout_allows_nested_oracle_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case, archive, runtime, record, deleted = self.runtime_fixture(root)
            result = run_command([
                sys.executable, str(ROOT / "oracles/run_oci_oracle.py"),
                "--case", "nested-test", "--case-dir", str(case),
                "--rootfs-tar", str(archive), "--candidate", str(runtime),
                "--reference", str(runtime), "--output", str(root / "oracle.json"), "--timeout", "30",
            ], timeout=1, termination_grace=ORACLE_TERMINATION_GRACE)
            self.assertTrue(result.timed_out)
            self.assert_runtime_cleaned(record, deleted)

    def test_failed_container_cleanup_retains_bundle_and_reports_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            case, archive, runtime, record, _deleted = self.runtime_fixture(Path(tmp), delete_status=2)
            result = oracle.run_repro(case_id="cleanup-test", case_dir=case, rootfs_tar=archive,
                                      runtime=str(runtime), runtime_label="candidate",
                                      config_name="base_config.json", timeout=1)
            temporary_dir = Path(result["execution_context"]["temporary_dir"])
            try:
                self.assertIn("container cleanup failed", result["cleanup_warning"])
                self.assertIn("retained temporary directory", result["cleanup_warning"])
                self.assertTrue(Path(json.loads(record.read_text())["bundle"]).exists())
                self.assertTrue(await_stopped(json.loads(record.read_text())["pid"]))
            finally:
                shutil.rmtree(temporary_dir)

    def test_privileged_container_cleanup_uses_noninteractive_sudo(self):
        with mock.patch.object(oracle, "run_process", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            self.assertIsNone(oracle.cleanup_container("/runtime", "owned-container", True))
        self.assertEqual(run.call_args.args[0], ["sudo", "-n", "/runtime", "delete", "-f", "owned-container"])
        self.assertTrue(run.call_args.kwargs["privileged_cleanup"]())


if __name__ == "__main__":
    unittest.main()
