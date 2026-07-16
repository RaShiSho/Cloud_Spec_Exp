#!/usr/bin/env bash
set -euo pipefail

BASELINE_NAME="metagpt"
BASELINE_REPO=""
REPO=""
TASK_FILE=""
OUTPUT_DIR=""
MODEL=""
API_TYPE="${METAGPT_API_TYPE:-deepseek}"
BASE_URL="${METAGPT_BASE_URL:-${OPENAI_API_BASE:-${OPENAI_BASE_URL:-}}}"
TIMEOUT_SECONDS="0"
N_ROUND="10"
INVESTMENT="3.0"
MAX_AUTO_SUMMARIZE_CODE="0"
RUN_TESTS="false"

usage() {
  cat >&2 <<'EOF'
Usage: run_oci_repair.sh --baseline-repo DIR --repo DIR --task-file FILE --output-dir DIR --model MODEL [options]

Run MetaGPT incremental development against an OCI runtime worktree.

Options:
  --api-type TYPE                 MetaGPT LLM provider type (default: deepseek).
  --base-url URL                  OpenAI-compatible API base URL.
  --timeout-seconds N             Stop MetaGPT after N seconds (0 disables).
  --n-round N                     MetaGPT team rounds (default: 10).
  --investment N                  MetaGPT team budget (default: 3.0).
  --max-auto-summarize-code N     SummarizeCode retry limit (default: 0).
  --run-tests                     Enable MetaGPT's upstream run_tests flag.

Environment:
  METAGPT_CONDA_ENV               Run with "conda run -n ENV python".
  METAGPT_PYTHON                  Otherwise use this Python executable.
  METAGPT_API_KEY                 Preferred API key; falls back to
                                  DEEPSEEK_API_KEY, then OPENAI_API_KEY.
  METAGPT_API_TYPE                Default for --api-type.
  METAGPT_BASE_URL                Default for --base-url.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --baseline-repo) BASELINE_REPO="${2:-}"; shift 2 ;;
    --repo) REPO="${2:-}"; shift 2 ;;
    --task-file) TASK_FILE="${2:-}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
    --model) MODEL="${2:-}"; shift 2 ;;
    --api-type) API_TYPE="${2:-}"; shift 2 ;;
    --base-url) BASE_URL="${2:-}"; shift 2 ;;
    --timeout-seconds) TIMEOUT_SECONDS="${2:-}"; shift 2 ;;
    --n-round) N_ROUND="${2:-}"; shift 2 ;;
    --investment) INVESTMENT="${2:-}"; shift 2 ;;
    --max-auto-summarize-code) MAX_AUTO_SUMMARIZE_CODE="${2:-}"; shift 2 ;;
    --run-tests) RUN_TESTS="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

if [ -z "$BASELINE_REPO" ] || [ -z "$REPO" ] || [ -z "$TASK_FILE" ] || [ -z "$OUTPUT_DIR" ] || [ -z "$MODEL" ]; then
  echo "Missing required argument." >&2
  usage
  exit 2
fi

for pair in "timeout-seconds:$TIMEOUT_SECONDS" "n-round:$N_ROUND" "max-auto-summarize-code:$MAX_AUTO_SUMMARIZE_CODE"; do
  name="${pair%%:*}"
  value="${pair#*:}"
  case "$value" in
    ''|*[!0-9]*) echo "--$name must be a non-negative integer: $value" >&2; exit 2 ;;
  esac
done

if [ ! -d "$BASELINE_REPO" ]; then
  echo "Missing baseline repo: $BASELINE_REPO" >&2
  exit 2
fi
if [ ! -f "$BASELINE_REPO/metagpt/software_company.py" ]; then
  echo "Missing MetaGPT software-company entrypoint: $BASELINE_REPO/metagpt/software_company.py" >&2
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

ADAPTER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
LAUNCHER="$ADAPTER_DIR/launch.py"
if [ ! -f "$LAUNCHER" ]; then
  echo "Missing MetaGPT adapter launcher: $LAUNCHER" >&2
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

if [ -n "${METAGPT_CONDA_ENV:-}" ]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "METAGPT_CONDA_ENV is set, but conda is not available on PATH." >&2
    exit 2
  fi
  METAGPT_PYTHON_CMD=(conda run --no-capture-output -n "$METAGPT_CONDA_ENV" python)
elif [ -n "${METAGPT_PYTHON:-}" ]; then
  if ! command -v "$METAGPT_PYTHON" >/dev/null 2>&1; then
    echo "METAGPT_PYTHON is not executable or not on PATH: $METAGPT_PYTHON" >&2
    exit 2
  fi
  METAGPT_PYTHON_CMD=("$METAGPT_PYTHON")
