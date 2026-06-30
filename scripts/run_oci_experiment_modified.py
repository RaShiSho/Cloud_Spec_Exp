from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from oci_common import (
    DEFAULT_EXTENSIONS,
    REPO_ROOT,
    append_jsonl,
    build_task_text,
    command_exists,
    executable_exists,
    load_config,
    load_jsonl,
    load_oci_cases,
    resolve_path,
    run_command,
    safe_id,
    scan_candidate_files,
    shell_quote,
    write_json,
    write_text,
)


def progress(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", file=sys.stderr, flush=True)


def run_label(baseline: dict[str, Any], case: dict[str, Any]) -> str:
    return f"[{baseline.get('name')}/{case['case_id']}]"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OCI repair experiments for configured baselines.")
    parser.add_argument("--config", required=True, help="Experiment YAML config.")
    parser.add_argument("--baseline", action="append", help="Baseline name to run. Repeatable.")
    parser.add_argument("--case", action="append", help="Case id to run. Repeatable.")
    parser.add_argument("--limit", type=int, help="Limit selected cases after filtering.")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and print the plan without side effects.")
    parser.add_argument("--clean", action="store_true", help="Remove previous output/worktree for selected runs before execution.")
    return parser.parse_args()


def enabled_baselines(config: dict[str, Any], names: list[str] | None) -> list[dict[str, Any]]:
    requested = set(names or [])
    selected = []
    for baseline in config.get("baselines", []):
        if not baseline.get("enabled", True):
            continue
        if requested and baseline.get("name") not in requested:
            continue
        selected.append(baseline)
    return selected


def benchmark_selection_mode(config: dict[str, Any]) -> str:
    benchmark = config.get("benchmark", {})
    selection = benchmark.get("selection", {})
    selection_mode = selection.get("mode") if isinstance(selection, dict) else None
    direct_mode = benchmark.get("mode")
    if direct_mode is not None and selection_mode in (None, "all"):
        return str(direct_mode)
    return str(selection_mode or direct_mode or "all")


def config_for_case_loading(config: dict[str, Any], selection_mode: str) -> dict[str, Any]:
    if selection_mode != "buggy_refs":
        return config

    # load_oci_cases may only know the original selection modes. Load the full
    # configured benchmark first, then apply buggy-ref filtering in this runner.
    case_loading_config = copy.deepcopy(config)
    benchmark = case_loading_config.setdefault("benchmark", {})
    selection = benchmark.setdefault("selection", {})
    if isinstance(selection, dict):
        selection["mode"] = "all"
    benchmark.pop("mode", None)
    return case_loading_config


def case_has_buggy_ref(config: dict[str, Any], case: dict[str, Any]) -> bool:
    runtime_cfg = config.get("runtimes", {}).get(case.get("runtime"), {})
    case_id = case.get("case_id")
    buggy_ref_by_case = runtime_cfg.get("buggy_ref_by_case") or runtime_cfg.get("buggy_refs") or {}

    if isinstance(buggy_ref_by_case, dict):
        return bool(buggy_ref_by_case.get(case_id))
    if isinstance(buggy_ref_by_case, list):
        return case_id in buggy_ref_by_case
    return False


def selected_cases(config: dict[str, Any], case_ids: list[str] | None, limit: int | None) -> tuple[list[dict[str, Any]], list[str]]:
    selection_mode = benchmark_selection_mode(config)
    cases, problems = load_oci_cases(config_for_case_loading(config, selection_mode))

    if selection_mode == "buggy_refs":
        cases = [case for case in cases if case_has_buggy_ref(config, case)]

    requested = set(case_ids or [])
    if requested:
        cases = [case for case in cases if case["case_id"] in requested]
        missing = sorted(requested - {case["case_id"] for case in cases})
        problems.extend(f"requested case not selected by config: {case_id}" for case_id in missing)
    if limit is not None:
        cases = cases[:limit]
    return cases, problems


def get_runtime_config(config: dict[str, Any], runtime: str) -> dict[str, Any]:
    runtimes = config.get("runtimes", {})
    runtime_cfg = runtimes.get(runtime)
    if not runtime_cfg:
        raise KeyError(f"missing runtime config for {runtime}")
    return runtime_cfg


def preflight(
    config: dict[str, Any],
    cases: list[dict[str, Any]],
    baselines: list[dict[str, Any]],
) -> list[str]:
    problems: list[str] = []
    benchmark = config.get("benchmark", {})
    rootfs_tar = resolve_path(benchmark.get("rootfs_tar"))
    if rootfs_tar is None or not rootfs_tar.exists():
        problems.append(f"missing rootfs_tar: {rootfs_tar}")

    for command in ("git", "bash"):
        if not command_exists(command):
            problems.append(f"missing command on PATH: {command}")
    if command_exists("bash"):
        bash_check = run_command(["bash", "-lc", "true"], timeout=5, shell=False)
        if not bash_check.ok:
            problems.append(f"bash exists but is not usable: returncode={bash_check.returncode}")

    if not cases:
        problems.append("no cases selected")
    if not baselines:
        problems.append("no baselines selected")

    for case in cases:
        for missing in case.get("missing_files", []):
            problems.append(f"{case['case_id']}: missing {missing}")
        try:
            runtime_cfg = get_runtime_config(config, case["runtime"])
        except KeyError as exc:
            problems.append(str(exc))
            continue
        source_dir = resolve_path(runtime_cfg.get("source_dir"))
        if source_dir is None or not source_dir.exists():
            problems.append(f"{case['case_id']}: missing runtime source_dir: {source_dir}")
        elif not (source_dir / ".git").exists():
            problems.append(f"{case['case_id']}: runtime source_dir is not a git repo: {source_dir}")
        if not runtime_cfg.get("build_command"):
            problems.append(f"{case['case_id']}: missing build_command for runtime {case['runtime']}")
        if not runtime_cfg.get("runtime_path"):
            problems.append(f"{case['case_id']}: missing runtime_path for runtime {case['runtime']}")
        if not executable_exists(runtime_cfg.get("reference_runtime")):
            problems.append(f"{case['case_id']}: missing reference_runtime: {runtime_cfg.get('reference_runtime')}")

    for baseline in baselines:
        repo_dir = resolve_path(baseline.get("repo_dir"))
        if repo_dir is None or not repo_dir.exists():
            problems.append(f"{baseline.get('name')}: missing baseline repo_dir: {repo_dir}")
        if baseline.get("adapter_patch"):
            patch_path = resolve_path(baseline.get("adapter_patch"))
            if patch_path is None or not patch_path.exists():
                problems.append(f"{baseline.get('name')}: missing adapter_patch: {patch_path}")
        if not baseline.get("command"):
            problems.append(f"{baseline.get('name')}: missing command template")
    return problems


def print_dry_run(
    config: dict[str, Any],
    cases: list[dict[str, Any]],
    baselines: list[dict[str, Any]],
    problems: list[str],
) -> None:
    payload = {
        "experiment": config.get("experiment", {}).get("name"),
        "cases": [case["case_id"] for case in cases],
        "baselines": [baseline.get("name") for baseline in baselines],
        "problems": problems,
    }
    print(json.dumps(payload, ensure_ascii=True, indent=2))


def render_command(template: str, values: dict[str, Any]) -> str:
    quoted = {key: shell_quote(value) for key, value in values.items()}
    return template.format(**quoted)


def resolve_baseline_cwd(baseline: dict[str, Any], worktree_dir: Path) -> Path:
    cwd_mode = baseline.get("cwd", "worktree_dir")
    if cwd_mode == "worktree_dir":
        return worktree_dir
    if cwd_mode == "repo_dir":
        repo_dir = resolve_path(baseline.get("repo_dir"))
        return repo_dir or worktree_dir
    custom_cwd = resolve_path(cwd_mode)
    return custom_cwd or worktree_dir


def source_ref_for_case(runtime_cfg: dict[str, Any], case_id: str) -> str:
    by_case = runtime_cfg.get("buggy_ref_by_case") or {}
    return by_case.get(case_id) or runtime_cfg.get("buggy_ref") or runtime_cfg.get("default_ref") or "HEAD"


def create_worktree(source_dir: Path, worktree_dir: Path, ref: str) -> None:
    if worktree_dir.exists():
        raise RuntimeError(f"worktree already exists: {worktree_dir}")
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    result = run_command(
        ["git", "-C", str(source_dir), "worktree", "add", "--detach", str(worktree_dir), ref],
        shell=False,
    )
    if not result.ok:
        raise RuntimeError(f"git worktree add failed: {result.stderr or result.stdout}")


def ensure_child_path(path: Path, root: Path, name: str) -> None:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_path == resolved_root:
        raise RuntimeError(f"refusing to clean {name} root: {resolved_path}")
    if resolved_path == REPO_ROOT.resolve():
        raise RuntimeError(f"refusing to clean repository root as {name}: {resolved_path}")
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"refusing to clean {name} outside configured root: {resolved_path}") from exc


