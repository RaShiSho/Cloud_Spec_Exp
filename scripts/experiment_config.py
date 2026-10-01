"""Strict experiment schema: no free-form command or per-baseline model overrides."""
from __future__ import annotations

import math
import re
from typing import Any

if __package__:
    from .model_profiles import ConfigError, fields, nonempty
else:
    from model_profiles import ConfigError, fields, nonempty

BASELINE_OPTIONS = {
    "mini_swe_agent": {"trajectory_name"},
    "agentless_oci": {"top_n_files", "max_samples", "seed_files_by_case"},
    "autocoderover": {"task_timeout_seconds", "conv_round_limit"},
    "metagpt": {"task_timeout_seconds", "n_round", "investment", "max_auto_summarize_code"},
    "repairagent": {"task_timeout_seconds", "max_cycles", "test_timeout_seconds"},
    "patchagent": {"task_timeout_seconds", "test_timeout_seconds"},
}
COMMON_BASELINE = {"name", "kind", "enabled", "repo_dir", "output_dir_name", "timeout_seconds", "conda_env"}


def positive_int(value: Any, name: str, minimum: int = 1) -> None:
    if type(value) is not int or value < minimum:
        raise ConfigError(f"{name} must be an integer >= {minimum}")


def path_component(value: Any, name: str) -> None:
    nonempty(value, name)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) or value in {".", ".."}:
        raise ConfigError(f"{name} must be a simple filename/path component")


def validate_experiment(config: dict[str, Any]) -> dict[str, Any]:
    root_fields = {"experiment", "model_profile", "benchmark", "runtimes", "oracle", "baselines"}
    fields(config, root_fields, "experiment config", root_fields)
    nonempty(config["model_profile"], "model_profile")
    experiment = fields(config["experiment"], {"name", "output_dir", "worktree_root", "timeout_seconds"}, "experiment", {"name", "output_dir", "worktree_root"})
    path_component(experiment["name"], "experiment.name")
    for key in {"output_dir", "worktree_root"}:
        nonempty(experiment[key], f"experiment.{key}")
    if "timeout_seconds" in experiment:
        positive_int(experiment["timeout_seconds"], "experiment.timeout_seconds")
    benchmark = fields(config["benchmark"], {"metadata_file", "cases_dir", "rootfs_tar", "selection"}, "benchmark", {"metadata_file", "cases_dir", "rootfs_tar", "selection"})
    for key in ("metadata_file", "cases_dir", "rootfs_tar"):
        nonempty(benchmark[key], f"benchmark.{key}")
    selection = fields(benchmark["selection"], {"mode", "count"}, "benchmark.selection", {"mode"})
    if not isinstance(selection["mode"], str) or selection["mode"] not in {"all", "first_n", "buggy_refs"}:
        raise ConfigError("benchmark.selection.mode must be all, first_n or buggy_refs")
    if selection["mode"] == "first_n":
        positive_int(selection.get("count", 20), "benchmark.selection.count")
    elif "count" in selection:
        raise ConfigError("benchmark.selection.count is unused unless mode is first_n")
    runtimes = config["runtimes"]
    if not isinstance(runtimes, dict) or not runtimes:
        raise ConfigError("runtimes must be a nonempty mapping")
    for name, runtime in runtimes.items():
        location = f"runtimes.{name}"
        required = {"source_dir", "build_command", "runtime_path", "reference_runtime"}
        fields(runtime, required | {"source_extensions", "buggy_ref_by_case", "buggy_ref", "default_ref"}, location, required)
        for key in required | ({"buggy_ref", "default_ref"} & runtime.keys()):
            nonempty(runtime[key], f"{location}.{key}")
        if "buggy_ref" in runtime and "default_ref" in runtime:
            raise ConfigError(f"{location}: buggy_ref conflicts with default_ref")
        if "source_extensions" in runtime:
            extensions = runtime["source_extensions"]
            if not isinstance(extensions, list) or not extensions or any(not isinstance(ext, str) or not ext.startswith(".") for ext in extensions):
                raise ConfigError(f"{location}.source_extensions must be a nonempty list of suffixes")
        refs = runtime.get("buggy_ref_by_case", {})
        if not isinstance(refs, dict):
            raise ConfigError(f"{location}.buggy_ref_by_case must be a mapping")
        for case, ref in refs.items():
            nonempty(ref, f"{location}.buggy_ref_by_case.{case}")
    oracle = fields(config["oracle"], {"timeout_seconds"}, "oracle")
    if "timeout_seconds" in oracle:
        positive_int(oracle["timeout_seconds"], "oracle.timeout_seconds")
    baselines = config["baselines"]
    if not isinstance(baselines, list) or not baselines:
        raise ConfigError("baselines must be a nonempty list")
    names = set()
    for index, baseline in enumerate(baselines):
        location = f"baselines[{index}]"
        if not isinstance(baseline, dict) or not isinstance(baseline.get("kind"), str) or baseline["kind"] not in BASELINE_OPTIONS:
            raise ConfigError(f"{location}.kind must be one of {', '.join(BASELINE_OPTIONS)}")
        fields(baseline, COMMON_BASELINE | BASELINE_OPTIONS[baseline["kind"]], location, {"name", "kind", "repo_dir"})
        if baseline["kind"] == "mini_swe_agent" and "output_dir_name" in baseline:
            raise ConfigError(f"{location}.output_dir_name is unused for mini_swe_agent; use trajectory_name")
        path_component(baseline["name"], f"{location}.name")
        if baseline["name"] in names:
            raise ConfigError(f"Duplicate baseline name: {baseline['name']}")
        names.add(baseline["name"])
        nonempty(baseline["repo_dir"], f"{location}.repo_dir")
        if "enabled" in baseline and type(baseline["enabled"]) is not bool:
            raise ConfigError(f"{location}.enabled must be a boolean")
        for key in {"conda_env", "output_dir_name", "trajectory_name"} & baseline.keys():
            path_component(baseline[key], f"{location}.{key}")
        for key in baseline.keys() & {"timeout_seconds", "task_timeout_seconds", "top_n_files", "max_samples", "conv_round_limit", "n_round", "max_cycles", "test_timeout_seconds", "max_auto_summarize_code"}:
            positive_int(baseline[key], f"{location}.{key}", 0 if key == "max_auto_summarize_code" else 1)
        if "investment" in baseline:
            value = baseline["investment"]
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ConfigError(f"{location}.investment must be a positive number")
        if "seed_files_by_case" in baseline:
            seeds = baseline["seed_files_by_case"]
            if not isinstance(seeds, dict) or any(not isinstance(items, list) or not items or any(not isinstance(item, str) or not item for item in items) for items in seeds.values()):
                raise ConfigError(f"{location}.seed_files_by_case must map cases to nonempty filename lists")
    return config