else
  METAGPT_PYTHON_CMD=("$PYTHON_BIN")
fi

if [ "$TIMEOUT_SECONDS" -gt 0 ] && ! command -v timeout >/dev/null 2>&1; then
  echo "--timeout-seconds requires GNU timeout on PATH." >&2
  exit 2
fi

RUN_HOME="$OUTPUT_DIR/.metagpt-home-$$"
mkdir -p "$RUN_HOME"
cleanup() {
  if [ -n "${RUN_HOME:-}" ] && [ -d "$RUN_HOME" ]; then
    rm -rf -- "$RUN_HOME"
  fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

"$PYTHON_BIN" - "$BASELINE_NAME" "$BASELINE_REPO" "$REPO" "$TASK_FILE" "$OUTPUT_DIR" "$MODEL" "$API_TYPE" "$BASE_URL" "$N_ROUND" "$INVESTMENT" "$MAX_AUTO_SUMMARIZE_CODE" "$RUN_TESTS" "$(pwd)" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

(baseline, baseline_repo, repo, task_file, output_dir, model, api_type, base_url,
 n_round, investment, max_auto_summarize_code, run_tests, cwd) = sys.argv[1:]
revision = subprocess.run(
    ["git", "-C", baseline_repo, "rev-parse", "HEAD"],
    capture_output=True,
    text=True,
    check=False,
).stdout.strip()
payload = {
    "baseline": baseline,
    "baseline_repo": baseline_repo,
    "baseline_revision": revision or None,
    "repo": repo,
    "task_file": task_file,
    "output_dir": output_dir,
    "model": model,
    "api_type": api_type,
    "base_url": base_url or None,
    "n_round": int(n_round),
    "investment": float(investment),
    "max_auto_summarize_code": int(max_auto_summarize_code),
    "run_tests": run_tests == "true",
    "cwd": cwd,
    "adapter_status": "starting",
}
Path(output_dir, "wrapper_metadata.json").write_text(
    json.dumps(payload, indent=2) + "\n", encoding="utf-8"
)
PY

update_wrapper_metadata() {
  local status="$1"
  local exit_code="${2:-}"
  "$PYTHON_BIN" - "$OUTPUT_DIR" "$status" "$exit_code" <<'PY'
import json
import sys
from pathlib import Path

output_dir, status, exit_code = sys.argv[1:]
path = Path(output_dir, "wrapper_metadata.json")
payload = json.loads(path.read_text(encoding="utf-8"))
payload["adapter_status"] = status
if exit_code:
    payload["adapter_exit_code"] = int(exit_code)
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

LAUNCH_COMMAND=(
  "${METAGPT_PYTHON_CMD[@]}" "$LAUNCHER"
  --baseline-repo "$BASELINE_REPO"
  --repo "$REPO"
  --task-file "$TASK_FILE"
  --output-dir "$OUTPUT_DIR"
  --model "$MODEL"
  --api-type "$API_TYPE"
  --n-round "$N_ROUND"
  --investment "$INVESTMENT"
  --max-auto-summarize-code "$MAX_AUTO_SUMMARIZE_CODE"
)
if [ -n "$BASE_URL" ]; then
  LAUNCH_COMMAND+=(--base-url "$BASE_URL")
fi
if [ "$RUN_TESTS" = "true" ]; then
  LAUNCH_COMMAND+=(--run-tests)
fi

echo "Starting MetaGPT incremental repair mode." >&2
set +e
if [ "$TIMEOUT_SECONDS" -gt 0 ]; then
  HOME="$RUN_HOME" \
  METAGPT_PROJECT_ROOT="$BASELINE_REPO" \
  PYTHONPATH="$BASELINE_REPO${PYTHONPATH:+:$PYTHONPATH}" \
    timeout --signal=TERM --kill-after=30s "${TIMEOUT_SECONDS}s" "${LAUNCH_COMMAND[@]}"
else
  HOME="$RUN_HOME" \
  METAGPT_PROJECT_ROOT="$BASELINE_REPO" \
  PYTHONPATH="$BASELINE_REPO${PYTHONPATH:+:$PYTHONPATH}" \
    "${LAUNCH_COMMAND[@]}"
fi
EXIT_CODE=$?
set -e

if [ "$EXIT_CODE" -ne 0 ]; then
  update_wrapper_metadata "metagpt_failed" "$EXIT_CODE"
  exit "$EXIT_CODE"
fi

update_wrapper_metadata "completed" "0"
