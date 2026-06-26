from __future__ import annotations

import argparse
import json
import os
import shutil
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
        return str(path) if path.exists() else None
    found = shutil.which(value)
    return found


def fingerprint(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "returncode": result["returncode"],
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
    if result.get("returncode") in (126, 127):
        return "environment"
    return None


def bash_env_path(value: str | Path) -> str:
    text = str(value)
    if os.name == "nt":
        return text.replace("\\", "/")
    return text


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
    with tempfile.TemporaryDirectory(prefix=f"oci-{case_id}-{runtime_label}-{config_name}-") as tmp:
        env = os.environ.copy()
        env.update(
            {
                "RUNTIME": bash_env_path(runtime),
                "CONFIG": config_name,
                "ROOTFS_TAR": bash_env_path(rootfs_tar),
                "BUNDLE": bash_env_path(Path(tmp) / "bundle"),
                "CONTAINER_ID": f"{case_id}-{runtime_label}-{config_name}-{uuid.uuid4().hex[:8]}",
            }
        )
        try:
            import subprocess

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
            return {
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
            return {
                "runtime_label": runtime_label,
                "config": config_name,
                "returncode": 124,
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "elapsed_seconds": round(time.monotonic() - start, 3),
                "timed_out": True,
                "error": f"timeout after {timeout}s",
            }
        except OSError as exc:
            return {
                "runtime_label": runtime_label,
                "config": config_name,
                "returncode": 127,
                "stdout": "",
                "stderr": str(exc),
                "elapsed_seconds": round(time.monotonic() - start, 3),
                "timed_out": False,
                "error": str(exc),
            }


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
