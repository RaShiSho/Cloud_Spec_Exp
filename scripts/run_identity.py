"""Stable, credential-safe identities for experiment resume."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from model_profiles import ROOT, ResolvedProfile, digest
from oci_common import REQUIRED_CASE_FILES, resolve_path


def file_digest(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def git_output(repo: Path | None, *args: str) -> str:
    if repo is None or not repo.is_dir():
        return ""
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def execution_inputs(config: dict[str, Any], baselines: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute shared file hashes once before any task starts."""
    implementation = {}
    for directory in ("scripts", "baselines", "oracles"):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.is_file() and path.suffix in {".py", ".sh", ".patch"} and not path.name.startswith("test_"):
                implementation[str(path.relative_to(ROOT))] = file_digest(path)
    baseline_revisions = {}
    for baseline in baselines:
        repo = resolve_path(baseline["repo_dir"])
        baseline_revisions[baseline["name"]] = {
            "revision": git_output(repo, "rev-parse", "HEAD"),
            "diff_sha256": digest(git_output(repo, "diff", "HEAD", "--binary", "--no-ext-diff")),
        }
    return {
        "implementation_sha256": digest(implementation),
        "rootfs_sha256": file_digest(resolve_path(config["benchmark"]["rootfs_tar"])),
        "baseline_revisions": baseline_revisions,
        "cost_rates": {name: os.environ.get(name) for name in ("METAGPT_PROMPT_COST_PER_1K", "METAGPT_COMPLETION_COST_PER_1K")},
    }


def run_identity(config: dict[str, Any], baseline: dict[str, Any], case: dict[str, Any], profile: ResolvedProfile, inputs: dict[str, Any]) -> dict[str, Any]:
    runtime = config["runtimes"][case["runtime"]]
    ref = runtime.get("buggy_ref_by_case", {}).get(case["case_id"]) or runtime.get("buggy_ref") or runtime.get("default_ref") or "HEAD"
    reference = runtime["reference_runtime"]
    reference_path = Path(shutil.which(reference) or reference)
    payload = {
        "schema_version": 1,
        "experiment_config": config,
        "model_profile": profile.identity(),
        "baseline": baseline,
        "case": case,
        "source_commit": git_output(resolve_path(runtime["source_dir"]), "rev-parse", "--verify", f"{ref}^{{commit}}"),
        "case_files": {name: file_digest(Path(case["case_dir"]) / name) for name in REQUIRED_CASE_FILES},
        "reference_runtime_sha256": file_digest(reference_path),
        "inputs": {key: value for key, value in inputs.items() if key != "baseline_revisions"},
        "baseline_revision": inputs["baseline_revisions"][baseline["name"]],
    }
    return {"fingerprint": digest(payload), "configuration": payload}
