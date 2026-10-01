from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare OCI runtime behavior against a reference runtime.")
    parser.add_argument("--case", required=True, help="Case id, for example crun-13.")
    parser.add_argument("--case-dir", required=True, help="Path to the OCI dataset case directory.")
    parser.add_argument("--candidate", required=True, help="Candidate runtime executable path.")
    parser.add_argument("--reference", required=True, help="Reference runtime executable path or command.")
    parser.add_argument("--rootfs-tar", required=True, help="Path to alpine-base.tar.gz from the dataset.")
    parser.add_argument("--output", required=True, help="Path to oracle JSON output.")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout per runtime/config execution.")
    return parser.parse_args()


def resolve_executable(value: str) -> str | None:
    path = Path(value)
    if path.is_absolute() or any(sep in value for sep in ("/", "\\")):
        return str(path.resolve()) if path.is_file() and os.access(path, os.X_OK) else None
    found = shutil.which(value)
    return found


def fingerprint(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "returncode": result["returncode"],
        "runtime_returncodes": result.get("runtime_returncodes", []),
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


def classify_execution_issue(result: dict[str, Any]) -> str | None:
    combined_output = f"{result.get('stdout') or ''}\n{result.get('stderr') or ''}".lower()
    if "windows subsystem for linux" in combined_output or "wslstore" in combined_output:
        return "environment"
    if result.get("timed_out"):
        return "timeout"
    if result.get("error"):
        return "execution"
    # A failing tar/cp/sudo (or an empty reproduction script) is not evidence
    # about the runtime. Cleanup-only `delete` calls do not count as execution.
    if result.get("runtime_invoked") is False:
        return "environment"
    if result.get("returncode") in (126, 127):
        return "environment"
    if (
        "rootless container requires user namespaces" in combined_output
        or re.search(r"(?m)^sudo:.*(?:password|not allowed|not permitted|no new privileges)", combined_output)
        or re.search(r"(?:cgroup|seccomp|user namespaces?).*(?:not supported|not available|not enabled|not mounted)", combined_output)
    ):
        return "environment"
    # The clean reference is the positive control. Its failure makes both
    # comparisons inconclusive, even when the candidate fails identically.
    if result.get("runtime_label") == "reference" and result.get("config") == "base_config.json" and (
        result.get("returncode") != 0
        or any(call["returncode"] != 0 for call in result.get("runtime_returncodes", []))
    ):
        return "environment"
    return None


def bash_env_path(value: str | Path) -> str:
    text = str(value)
    if os.name == "nt":
        return text.replace("\\", "/")
    return text


def ensure_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def cleanup_temp_dir(path: Path) -> str | None:
    try:
        shutil.rmtree(path)
    except OSError as exc:
        return f"failed to remove temporary directory {path}: {exc}"
    return None


def run_repro(
    *,
    case_id: str,
    case_dir: Path,
    rootfs_tar: Path,
    runtime: str,
    runtime_label: str,
    config_name: str,
    timeout: int,
) -> dict[str, Any]:
    start = time.monotonic()
    tmp = Path(tempfile.mkdtemp(prefix=f"oci-{case_id}-{runtime_label}-{config_name}-"))
    result: dict[str, Any]
    try:
        invocations = tmp / "runtime-invocations"
        exit_statuses = tmp / "runtime-exit-statuses"
        exit_statuses.touch(mode=0o600)
        launcher = tmp / "runtime"
        # A shell wrapper also works for repro scripts which use sudo. Record
        # calls in a file rather than stdout, where they would affect verdicts.
        launcher.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"${{1-}}\" >> {shlex.quote(str(invocations))}\n"
            "set +e\n"
            f"{shlex.quote(runtime)} \"$@\"\n"
            "status=$?\n"
            f"printf '%s\\t%s\\n' \"${{1-}}\" \"$status\" >> {shlex.quote(str(exit_statuses))}\n"
            "exit \"$status\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o700)
        env = os.environ.copy()
        env.update(
            {
                "RUNTIME": bash_env_path(launcher),
                "CONFIG": config_name,
                "ROOTFS_TAR": bash_env_path(rootfs_tar),
                "BUNDLE": bash_env_path(Path(tmp) / "bundle"),
                "CONTAINER_ID": f"{case_id}-{runtime_label}-{config_name}-{uuid.uuid4().hex[:8]}",
            }
        )
        try:
            completed = subprocess.run(
                ["bash", "repro.sh"],
                cwd=str(case_dir),
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
            )
            result = {
                "runtime_label": runtime_label,
                "config": config_name,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "elapsed_seconds": round(time.monotonic() - start, 3),
                "timed_out": False,
                "error": None,
            }
        except subprocess.TimeoutExpired as exc:
            result = {
                "runtime_label": runtime_label,
                "config": config_name,
                "returncode": 124,
                "stdout": ensure_text(exc.stdout),
                "stderr": ensure_text(exc.stderr),
                "elapsed_seconds": round(time.monotonic() - start, 3),
                "timed_out": True,
                "error": f"timeout after {timeout}s",
            }
        except OSError as exc:
            result = {
                "runtime_label": runtime_label,
                "config": config_name,
                "returncode": 127,
                "stdout": "",
                "stderr": str(exc),
                "elapsed_seconds": round(time.monotonic() - start, 3),
                "timed_out": False,
                "error": str(exc),
            }
        result["runtime_invoked"] = invocations.exists() and any(
            command != "delete" for command in invocations.read_text().splitlines()
        )
        result["runtime_returncodes"] = [
            {"command": command, "returncode": int(code)}
            for line in exit_statuses.read_text().splitlines()
            for command, code in [line.rsplit("\t", 1)] if command != "delete"
        ]
    finally:
        cleanup_warning = cleanup_temp_dir(tmp)

    result["cleanup_warning"] = cleanup_warning
    return result


def write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    case_dir = Path(args.case_dir)
    rootfs_tar = Path(args.rootfs_tar)
    output = Path(args.output)
    expected_diff = case_dir / "expected_diff.txt"

    setup_errors: list[str] = []
    if shutil.which("bash") is None:
        setup_errors.append("missing bash")
    if not case_dir.exists():
        setup_errors.append(f"missing case_dir: {case_dir}")
    if not (case_dir / "repro.sh").exists():
        setup_errors.append(f"missing repro.sh in case_dir: {case_dir}")
    for config_name in ("base_config.json", "buggy_config.json"):
        if not (case_dir / config_name).is_file():
            setup_errors.append(f"missing {config_name} in case_dir: {case_dir}")
    if not rootfs_tar.exists():
        setup_errors.append(f"missing rootfs_tar: {rootfs_tar}")

    candidate = resolve_executable(args.candidate)
    reference = resolve_executable(args.reference)
    if candidate is None:
        setup_errors.append(f"missing candidate runtime: {args.candidate}")
    if reference is None:
        setup_errors.append(f"missing reference runtime: {args.reference}")

    if setup_errors:
        payload = {
            "case_id": args.case,
            "status": "error",
            "error_type": "environment",
            "message": "; ".join(setup_errors),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "comparisons": {},
            "expected_diff": expected_diff.read_text(encoding="utf-8", errors="replace") if expected_diff.exists() else "",
        }
        write_output(output, payload)
        return 2

    assert candidate is not None
    assert reference is not None

    comparisons: dict[str, Any] = {}
    execution_errors: list[str] = []
    for config_name in ("base_config.json", "buggy_config.json"):
        reference_result = run_repro(
            case_id=args.case,
            case_dir=case_dir,
            rootfs_tar=rootfs_tar,
            runtime=reference,
            runtime_label="reference",
            config_name=config_name,
            timeout=args.timeout,
        )
        candidate_result = run_repro(
            case_id=args.case,
            case_dir=case_dir,
            rootfs_tar=rootfs_tar,
            runtime=candidate,
            runtime_label="candidate",
            config_name=config_name,
            timeout=args.timeout,
        )
        comparisons[config_name] = {
            "reference": reference_result,
            "candidate": candidate_result,
            "matches": fingerprint(reference_result) == fingerprint(candidate_result),
        }
        for label, result in (("reference", reference_result), ("candidate", candidate_result)):
            issue = classify_execution_issue(result)
            if issue is not None:
                execution_errors.append(f"{config_name}:{label}:{issue}")

    if execution_errors:
        status = "error"
        error_type = "environment" if any(item.endswith(":environment") for item in execution_errors) else "execution"
        message = "; ".join(execution_errors)
    elif all(value["matches"] for value in comparisons.values()):
        status = "pass"
        error_type = None
        message = "candidate behavior matches reference for base_config.json and buggy_config.json"
    else:
        status = "fail"
        error_type = None
        message = "candidate behavior differs from reference"

    payload = {
        "case_id": args.case,
        "status": status,
        "error_type": error_type,
        "message": message,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "comparisons": comparisons,
        "expected_diff": expected_diff.read_text(encoding="utf-8", errors="replace") if expected_diff.exists() else "",
    }
    write_output(output, payload)
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
