from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from oci_common import load_config, load_oci_cases, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and validate OCI dataset case metadata.")
    parser.add_argument("--config", required=True, help="Experiment YAML config.")
    parser.add_argument("--output", help="Optional JSON output path for the selected cases.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print without writing files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    cases, problems = load_oci_cases(config)

    payload = {
        "config": str(Path(args.config)),
        "case_count": len(cases),
        "cases": cases,
        "problems": problems,
    }

    print(json.dumps(payload, ensure_ascii=True, indent=2))
    if args.dry_run:
        return 0

    if problems:
        return 2
    if args.output:
        write_json(Path(args.output), payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
