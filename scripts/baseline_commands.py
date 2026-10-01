"""Construct supported commands; experiment YAML cannot inject model overrides."""
from __future__ import annotations

import sys
from typing import Any

from model_profiles import ROOT


def baseline_command(baseline: dict[str, Any], values: dict[str, Any]) -> list[str]:
    kind = baseline["kind"]
    common = ["--baseline-repo", values["baseline_repo_dir"], "--model-config", values["model_config"], "--task-file", values["task_file"]]
    if kind in {"mini_swe_agent", "agentless_oci"}:
        command = [sys.executable, ROOT / "scripts" / "launch_profiled_baseline.py", "--kind", kind, *common]
        if baseline.get("conda_env"):
            command = ["conda", "run", "--no-capture-output", "-n", baseline["conda_env"], "python", *command[1:]]
        if kind == "mini_swe_agent":
            command += ["--output", values["trajectory_file"]]
        else:
            command += ["--output", values["agentless_output_dir"], "--task-jsonl", values["task_jsonl"], "--loc-jsonl", values["loc_jsonl"], "--case-id", values["case_id"], "--top-n", values["top_n_files"], "--max-samples", values["max_samples"]]
    else:
        command = ["bash", ROOT / "baselines" / kind / "run_oci_repair.sh", *common, "--repo", values["worktree_dir"], "--output-dir", values["baseline_output_dir"], "--timeout-seconds", values["task_timeout_seconds"]]
        options = {
            "metagpt": {"n-round": "n_round", "investment": "investment", "max-auto-summarize-code": "max_auto_summarize_code"},
            "repairagent": {"test-command": "build_command", "source-extensions": "source_extensions", "max-cycles": "max_cycles", "test-timeout-seconds": "test_timeout_seconds"},
            "patchagent": {"build-command": "build_command", "source-extensions": "source_extensions", "build-timeout-seconds": "test_timeout_seconds"},
            "autocoderover": {"conv-round-limit": "conv_round_limit", "source-extensions": "source_extensions"},
        }[kind]
        for argument, field in options.items():
            command += ["--" + argument, values[field]]
    return [str(part) for part in command]


def configure_baseline_environment(baseline: dict[str, Any], env: dict[str, str]) -> dict[str, str]:
    prefixes = {"metagpt": "METAGPT", "repairagent": "REPAIRAGENT", "patchagent": "PATCHAGENT", "autocoderover": "ACR"}
    prefix = prefixes.get(baseline["kind"])
    if prefix and baseline.get("conda_env"):
        env[prefix + "_CONDA_ENV"] = baseline["conda_env"]
    return env
