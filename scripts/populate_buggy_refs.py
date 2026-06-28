from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from oci_common import case_runtime, load_config, resolve_path, run_command

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only on minimal hosts.
    yaml = None


FIX_VERBS = ("close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved")
GITHUB_API = "https://api.github.com"


@dataclass
class CaseEntry:
    case_id: str
    runtime: str
    title: str
    url: str


@dataclass
class GitHubIssueRef:
    owner: str
    repo: str
    issue_number: str

    @property
    def events_api_url(self) -> str:
        return f"{GITHUB_API}/repos/{self.owner}/{self.repo}/issues/{self.issue_number}/events"

    @property
    def issue_api_url(self) -> str:
        return f"{GITHUB_API}/repos/{self.owner}/{self.repo}/issues/{self.issue_number}"


@dataclass
class BuggyRefResolution:
    method: str
    buggy_ref: str
    reason: str
    fix_commit: str | None = None
    api_url: str | None = None
    created_at: str | None = None
    command: list[str] | None = None
    fallback_reasons: list[str] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Populate OCI buggy_ref_by_case entries from GitHub issue data and local git fallbacks.")
    parser.add_argument("--config", required=True, help="Experiment YAML config to read and optionally update.")
    parser.add_argument("--case", action="append", dest="case_ids", help="Case id to process. Repeatable.")
    parser.add_argument("--runtime", help="Only process cases for this runtime.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing buggy_ref_by_case entries.")
    parser.add_argument("--write", action="store_true", help="Write updates to the YAML config. Default is dry-run.")
    parser.add_argument("--min-score", type=int, default=80, help="Compatibility option; current resolver does not score candidates.")
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


def parse_github_issue_url(url: str) -> GitHubIssueRef | None:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 4 or parts[2] != "issues" or not parts[3].isdigit():
        return None
    return GitHubIssueRef(owner=parts[0], repo=parts[1], issue_number=parts[3])