def remove_output_dir(output_dir: Path, output_root: Path, label: str) -> None:
    ensure_child_path(output_dir, output_root, "output_dir")
    if not output_dir.exists():
        progress(f"{label} output directory does not exist; nothing to clean")
        return
    progress(f"{label} cleaning output directory: {output_dir}")
    try:
        shutil.rmtree(output_dir)
    except OSError as exc:
        raise RuntimeError(f"failed to remove output directory {output_dir}: {exc}") from exc


def remove_worktree_dir(source_dir: Path, worktree_dir: Path, worktree_root: Path, label: str) -> None:
    ensure_child_path(worktree_dir, worktree_root, "worktree_dir")
    if not worktree_dir.exists():
        progress(f"{label} worktree does not exist; nothing to clean")
        return

    progress(f"{label} cleaning worktree: {worktree_dir}")
    remove_result = run_command(
        ["git", "-C", str(source_dir), "worktree", "remove", "--force", str(worktree_dir)],
        shell=False,
    )
    progress(f"{label} git worktree remove finished returncode={remove_result.returncode}")
    prune_result = run_command(["git", "-C", str(source_dir), "worktree", "prune"], shell=False)
    progress(f"{label} git worktree prune finished returncode={prune_result.returncode}")
    if worktree_dir.exists():
        progress(f"{label} removing remaining worktree directory after git cleanup: {worktree_dir}")
        try:
            shutil.rmtree(worktree_dir)
        except OSError as exc:
            raise RuntimeError(f"failed to remove worktree directory {worktree_dir}: {exc}") from exc


