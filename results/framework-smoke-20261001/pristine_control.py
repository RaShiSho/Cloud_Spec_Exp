"""Build the configured, unmodified buggy revision as an oracle negative control."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from oci_common import load_config, run_command, write_json, write_text
from run_oci_experiment import create_worktree
from experiment_trace import trace_event
from process_control import ORACLE_CLEANUP_ALLOWANCE

if __name__ == "__main__":
    dest = Path(__file__).resolve().parent / "diagnostics" / "pristine-control"
    dest.mkdir(parents=True, exist_ok=True)
    cfg = load_config(Path(__file__).with_name("experiment.yaml"))
    runtime = cfg["runtimes"]["crun"]
    repo = ROOT / runtime["source_dir"]
    worktree = ROOT / "external/worktrees/framework-smoke-20261001/pristine-control/crun-13"
    ref = runtime["buggy_ref_by_case"]["crun-13"]
    trace_event(dest / "events.jsonl", "worktree_started", worktree=str(worktree), ref=ref)
    create_worktree(repo, worktree, ref)
    report = {"purpose": "Unmodified configured buggy revision: verifies whether this case distinguishes a repair.", "source_ref": ref, "worktree": str(worktree)}
    report["source_commit"] = run_command(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    report["initial_diff"] = run_command(["git", "diff", "HEAD"], cwd=worktree).stdout
    trace_event(dest / "events.jsonl", "build_started", command=runtime["build_command"])
    build = run_command(runtime["build_command"], cwd=worktree, timeout=600)
    write_text(dest / "build.stdout.log", build.stdout)
    write_text(dest / "build.stderr.log", build.stderr)
    report["build"] = build.to_dict()
    trace_event(dest / "events.jsonl", "build_finished", returncode=build.returncode)
    if build.ok:
        command = [sys.executable, str(ROOT / "oracles/run_oci_oracle.py"), "--case", "crun-13", "--case-dir", str(ROOT / cfg["benchmark"]["cases_dir"] / "crun-13"), "--candidate", str(worktree / "crun"), "--reference", runtime["reference_runtime"], "--rootfs-tar", str(ROOT / cfg["benchmark"]["rootfs_tar"]), "--output", str(dest / "oracle.json"), "--timeout", "15"]
        result = run_command(command, timeout=60 + ORACLE_CLEANUP_ALLOWANCE, shell=False)
        write_text(dest / "oracle.stdout.log", result.stdout)
        write_text(dest / "oracle.stderr.log", result.stderr)
        report["oracle_process"] = result.to_dict()
    report["final_diff"] = run_command(["git", "diff", "HEAD"], cwd=worktree).stdout
    write_json(dest / "control.json", report)
    trace_event(dest / "events.jsonl", "control_finished")
    print(json.dumps({key: value for key, value in report.items() if key not in {"build", "oracle_process", "final_diff"}}, indent=2))
