#!/usr/bin/env bash
set -euo pipefail

BASELINE_NAME="repairagent"
BASELINE_REPO=""
REPO=""
TASK_FILE=""
OUTPUT_DIR=""
MODEL=""
BASE_URL="${REPAIRAGENT_BASE_URL:-${OPENAI_API_BASE:-${OPENAI_BASE_URL:-https://api.deepseek.com}}}"
TEST_COMMAND=""
SOURCE_EXTENSIONS=""
TIMEOUT_SECONDS="0"
MAX_CYCLES="40"
TEST_TIMEOUT_SECONDS="600"

usage() {
  cat >&2 <<'EOF'
Usage: run_oci_repair.sh --baseline-repo DIR --repo DIR --task-file FILE --output-dir DIR --model MODEL --test-command COMMAND [options]

Run RepairAgent's upstream FSM with an OCI-compatible tool layer.

Options:
  --base-url URL                 OpenAI-compatible API base URL.
  --source-extensions CSV        Source suffixes visible to search (for example .c,.h).
  --timeout-seconds N            Stop RepairAgent after N seconds (0 disables).
  --max-cycles N                 Maximum RepairAgent command cycles (default: 40).
  --test-timeout-seconds N       Per-build timeout used by write_fix (default: 600).

Environment:
  REPAIRAGENT_CONDA_ENV          Run with "conda run -n ENV python".
  REPAIRAGENT_PYTHON             Otherwise use this Python executable.
  REPAIRAGENT_API_KEY            Preferred API key; falls back to DEEPSEEK_API_KEY,
                                 then OPENAI_API_KEY.
  REPAIRAGENT_BASE_URL           Default OpenAI-compatible API base URL.
  REPAIRAGENT_TEMPERATURE        LLM temperature (default: 0).
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --baseline-repo) BASELINE_REPO="${2:-}"; shift 2 ;;
    --repo) REPO="${2:-}"; shift 2 ;;
    --task-file) TASK_FILE="${2:-}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
    --model) MODEL="${2:-}"; shift 2 ;;
    --base-url) BASE_URL="${2:-}"; shift 2 ;;
    --test-command) TEST_COMMAND="${2:-}"; shift 2 ;;
    --source-extensions) SOURCE_EXTENSIONS="${2:-}"; shift 2 ;;
    --timeout-seconds) TIMEOUT_SECONDS="${2:-}"; shift 2 ;;
    --max-cycles) MAX_CYCLES="${2:-}"; shift 2 ;;
    --test-timeout-seconds) TEST_TIMEOUT_SECONDS="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

if [ -z "$BASELINE_REPO" ] || [ -z "$REPO" ] || [ -z "$TASK_FILE" ] || [ -z "$OUTPUT_DIR" ] || [ -z "$MODEL" ] || [ -z "$TEST_COMMAND" ]; then
  echo "Missing required argument." >&2
  usage
  exit 2
fi

for pair in "timeout-seconds:$TIMEOUT_SECONDS" "max-cycles:$MAX_CYCLES" "test-timeout-seconds:$TEST_TIMEOUT_SECONDS"; do
  name="${pair%%:*}"
  value="${pair#*:}"
  case "$value" in
    ''|*[!0-9]*) echo "--$name must be a non-negative integer: $value" >&2; exit 2 ;;
  esac
done
if [ "$MAX_CYCLES" -eq 0 ] || [ "$TEST_TIMEOUT_SECONDS" -eq 0 ]; then
  echo "--max-cycles and --test-timeout-seconds must be positive." >&2
  exit 2
fi

if [ ! -f "$BASELINE_REPO/repair_agent/autogpt/agents/base.py" ]; then
  echo "Missing upstream RepairAgent source: $BASELINE_REPO/repair_agent/autogpt/agents/base.py" >&2
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
  echo "Missing RepairAgent adapter launcher: $LAUNCHER" >&2
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

if [ -n "${REPAIRAGENT_CONDA_ENV:-}" ]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "REPAIRAGENT_CONDA_ENV is set, but conda is not available on PATH." >&2
    exit 2
  fi
  REPAIRAGENT_PYTHON_CMD=(conda run --no-capture-output -n "$REPAIRAGENT_CONDA_ENV" python)