def clean_previous_run(
    *,
    source_dir: Path,
    output_dir: Path,
    output_root: Path,
    worktree_dir: Path,
    worktree_root: Path,
    label: str,
) -> None:
    progress(f"{label} clean enabled")
    ensure_child_path(output_dir, output_root, "output_dir")
    ensure_child_path(worktree_dir, worktree_root, "worktree_dir")
    remove_output_dir(output_dir, output_root, label)
    remove_worktree_dir(source_dir, worktree_dir, worktree_root, label)
    progress(f"{label} clean finished")


def git_diff(worktree_dir: Path) -> str:
    result = run_command(["git", "-C", str(worktree_dir), "diff", "--binary", "--no-ext-diff"], shell=False)
    return result.stdout if result.returncode == 0 else ""


def write_command_logs(output_dir: Path, prefix: str | None, result: Any) -> None:
    if prefix:
        write_text(output_dir / f"{prefix}_stdout.log", result.stdout)
        write_text(output_dir / f"{prefix}_stderr.log", result.stderr)
    else:
        write_text(output_dir / "stdout.log", result.stdout)
        write_text(output_dir / "stderr.log", result.stderr)


def build_agentless_inputs(
    *,
    baseline: dict[str, Any],
    case: dict[str, Any],
    runtime_cfg: dict[str, Any],
    worktree_dir: Path,
    task_text: str,
    output_dir: Path,
) -> dict[str, Path]:
    task_jsonl = output_dir / "agentless_task.jsonl"
    loc_jsonl = output_dir / "agentless_locs.jsonl"
    task_jsonl.unlink(missing_ok=True)
    loc_jsonl.unlink(missing_ok=True)

    append_jsonl(
        task_jsonl,
        {
            "instance_id": case["case_id"],
            "problem_statement": task_text,
            "repo_path": str(worktree_dir),
        },
    )

    extensions = runtime_cfg.get("source_extensions") or DEFAULT_EXTENSIONS.get(case["runtime"], [])
    found_files = baseline.get("seed_files_by_case", {}).get(case["case_id"])
    if not found_files:
        found_files = scan_candidate_files(
            worktree_dir,
            task_text,
            extensions=list(extensions),
            limit=int(baseline.get("top_n_files", 5)),
        )
    append_jsonl(
        loc_jsonl,
        {
            "instance_id": case["case_id"],
            "found_files": found_files,
            "found_edit_locs": {},
        },
    )
    return {"task_jsonl": task_jsonl, "loc_jsonl": loc_jsonl}


