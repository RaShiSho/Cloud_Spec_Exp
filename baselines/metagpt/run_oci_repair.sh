#!/usr/bin/env bash
set -euo pipefail

BASELINE_NAME="metagpt"
BASELINE_REPO=""
REPO=""
TASK_FILE=""
OUTPUT_DIR=""
MODEL=""

usage() {
  cat >&2 <<'EOF'
Usage: run_oci_repair.sh --baseline-repo DIR --repo DIR --task-file FILE --output-dir DIR --model MODEL

This is a Cloud-Spec-Exp OCI adapter skeleton for MetaGPT.
It is not the upstream MetaGPT native command.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --baseline-repo)
      BASELINE_REPO="${2:-}"
      shift 2
      ;;
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --task-file)
      TASK_FILE="${2:-}"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="${2:-}"
      shift 2
      ;;
    --model)
      MODEL="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [ -z "$BASELINE_REPO" ] || [ -z "$REPO" ] || [ -z "$TASK_FILE" ] || [ -z "$OUTPUT_DIR" ] || [ -z "$MODEL" ]; then
  echo "Missing required argument." >&2
  usage
  exit 2
fi

if [ ! -d "$BASELINE_REPO" ]; then
  echo "Missing baseline repo: $BASELINE_REPO" >&2
  exit 2
fi
if [ ! -d "$REPO" ]; then
  echo "Missing candidate repo: $REPO" >&2
  exit 2
fi
if [ ! -f "$TASK_FILE" ]; then
  echo "Missing task file: $TASK_FILE" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "Missing python3/python for wrapper metadata generation." >&2
    exit 2
  fi
fi

"$PYTHON_BIN" - "$BASELINE_NAME" "$BASELINE_REPO" "$REPO" "$TASK_FILE" "$OUTPUT_DIR" "$MODEL" "$(pwd)" <<'PY'
import json
import sys
from pathlib import Path

baseline, baseline_repo, repo, task_file, output_dir, model, cwd = sys.argv[1:]
payload = {
    "baseline": baseline,
    "baseline_repo": baseline_repo,
    "repo": repo,
    "task_file": task_file,
    "output_dir": output_dir,
    "model": model,
    "cwd": cwd,
    "adapter_status": "not_implemented",
}
Path(output_dir, "wrapper_metadata.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

echo "OCI wrapper exists, but upstream invocation is not implemented yet." >&2
echo "Implement MetaGPT invocation inside baselines/metagpt/run_oci_repair.sh before enabling this baseline." >&2
exit 64
