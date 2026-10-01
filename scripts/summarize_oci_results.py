from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from oci_common import write_json, write_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize OCI experiment oracle results.")
    parser.add_argument("--results-dir", required=True, help="Experiment results directory.")
    parser.add_argument("--output-json", help="Summary JSON path. Defaults to <results-dir>/summary.json.")
    parser.add_argument("--output-md", help="Summary Markdown path. Defaults to <results-dir>/summary.md.")
    return parser.parse_args()


def load_oracle(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def missing_oracle(metadata_path: Path, case_id: str) -> dict[str, Any]:
    metadata = load_oracle(metadata_path)
    terminal = metadata.get("status") in {"error", "done"}
    return {
        "case_id": metadata.get("case_id", case_id),
        "status": "error" if terminal else "incomplete",
        "error_type": "execution" if metadata.get("status") == "error" else "missing_oracle",
        "message": metadata.get("error") or "missing oracle.json; no completed behavioral verdict",
        "elapsed_seconds": metadata.get("elapsed_seconds", 0),
    }


def collect(results_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # Include legacy failures and interrupted runs which only wrote metadata.
    directories = {path.parent for pattern in ("*/*/oracle.json", "*/*/metadata.json") for path in results_dir.glob(pattern)}
    for directory in sorted(directories):
        oracle_path = directory / "oracle.json"
        metadata_path = directory / "metadata.json"
        baseline = directory.parent.name
        case_id = directory.name
        try:
            oracle = load_oracle(oracle_path) if oracle_path.exists() else missing_oracle(metadata_path, case_id)
            if oracle.get("status") not in {"pass", "fail", "error", "incomplete"}:
                raise ValueError(f"invalid oracle status: {oracle.get('status')!r}")
        except (OSError, ValueError) as exc:
            oracle = {
                "case_id": case_id,
                "status": "error",
                "error_type": "summary",
                "message": str(exc),
            }
        rows.append(
            {
                "baseline": baseline,
                "case_id": oracle.get("case_id", case_id),
                "status": oracle.get("status", "error"),
                "error_type": oracle.get("error_type"),
                "message": oracle.get("message", ""),
                "elapsed_seconds": oracle.get("elapsed_seconds", 0),
                "oracle_path": str(oracle_path) if oracle_path.exists() else None,
                "metadata_path": str(metadata_path) if metadata_path.exists() else None,
                "result_source": "oracle" if oracle_path.exists() else "metadata",
            }
        )
    return rows


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_baseline: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        status = row["status"]
        if status == "error" and row.get("error_type") == "environment":
            status = "env_error"
        by_baseline[row["baseline"]][status] += 1
    return {
        "total_results": len(rows),
        "by_baseline": {baseline: dict(counter) for baseline, counter in sorted(by_baseline.items())},
        "results": rows,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# OCI Experiment Summary",
        "",
        f"Total results: {summary['total_results']}",
        "",
        "## By Baseline",
        "",
        "| Baseline | pass | fail | error | env_error | incomplete |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for baseline, counts in summary["by_baseline"].items():
        lines.append(
            f"| {baseline} | {counts.get('pass', 0)} | {counts.get('fail', 0)} | {counts.get('error', 0)} | {counts.get('env_error', 0)} | {counts.get('incomplete', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Results",
            "",
            "| Baseline | Case | Status | Error Type | Message |",
            "|---|---|---|---|---|",
        ]
    )
    for row in summary["results"]:
        message = str(row.get("message", "")).replace("\n", " ").replace("|", "\\|")
        lines.append(
            f"| {row['baseline']} | {row['case_id']} | {row['status']} | {row.get('error_type') or ''} | {message} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    results_dir = Path(args.results_dir)
    rows = collect(results_dir)
    summary = build_summary(rows)
    output_json = Path(args.output_json) if args.output_json else results_dir / "summary.json"
    output_md = Path(args.output_md) if args.output_md else results_dir / "summary.md"
    write_json(output_json, summary)
    write_text(output_md, render_markdown(summary))
    print(json.dumps({"summary_json": str(output_json), "summary_md": str(output_md)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