def find_agentless_patch(agentless_output_dir: Path, case_id: str) -> str:
    candidates = sorted(agentless_output_dir.glob("*processed.jsonl"))
    candidates.append(agentless_output_dir / "output.jsonl")
    for path in candidates:
        for row in load_jsonl(path):
            if row.get("instance_id") == case_id and row.get("model_patch"):
                return row["model_patch"]
    return ""


def apply_agentless_patch(worktree_dir: Path, patch_file: Path) -> Any:
    return run_command(
        ["git", "-C", str(worktree_dir), "apply", "--whitespace=nowarn", str(patch_file)],
        shell=False,
    )


def write_oracle_error(output_dir: Path, case_id: str, error_type: str, message: str) -> None:
    write_json(
        output_dir / "oracle.json",
        {
            "case_id": case_id,
            "status": "error",
            "error_type": error_type,
            "message": message,
            "elapsed_seconds": 0,
            "comparisons": {},
            "expected_diff": "",
        },
    )


def run_one(
    *,
    config: dict[str, Any],
    case: dict[str, Any],
    baseline: dict[str, Any],
    clean: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    experiment = config.get("experiment", {})
    benchmark = config.get("benchmark", {})
    model = config.get("model", {})
    runtime_cfg = get_runtime_config(config, case["runtime"])
    source_dir = resolve_path(runtime_cfg.get("source_dir"))
    assert source_dir is not None
    label = run_label(baseline, case)

    output_root = resolve_path(experiment.get("output_dir")) or (REPO_ROOT / "results" / "oci-first20-smoke")
    worktree_root = resolve_path(experiment.get("worktree_root")) or (REPO_ROOT / "external" / "worktrees")
    output_dir = output_root / baseline["name"] / case["case_id"]
    worktree_dir = worktree_root / safe_id(experiment.get("name", "experiment")) / baseline["name"] / case["case_id"]
    progress(f"{label} initializing run paths: output={output_dir} worktree={worktree_dir}")
    if clean:
        try:
            clean_previous_run(
                source_dir=source_dir,
                output_dir=output_dir,
                output_root=output_root,
                worktree_dir=worktree_dir,
                worktree_root=worktree_root,
                label=label,
            )
        except RuntimeError as exc:
            progress(f"{label} setup error while cleaning previous run: {exc}")
            return {
                "case": case,
                "baseline": baseline.get("name"),
                "baseline_kind": baseline.get("kind"),
                "runtime": case["runtime"],
                "worktree_dir": str(worktree_dir),
                "started_at_unix": started,
                "status": "error",
                "error": str(exc),
            }
    output_dir.mkdir(parents=True, exist_ok=True)

    ref = source_ref_for_case(runtime_cfg, case["case_id"])
    metadata: dict[str, Any] = {
        "case": case,
        "baseline": baseline.get("name"),
        "baseline_kind": baseline.get("kind"),
        "runtime": case["runtime"],
        "source_ref": ref,
        "worktree_dir": str(worktree_dir),
        "started_at_unix": started,
    }

    try:
        progress(f"{label} creating worktree from {source_dir} at {ref}")
        create_worktree(source_dir, worktree_dir, ref)
        progress(f"{label} worktree created: {worktree_dir}")
    except RuntimeError as exc:
        progress(f"{label} setup error while creating worktree: {exc}")
        metadata["status"] = "error"
        metadata["error"] = str(exc)
        write_json(output_dir / "metadata.json", metadata)
        write_oracle_error(output_dir, case["case_id"], "setup", str(exc))
        return metadata

    progress(f"{label} writing task prompt")
    task_text = build_task_text(case, runtime_cfg)
    task_file = output_dir / "task.md"
    write_text(task_file, task_text)

    baseline_output_dir = output_dir / baseline.get("output_dir_name", f"{baseline['name']}-output")
    baseline_repo_dir = resolve_path(baseline.get("repo_dir")) or Path("")
    command_values: dict[str, Any] = {
        "model": baseline.get("model") or model.get("name", ""),
        "task_text": task_text,
        "task_file": task_file,
        "case_id": case["case_id"],
        "worktree_dir": worktree_dir,
        "repo_root": REPO_ROOT,
        "baseline_repo_dir": baseline_repo_dir,
        "baseline_output_dir": baseline_output_dir,
        "output_dir": output_dir,
        "trajectory_file": output_dir / baseline.get("trajectory_name", "trajectory.json"),
        "max_samples": baseline.get("max_samples", 1),
        "top_n_files": baseline.get("top_n_files", 5),
    }

    baseline_cwd = resolve_baseline_cwd(baseline, worktree_dir)
    if baseline.get("kind") == "agentless_oci":
        progress(f"{label} preparing Agentless OCI inputs")
        repo_dir = resolve_path(baseline.get("repo_dir"))
        baseline_cwd = repo_dir or worktree_dir
        agentless_output_dir = output_dir / baseline.get("output_dir_name", "agentless-output")
        agentless_inputs = build_agentless_inputs(
            baseline=baseline,
            case=case,
            runtime_cfg=runtime_cfg,
            worktree_dir=worktree_dir,
            task_text=task_text,
            output_dir=output_dir,
        )
        command_values.update(
            {
                "task_jsonl": agentless_inputs["task_jsonl"],
                "loc_jsonl": agentless_inputs["loc_jsonl"],
                "agentless_output_dir": agentless_output_dir,
            }
        )
        progress(f"{label} Agentless inputs ready: task={agentless_inputs['task_jsonl']} loc={agentless_inputs['loc_jsonl']}")

    command = render_command(baseline["command"], command_values)
    progress(f"{label} running baseline command in {baseline_cwd}")
    baseline_result = run_command(
        command,
        cwd=baseline_cwd,
        timeout=int(experiment.get("timeout_seconds", 1800)),
    )
    progress(f"{label} baseline finished returncode={baseline_result.returncode} timed_out={baseline_result.timed_out}")
    write_command_logs(output_dir, None, baseline_result)
    metadata["baseline_result"] = baseline_result.to_dict()

    if baseline.get("kind") == "agentless_oci":
        agentless_output_dir = output_dir / baseline.get("output_dir_name", "agentless-output")
        progress(f"{label} collecting Agentless patch from {agentless_output_dir}")
        raw_patch = find_agentless_patch(agentless_output_dir, case["case_id"])
        if raw_patch:
            raw_patch_file = output_dir / "agentless_model.patch"
            write_text(raw_patch_file, raw_patch)
            progress(f"{label} applying Agentless patch: {raw_patch_file}")
            apply_result = apply_agentless_patch(worktree_dir, raw_patch_file)
            progress(f"{label} Agentless patch apply finished returncode={apply_result.returncode}")
            write_command_logs(output_dir, "agentless_apply", apply_result)
            metadata["agentless_apply_result"] = apply_result.to_dict()
        else:
            progress(f"{label} Agentless did not produce a model_patch")
            metadata["agentless_patch_missing"] = True

    progress(f"{label} collecting git diff")
    patch = git_diff(worktree_dir)
    write_text(output_dir / "candidate.patch", patch)
    metadata["patch_size_bytes"] = len(patch.encode("utf-8"))
    progress(f"{label} candidate patch size={metadata['patch_size_bytes']} bytes")
    if not patch.strip():
        progress(f"{label} error: baseline produced no git diff")
        metadata["status"] = "error"
        metadata["error"] = "baseline produced no git diff"
        write_json(output_dir / "metadata.json", metadata)
        write_oracle_error(output_dir, case["case_id"], "baseline", "baseline produced no git diff")
        return metadata

    progress(f"{label} building candidate runtime")
    build_result = run_command(
        runtime_cfg["build_command"],
        cwd=worktree_dir,
        timeout=int(experiment.get("timeout_seconds", 1800)),
    )
    progress(f"{label} build finished returncode={build_result.returncode} timed_out={build_result.timed_out}")
    write_command_logs(output_dir, "build", build_result)
    metadata["build_result"] = build_result.to_dict()
    if not build_result.ok:
        progress(f"{label} error: build failed")
        metadata["status"] = "error"
        metadata["error"] = "build failed"
        write_json(output_dir / "metadata.json", metadata)
        write_oracle_error(output_dir, case["case_id"], "build", "build failed")
        return metadata

    candidate_runtime = Path(runtime_cfg["runtime_path"])
    if not candidate_runtime.is_absolute():
        candidate_runtime = worktree_dir / candidate_runtime
    progress(f"{label} validating candidate runtime path: {candidate_runtime}")
    if not candidate_runtime.exists():
        progress(f"{label} error: candidate runtime missing after build")
        metadata["status"] = "error"
        metadata["error"] = f"candidate runtime missing after build: {candidate_runtime}"
        write_json(output_dir / "metadata.json", metadata)
        write_oracle_error(output_dir, case["case_id"], "build", metadata["error"])
        return metadata

    oracle_script = REPO_ROOT / "oracles" / "run_oci_oracle.py"
    oracle_timeout = int(config.get("oracle", {}).get("timeout_seconds", 300))
    oracle_command = [
        sys.executable,
        str(oracle_script),
        "--case",
        case["case_id"],
        "--case-dir",
        case["case_dir"],
        "--candidate",
        str(candidate_runtime),
        "--reference",
        str(runtime_cfg["reference_runtime"]),
        "--rootfs-tar",
        str(resolve_path(benchmark.get("rootfs_tar"))),
        "--output",
        str(output_dir / "oracle.json"),
        "--timeout",
        str(oracle_timeout),
    ]
    progress(f"{label} running oracle")
    oracle_result = run_command(oracle_command, timeout=oracle_timeout * 4, shell=False)
    progress(f"{label} oracle finished returncode={oracle_result.returncode} timed_out={oracle_result.timed_out}")
    write_command_logs(output_dir, "oracle", oracle_result)
    metadata["oracle_result"] = oracle_result.to_dict()
    metadata["status"] = "done"
    metadata["elapsed_seconds"] = round(time.monotonic() - started, 3)
    progress(f"{label} writing final metadata: {output_dir / 'metadata.json'}")
    write_json(output_dir / "metadata.json", metadata)
    progress(f"{label} run done elapsed_seconds={metadata['elapsed_seconds']}")
    return metadata


def main() -> int:
    args = parse_args()
    progress(f"loading config: {args.config}")
    config = load_config(args.config)
    cases, case_problems = selected_cases(config, args.case, args.limit)
    baselines = enabled_baselines(config, args.baseline)
    progress(f"selected {len(cases)} case(s), {len(baselines)} baseline(s)")
    progress("running preflight checks")
    problems = case_problems + preflight(config, cases, baselines)
    progress(f"preflight finished with {len(problems)} problem(s)")

    if args.dry_run:
        if args.clean:
            progress("clean requested with dry-run; no files will be removed")
        progress("dry-run mode: printing plan without executing baselines")
        print_dry_run(config, cases, baselines, problems)
        return 0
    if problems:
        progress("preflight failed; aborting experiment")
        print(json.dumps({"problems": problems}, ensure_ascii=True, indent=2), file=sys.stderr)
        return 2

    results = []
    for baseline in baselines:
        for case in cases:
            label = run_label(baseline, case)
            progress(f"{label} starting run")
            results.append(run_one(config=config, case=case, baseline=baseline, clean=args.clean))
            progress(f"{label} finished run status={results[-1].get('status')}")
    print(json.dumps({"runs": results}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
