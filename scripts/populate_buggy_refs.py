from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oci_common import REPO_ROOT, case_runtime, load_config, resolve_path, run_command

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only on minimal hosts.
    yaml = None


FIX_VERBS = ("close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved")
TITLE_STOPWORDS = {
    "about",
    "after",
    "before",
    "container",
    "process",
    "runtime",
    "support",
    "using",
    "with",
    "without",
}


@dataclass
class CaseEntry:
    case_id: str
    runtime: str
    title: str
    url: str


@dataclass
class CommitCandidate:
    sha: str
    parents: list[str]
    subject: str
    body: str
    score: int
    reason: str

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def buggy_ref(self) -> str:
        return f"{self.sha}^1" if self.is_merge else f"{self.sha}^"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Populate OCI buggy_ref_by_case entries from local git history.")
    parser.add_argument("--config", required=True, help="Experiment YAML config to read and optionally update.")
    parser.add_argument("--case", action="append", dest="case_ids", help="Case id to process. Repeatable.")
    parser.add_argument("--runtime", help="Only process cases for this runtime.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing buggy_ref_by_case entries.")
    parser.add_argument("--write", action="store_true", help="Write updates to the YAML config. Default is dry-run.")
    parser.add_argument("--min-score", type=int, default=80, help="Minimum score required to write a candidate.")
    return parser.parse_args()


def load_yaml_file(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required: pip install PyYAML")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a YAML mapping: {path}")
    return data


def dump_yaml_file(path: Path, data: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required: pip install PyYAML")
    with path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def load_metadata_entries(config: dict[str, Any], requested_ids: list[str] | None) -> list[CaseEntry]:
    benchmark = config.get("benchmark", {})
    metadata_file = resolve_path(benchmark.get("metadata_file"))
    if metadata_file is None or not metadata_file.exists():
        raise FileNotFoundError(f"missing metadata_file: {metadata_file}")

    with metadata_file.open("r", encoding="utf-8") as f:
        metadata = json.load(f)
    if not isinstance(metadata, list):
        raise ValueError(f"metadata.json must be a JSON array: {metadata_file}")

    requested = set(requested_ids or [])
    if requested:
        selected = [entry for entry in metadata if entry.get("number") in requested]
        missing = sorted(requested - {entry.get("number") for entry in selected})
        if missing:
            raise ValueError(f"requested case(s) not found in metadata: {', '.join(missing)}")
    else:
        selection = benchmark.get("selection", {})
        mode = selection.get("mode", "first_n")
        if mode != "first_n":
            raise ValueError(f"Unsupported benchmark.selection.mode: {mode}")
        selected = metadata[: int(selection.get("count", 20))]

    cases: list[CaseEntry] = []
    for entry in selected:
        case_id = entry.get("number")
        if not case_id:
            continue
        cases.append(
            CaseEntry(
                case_id=case_id,
                runtime=case_runtime(case_id),
                title=entry.get("title", "") or "",
                url=entry.get("url", "") or "",
            )
        )
    return cases


def issue_number_from_url(url: str) -> str:
    match = re.search(r"/issues/(\d+)(?:$|[/?#])", url)
    return match.group(1) if match else ""


def title_tokens(title: str) -> set[str]:
    tokens = set()
    for token in re.findall(r"[A-Za-z0-9_.$-]+", title.lower()):
        token = token.strip(".$-_")
        if len(token) >= 4 and token not in TITLE_STOPWORDS:
            tokens.add(token)
    return tokens


def score_commit(commit: dict[str, Any], case: CaseEntry) -> tuple[int, list[str]]:
    message = f"{commit['subject']}\n{commit['body']}".lower()
    url = case.url.lower()
    issue_number = issue_number_from_url(case.url)
    score = 0
    reasons: list[str] = []

    if url and url in message:
        score += 100
        reasons.append("exact issue URL")

    if issue_number:
        issue_path = f"issues/{issue_number}"
        if issue_path in message:
            score += 90
            reasons.append(f"issue path {issue_path}")
        if re.search(rf"(?<![A-Za-z0-9])#{re.escape(issue_number)}(?![A-Za-z0-9])", message):
            score += 75
            reasons.append(f"issue shorthand #{issue_number}")
        if re.search(rf"\b({'|'.join(FIX_VERBS)})\b[^\n#]{{0,80}}(?:#|issues/){re.escape(issue_number)}\b", message):
            score += 15
            reasons.append("fix verb near issue id")

    tokens = title_tokens(case.title)
    if tokens:
        overlap = sorted(token for token in tokens if token in message)
        if overlap:
            bonus = min(15, len(overlap) * 3)
            score += bonus
            reasons.append(f"title token overlap: {', '.join(overlap[:5])}")

    if "revert" in commit["subject"].lower():
        score -= 20
        reasons.append("revert penalty")

    return score, reasons


def parse_git_log(stdout: str) -> list[dict[str, Any]]:
    commits: list[dict[str, Any]] = []
    for raw_record in stdout.split("\x1e"):
        record = raw_record.strip("\n")
        if not record:
            continue
        parts = record.split("\x00", 4)
        if len(parts) != 5:
            continue
        sha, parents, timestamp, subject, body = parts
        commits.append(
            {
                "sha": sha,
                "parents": [parent for parent in parents.split() if parent],
                "timestamp": int(timestamp or 0),
                "subject": subject.strip(),
                "body": body.strip(),
            }
        )
    return commits


def find_best_candidate(source_dir: Path, case: CaseEntry) -> CommitCandidate | None:
    result = run_command(
        ["git", "-C", str(source_dir), "log", "--all", "--format=%H%x00%P%x00%ct%x00%s%x00%B%x1e"],
        shell=False,
    )
    if not result.ok:
        raise RuntimeError(f"git log failed in {source_dir}: {result.stderr or result.stdout}")

    candidates: list[CommitCandidate] = []
    for commit in parse_git_log(result.stdout):
        score, reasons = score_commit(commit, case)
        if score <= 0:
            continue
        candidates.append(
            CommitCandidate(
                sha=commit["sha"],
                parents=commit["parents"],
                subject=commit["subject"],
                body=commit["body"],
                score=score,
                reason="; ".join(reasons),
            )
        )

    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item.score, not item.is_merge), reverse=True)[0]