def parse_link_next(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        match = re.search(r"<([^>]+)>", section)
        if match:
            return match.group(1)
    return None


def github_request_json(api_url: str) -> tuple[Any | None, str | None, str | None]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Cloud-Spec-Exp populate_buggy_refs.py",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(api_url, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload, None, parse_link_next(response.headers.get("Link"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return None, f"GitHub API HTTP {exc.code} for {api_url}: {body[:300]}", None
    except URLError as exc:
        return None, f"GitHub API URL error for {api_url}: {exc.reason}", None
    except (TimeoutError, json.JSONDecodeError) as exc:
        return None, f"GitHub API error for {api_url}: {exc}", None


def find_fix_commit_from_github_events(issue: GitHubIssueRef) -> tuple[BuggyRefResolution | None, str]:
    api_url = issue.events_api_url
    next_url: str | None = api_url
    pages_checked = 0
    while next_url and pages_checked < 10:
        pages_checked += 1
        payload, error, next_link = github_request_json(next_url)
        if error:
            return None, error
        if not isinstance(payload, list):
            return None, f"GitHub events response is not a list: {next_url}"
        for event in payload:
            if not isinstance(event, dict):
                continue
            fix_commit = event.get("commit_id")
            if event.get("event") == "closed" and fix_commit:
                return (
                    BuggyRefResolution(
                        method="github_events",
                        fix_commit=str(fix_commit),
                        buggy_ref=f"{fix_commit}^",
                        api_url=api_url,
                        reason="closed issue event with commit_id",
                    ),
                    "",
                )
        next_url = next_link
    if next_url:
        return None, "no closed event with commit_id found in first 10 GitHub events pages"
    return None, "no closed event with commit_id found in GitHub issue events"


def git_log_first_match(source_dir: Path, pattern: str) -> tuple[str | None, list[str], str | None]:
    command = [
        "git",
        "-C",
        str(source_dir),
        "log",
        "--all",
        "--extended-regexp",
        "--regexp-ignore-case",
        f"--grep={pattern}",
        "--format=%H",
        "-n",
        "1",
    ]
    result = run_command(command, shell=False)
    if not result.ok:
        return None, command, result.stderr or result.stdout or result.error or "git log failed"
    sha = result.stdout.strip().splitlines()[0] if result.stdout.strip() else None
    return sha, command, None


def find_fix_commit_from_local_git(source_dir: Path, issue_number: str) -> tuple[BuggyRefResolution | None, str]:
    if not issue_number:
        return None, "missing issue number for local git grep"

    issue_pattern = rf"(^|[^A-Za-z0-9])(#?{re.escape(issue_number)}|issues/{re.escape(issue_number)})([^A-Za-z0-9]|$)"
    verb_pattern = "|".join(FIX_VERBS)
    patterns = [
        rf"(({verb_pattern}).{{0,120}}{issue_pattern}|{issue_pattern}.{{0,120}}({verb_pattern}))",
        issue_pattern,
    ]
    last_command: list[str] | None = None
    errors: list[str] = []
    for index, pattern in enumerate(patterns):
        fix_commit, command, error = git_log_first_match(source_dir, pattern)
        last_command = command
        if error:
            errors.append(error)
            continue
        if fix_commit:
            reason = "fix/close/resolve verb near issue number" if index == 0 else "commit message contains issue number"
            return (
                BuggyRefResolution(
                    method="local_git_grep",
                    fix_commit=fix_commit,
                    buggy_ref=f"{fix_commit}^",
                    command=command,
                    reason=reason,
                ),
                "",
            )
    if errors:
        return None, "; ".join(errors)
    return None, f"no local git commit matched issue {issue_number}; last_command={last_command}"


def find_issue_created_at(issue: GitHubIssueRef) -> tuple[str | None, str]:
    payload, error, _next_link = github_request_json(issue.issue_api_url)
    if error:
        return None, error
    if not isinstance(payload, dict):
        return None, f"GitHub issue response is not an object: {issue.issue_api_url}"
    created_at = payload.get("created_at")
    if not created_at:
        return None, f"GitHub issue response missing created_at: {issue.issue_api_url}"
    return str(created_at), ""


def git_before_value(created_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return created_at
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%d %H:%M:%S +0000")


def find_buggy_commit_before_issue(source_dir: Path, created_at: str) -> tuple[BuggyRefResolution | None, str]:
    before_value = git_before_value(created_at)
    command = ["git", "-C", str(source_dir), "rev-list", "-n", "1", f"--before={before_value}", "main"]
    result = run_command(command, shell=False)
    if not result.ok:
        return None, result.stderr or result.stdout or result.error or "git rev-list failed"
    buggy_commit = result.stdout.strip().splitlines()[0] if result.stdout.strip() else None
    if not buggy_commit:
        return None, f"no commit found on main before {created_at}"
    return (
        BuggyRefResolution(
            method="issue_created_at",
            buggy_ref=buggy_commit,
            created_at=created_at,
            command=command,
            reason="nearest main commit before issue created_at",
        ),
        "",
    )


def resolve_buggy_ref(source_dir: Path, case: CaseEntry) -> tuple[BuggyRefResolution | None, list[str]]:
    issue = parse_github_issue_url(case.url)
    issue_number = issue.issue_number if issue else issue_number_from_url(case.url)
    fallback_reasons: list[str] = []

    if issue:
        resolution, reason = find_fix_commit_from_github_events(issue)
        if resolution:
            resolution.fallback_reasons = fallback_reasons
            return resolution, fallback_reasons
        fallback_reasons.append(f"github_events: {reason}")
    else:
        fallback_reasons.append(f"github_events: unsupported issue URL: {case.url}")

    resolution, reason = find_fix_commit_from_local_git(source_dir, issue_number)
    if resolution:
        resolution.fallback_reasons = fallback_reasons
        return resolution, fallback_reasons
    fallback_reasons.append(f"local_git_grep: {reason}")

    if issue:
        created_at, reason = find_issue_created_at(issue)
        if created_at:
            resolution, reason = find_buggy_commit_before_issue(source_dir, created_at)
            if resolution:
                resolution.api_url = issue.issue_api_url
                resolution.fallback_reasons = fallback_reasons
                return resolution, fallback_reasons
            fallback_reasons.append(f"issue_created_at: {reason}")
        else:
            fallback_reasons.append(f"issue_created_at: {reason}")
    else:
        fallback_reasons.append("issue_created_at: unsupported GitHub issue URL")
    return None, fallback_reasons


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
    resolution, fallback_reasons = resolve_buggy_ref(source_dir, case)
    payload: dict[str, Any] = {
        "case_id": case.case_id,
        "runtime": case.runtime,
        "old_value": old_value,
        "min_score": min_score,
    }

    if resolution:
        payload.update(
            {
                "method": resolution.method,
                "fix_commit": resolution.fix_commit,
                "buggy_ref": resolution.buggy_ref,
                "api_url": resolution.api_url,
                "created_at": resolution.created_at,
                "command": resolution.command,
                "reason": resolution.reason,
                "fallback_reasons": resolution.fallback_reasons or fallback_reasons,
            }
        )
    else:
        payload.update(
            {
                "status": "skipped",
                "reason": "no buggy ref could be resolved",
                "fallback_reasons": fallback_reasons,
            }
        )
        return payload

    if old_value and not overwrite:
        payload["status"] = "skipped"
        payload["reason"] = f"existing mapping present: {old_value}"
        return payload

    if write:
        by_case[case.case_id] = resolution.buggy_ref
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
