"""Bound subprocess lifetimes, including shell children and nested supervisors."""
from __future__ import annotations

from contextlib import contextmanager
import os
import signal
import subprocess
import threading
from typing import Callable

TERMINATION_GRACE_SECONDS = 1.0
CONTAINER_CLEANUP_TIMEOUT = 5
# Include TERM/KILL, privileged signal helpers, pipe draining and process reap.
PROCESS_CLEANUP_ALLOWANCE = 6 * TERMINATION_GRACE_SECONDS
ORACLE_TERMINATION_GRACE = CONTAINER_CLEANUP_TIMEOUT + 2 * PROCESS_CLEANUP_ALLOWANCE + 1
ORACLE_CLEANUP_ALLOWANCE = 4 * ORACLE_TERMINATION_GRACE + 5


@contextmanager
def handle_termination():
    """Let a terminating parent run finally blocks which clean up child sessions."""
    installed = threading.current_thread() is threading.main_thread() and signal.getsignal(signal.SIGTERM) == signal.SIG_DFL
    if installed:
        def terminate(signum, _frame):
            raise SystemExit(128 + signum)
        signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        if installed:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)


def _signal_group(process: subprocess.Popen, sig: int, privileged: Callable[[], bool] | None) -> str | None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, sig)
        elif process.poll() is None:
            process.terminate() if sig == signal.SIGTERM else process.kill()
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        # sudo-launched runtime children may have changed UID. Only allow this
        # fallback when the oracle observed a root-owned runtime invocation.
        if privileged is None or not privileged():
            return str(exc)
        try:
            result = subprocess.run(
                ["sudo", "-n", "kill", f"-{sig}", "--", f"-{process.pid}"],
                capture_output=True, timeout=TERMINATION_GRACE_SECONDS,
            )
            if result.returncode:
                return "could not signal privileged process group"
        except (OSError, subprocess.TimeoutExpired) as error:
            return f"could not signal privileged process group: {error}"
    return None


def _stop(process: subprocess.Popen, privileged: Callable[[], bool] | None, grace: float):
    errors = []
    error = _signal_group(process, signal.SIGTERM, privileged)
    if error:
        errors.append(error)
    try:
        process.communicate(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    # A descendant may close its output pipes and ignore TERM. Kill the group
    # even when communicate() has already reaped its leader.
    error = _signal_group(process, getattr(signal, "SIGKILL", 9), privileged)
    if error:
        errors.append(error)
    try:
        stdout, stderr = process.communicate(timeout=TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.stdout, exc.stderr
        errors.append("output pipes remained open after process group termination")
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()
        try:
            process.wait(timeout=TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            errors.append("process did not exit after termination")
    return stdout, stderr, errors


def run_process(command, *, cwd=None, env=None, timeout=None, shell=False,
                termination_grace: float = TERMINATION_GRACE_SECONDS,
                privileged_cleanup: Callable[[], bool] | None = None) -> subprocess.CompletedProcess:
    with handle_termination():
        process = subprocess.Popen(
            command, cwd=cwd, env=env, shell=shell,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            start_new_session=os.name == "posix",
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            stdout, stderr, errors = _stop(process, privileged_cleanup, termination_grace)
            error = subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
            error.cleanup_errors = errors
            raise error from None
        except BaseException as error:
            _stdout, _stderr, errors = _stop(process, privileged_cleanup, termination_grace)
            error.cleanup_errors = errors
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
