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
        return json.load(f)


def collect(results_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for oracle_path in sorted(results_dir.glob("*/*/oracle.json")):
        baseline = oracle_path.parent.parent.name
        case_id = oracle_path.parent.name
        try:
            oracle = load_oracle(oracle_path)
        except (OSError, json.JSONDecodeError) as exc:
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
                "oracle_path": str(oracle_path),
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
        "| Baseline | pass | fail | error | env_error |",
        "|---|---:|---:|---:|---:|",
    ]
    for baseline, counts in summary["by_baseline"].items():
        lines.append(
            f"| {baseline} | {counts.get('pass', 0)} | {counts.get('fail', 0)} | {counts.get('error', 0)} | {counts.get('env_error', 0)} |"
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