elif [ -n "${REPAIRAGENT_PYTHON:-}" ]; then
  if ! command -v "$REPAIRAGENT_PYTHON" >/dev/null 2>&1; then
    echo "REPAIRAGENT_PYTHON is not executable or not on PATH: $REPAIRAGENT_PYTHON" >&2
    exit 2
  fi
  REPAIRAGENT_PYTHON_CMD=("$REPAIRAGENT_PYTHON")
else
  REPAIRAGENT_PYTHON_CMD=("$PYTHON_BIN")
fi

if [ "$TIMEOUT_SECONDS" -gt 0 ] && ! command -v timeout >/dev/null 2>&1; then
  echo "--timeout-seconds requires GNU timeout on PATH." >&2
  exit 2
fi

API_KEY="${REPAIRAGENT_API_KEY:-${DEEPSEEK_API_KEY:-${OPENAI_API_KEY:-}}}"
if [ -z "$API_KEY" ]; then
  echo "Missing API key: set REPAIRAGENT_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY." >&2
  exit 2
fi

"$PYTHON_BIN" - "$BASELINE_NAME" "$BASELINE_REPO" "$REPO" "$TASK_FILE" "$OUTPUT_DIR" "$MODEL" "$BASE_URL" "$TEST_COMMAND" "$SOURCE_EXTENSIONS" "$TIMEOUT_SECONDS" "$MAX_CYCLES" "$TEST_TIMEOUT_SECONDS" "$(pwd)" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

(baseline, baseline_repo, repo, task_file, output_dir, model, base_url,
 test_command, source_extensions, timeout_seconds, max_cycles,
 test_timeout_seconds, cwd) = sys.argv[1:]
revision = subprocess.run(
    ["git", "-c", f"safe.directory={Path(baseline_repo).resolve()}", "-C", baseline_repo, "rev-parse", "HEAD"],
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
    "base_url": base_url or None,
    "test_command": test_command,
    "source_extensions": source_extensions,
    "timeout_seconds": int(timeout_seconds),
    "max_cycles": int(max_cycles),
    "test_timeout_seconds": int(test_timeout_seconds),
    "cwd": cwd,
    "adapter_status": "starting",
    "adapter_mode": "upstream_fsm_with_oci_tool_layer",
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
  "${REPAIRAGENT_PYTHON_CMD[@]}" "$LAUNCHER"
  --baseline-repo "$BASELINE_REPO"
  --repo "$REPO"
  --task-file "$TASK_FILE"
  --output-dir "$OUTPUT_DIR"
  --model "$MODEL"
  --test-command "$TEST_COMMAND"
  --source-extensions "$SOURCE_EXTENSIONS"
  --max-cycles "$MAX_CYCLES"
  --test-timeout-seconds "$TEST_TIMEOUT_SECONDS"
)
if [ -n "$BASE_URL" ]; then
  LAUNCH_COMMAND+=(--base-url "$BASE_URL")
fi

echo "Starting RepairAgent with the OCI tool compatibility layer." >&2
set +e
if [ "$TIMEOUT_SECONDS" -gt 0 ]; then
  OPENAI_API_KEY="$API_KEY" \
  OPENAI_API_BASE_URL="$BASE_URL" \
  PYTHONPATH="$BASELINE_REPO/repair_agent:$ADAPTER_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    timeout --signal=TERM --kill-after=30s "${TIMEOUT_SECONDS}s" "${LAUNCH_COMMAND[@]}"
else
  OPENAI_API_KEY="$API_KEY" \
  OPENAI_API_BASE_URL="$BASE_URL" \
  PYTHONPATH="$BASELINE_REPO/repair_agent:$ADAPTER_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    "${LAUNCH_COMMAND[@]}"
fi
EXIT_CODE=$?
set -e

if [ "$EXIT_CODE" -ne 0 ]; then
  if [ "$EXIT_CODE" -eq 65 ]; then
    update_wrapper_metadata "patch_missing" "$EXIT_CODE"
  else
    update_wrapper_metadata "repairagent_failed" "$EXIT_CODE"
  fi
  exit "$EXIT_CODE"
fi

update_wrapper_metadata "completed" "0"