def ensure_buggy_ref_map(config: dict[str, Any], runtime: str) -> dict[str, str]:
    runtimes = config.setdefault("runtimes", {})
    runtime_cfg = runtimes.setdefault(runtime, {})
    by_case = runtime_cfg.setdefault("buggy_ref_by_case", {})
    if by_case is None:
        by_case = {}
        runtime_cfg["buggy_ref_by_case"] = by_case
    if not isinstance(by_case, dict):
        raise ValueError(f"runtimes.{runtime}.buggy_ref_by_case must be a mapping")
    return by_case


def process_case(
    *,
    config: dict[str, Any],
    case: CaseEntry,
    min_score: int,
    overwrite: bool,
    write: bool,
) -> dict[str, Any]:
    runtimes = config.get("runtimes", {})
    runtime_cfg = runtimes.get(case.runtime)
    if not runtime_cfg:
        return {
            "case_id": case.case_id,
            "runtime": case.runtime,
            "status": "skipped",
            "reason": f"missing runtime config for {case.runtime}",
        }

    source_dir = resolve_path(runtime_cfg.get("source_dir"))
    if source_dir is None or not source_dir.exists():
        return {
            "case_id": case.case_id,
            "runtime": case.runtime,
            "status": "skipped",
            "reason": f"missing source_dir: {source_dir}",
        }

    by_case = ensure_buggy_ref_map(config, case.runtime)
    old_value = by_case.get(case.case_id)
    candidate = find_best_candidate(source_dir, case)
    payload: dict[str, Any] = {
        "case_id": case.case_id,
        "runtime": case.runtime,
        "old_value": old_value,
    }

    if candidate:
        payload.update(
            {
                "fix_commit": candidate.sha,
                "buggy_ref": candidate.buggy_ref,
                "score": candidate.score,
                "subject": candidate.subject,
                "reason": candidate.reason,
            }
        )
    else:
        payload.update({"status": "skipped", "reason": "no matching commit found"})
        return payload

    if old_value and not overwrite:
        payload["status"] = "skipped"
        payload["reason"] = f"existing mapping present: {old_value}"
        return payload

    if candidate.score < min_score:
        payload["status"] = "skipped"
        payload["reason"] = f"candidate score below min_score={min_score}: {candidate.score}"
        return payload

    if write:
        by_case[case.case_id] = candidate.buggy_ref
        payload["status"] = "written"
    else:
        payload["status"] = "would_write"
    return payload


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    config = load_config(config_path)
    writable_config = load_yaml_file(config_path)
    cases = load_metadata_entries(config, args.case_ids)
    if args.runtime:
        cases = [case for case in cases if case.runtime == args.runtime]

    results = [
        process_case(
            config=writable_config,
            case=case,
            min_score=args.min_score,
            overwrite=args.overwrite,
            write=args.write,
        )
        for case in cases
    ]

    if args.write and any(result.get("status") == "written" for result in results):
        dump_yaml_file(config_path, writable_config)

    payload = {
        "config": str(config_path),
        "write": args.write,
        "overwrite": args.overwrite,
        "min_score": args.min_score,
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
