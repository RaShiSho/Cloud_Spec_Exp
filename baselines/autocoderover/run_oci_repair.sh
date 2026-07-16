#!/usr/bin/env bash
set -euo pipefail

BASELINE_NAME="autocoderover"
BASELINE_REPO=""
REPO=""
TASK_FILE=""
OUTPUT_DIR=""
MODEL=""
TIMEOUT_SECONDS="0"
CONV_ROUND_LIMIT="15"
SOURCE_EXTENSIONS=""

usage() {
  cat >&2 <<'EOF'
Usage: run_oci_repair.sh --baseline-repo DIR --repo DIR --task-file FILE --output-dir DIR --model MODEL [options]

This is a Cloud-Spec-Exp OCI adapter skeleton for AutoCodeRover.
It invokes AutoCodeRover upstream local-issue mode and applies the selected
patch back to the OCI worktree so the experiment runner can collect git diff.

Options:
  --timeout-seconds N    Stop one ACR invocation after N seconds (0 disables).
  --conv-round-limit N   ACR conversation round limit (default: 15).
  --source-extensions L  Comma-separated non-Python source suffixes to index.

Environment:
  ACR_CONDA_ENV          Run ACR with "conda run -n ENV python".
  ACR_PYTHON             Otherwise run ACR with this Python executable.
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
    --timeout-seconds)
      TIMEOUT_SECONDS="${2:-}"
      shift 2
      ;;
    --conv-round-limit)
      CONV_ROUND_LIMIT="${2:-}"
      shift 2
      ;;
    --source-extensions)
      SOURCE_EXTENSIONS="${2:-}"
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

case "$TIMEOUT_SECONDS" in
  ''|*[!0-9]*)
    echo "--timeout-seconds must be a non-negative integer: $TIMEOUT_SECONDS" >&2
    exit 2
    ;;
esac
case "$CONV_ROUND_LIMIT" in
  ''|*[!0-9]*)
    echo "--conv-round-limit must be a non-negative integer: $CONV_ROUND_LIMIT" >&2
    exit 2
    ;;
esac

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
if [ ! -f "$BASELINE_REPO/app/main.py" ]; then
  echo "Missing AutoCodeRover entrypoint: $BASELINE_REPO/app/main.py" >&2
  exit 2
fi

ADAPTER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ACR_LAUNCHER="$ADAPTER_DIR/launch.py"
if [ ! -f "$ACR_LAUNCHER" ]; then
  echo "Missing AutoCodeRover adapter launcher: $ACR_LAUNCHER" >&2
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

ACR_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
ACR_RUN_DIR="$OUTPUT_DIR/acr-runs/$ACR_RUN_ID"
ACR_MODEL_NAME="${ACR_MODEL:-$MODEL}"
ACR_MODEL_TEMPERATURE="${ACR_MODEL_TEMPERATURE:-0}"
ACR_TASK_ID="${ACR_TASK_ID:-$(basename "$(dirname "$TASK_FILE")")}"
mkdir -p "$ACR_RUN_DIR"

if [ -n "${ACR_CONDA_ENV:-}" ]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "ACR_CONDA_ENV is set, but conda is not available on PATH." >&2
    exit 2
  fi
  ACR_PYTHON_CMD=(conda run --no-capture-output -n "$ACR_CONDA_ENV" python)
elif [ -n "${ACR_PYTHON:-}" ]; then
  if ! command -v "$ACR_PYTHON" >/dev/null 2>&1; then
    echo "ACR_PYTHON is not executable or not on PATH: $ACR_PYTHON" >&2
    exit 2
  fi
  ACR_PYTHON_CMD=("$ACR_PYTHON")
else
  ACR_PYTHON_CMD=("$PYTHON_BIN")
fi

if [ "$TIMEOUT_SECONDS" -gt 0 ] && ! command -v timeout >/dev/null 2>&1; then
  echo "--timeout-seconds requires GNU timeout on PATH." >&2
  exit 2
fi

"$PYTHON_BIN" - "$BASELINE_NAME" "$BASELINE_REPO" "$REPO" "$TASK_FILE" "$OUTPUT_DIR" "$MODEL" "$ACR_MODEL_NAME" "$ACR_MODEL_TEMPERATURE" "$ACR_TASK_ID" "$ACR_RUN_DIR" "$SOURCE_EXTENSIONS" "$(pwd)" <<'PY'
import json
import sys
from pathlib import Path

baseline, baseline_repo, repo, task_file, output_dir, model, acr_model, acr_temperature, acr_task_id, acr_run_dir, source_extensions, cwd = sys.argv[1:]
payload = {
    "baseline": baseline,
    "baseline_repo": baseline_repo,
    "repo": repo,
    "task_file": task_file,
    "output_dir": output_dir,
    "model": model,
    "acr_model": acr_model,
    "acr_model_temperature": acr_temperature,
    "acr_task_id": acr_task_id,
    "acr_run_dir": acr_run_dir,
    "source_extensions": source_extensions,
    "cwd": cwd,
    "adapter_status": "starting",
}
Path(output_dir, "wrapper_metadata.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

update_wrapper_metadata() {
  local status="$1"
  local exit_code="${2:-}"
  local selected_patch="${3:-}"
  "$PYTHON_BIN" - "$OUTPUT_DIR" "$status" "$exit_code" "$selected_patch" <<'PY'
import json
import sys
from pathlib import Path

output_dir, status, exit_code, selected_patch = sys.argv[1:]
path = Path(output_dir, "wrapper_metadata.json")
payload = json.loads(path.read_text(encoding="utf-8"))
payload["adapter_status"] = status
if exit_code:
    payload["adapter_exit_code"] = int(exit_code)
if selected_patch:
    payload["selected_patch"] = selected_patch
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

echo "Starting AutoCodeRover local-issue mode." >&2
set +e
(
  cd "$BASELINE_REPO"
  if [ -z "${OPENAI_KEY:-}" ] && [ -n "${OPENAI_API_KEY:-}" ]; then
    export OPENAI_KEY="$OPENAI_API_KEY"
  fi
  ACR_COMMAND=(
    "${ACR_PYTHON_CMD[@]}" "$ACR_LAUNCHER" local-issue
    --output-dir "$ACR_RUN_DIR"
    --model "$ACR_MODEL_NAME"
    --model-temperature "$ACR_MODEL_TEMPERATURE"
    --conv-round-limit "$CONV_ROUND_LIMIT"
    --task-id "$ACR_TASK_ID"
    --local-repo "$REPO"
    --issue-file "$TASK_FILE"
  )
  if [ "$TIMEOUT_SECONDS" -gt 0 ]; then
    ACR_SOURCE_EXTENSIONS="$SOURCE_EXTENSIONS" \
      PYTHONPATH="$BASELINE_REPO${PYTHONPATH:+:$PYTHONPATH}" \
      timeout --signal=TERM --kill-after=30s "${TIMEOUT_SECONDS}s" "${ACR_COMMAND[@]}"
  else
    ACR_SOURCE_EXTENSIONS="$SOURCE_EXTENSIONS" \
      PYTHONPATH="$BASELINE_REPO${PYTHONPATH:+:$PYTHONPATH}" "${ACR_COMMAND[@]}"
  fi
)
ACR_EXIT_CODE=$?
set -e
if [ "$ACR_EXIT_CODE" -ne 0 ]; then
  update_wrapper_metadata "acr_failed" "$ACR_EXIT_CODE"
  exit "$ACR_EXIT_CODE"
fi

PATCH_FILE=""
if ! PATCH_FILE="$(
  "$PYTHON_BIN" - "$ACR_RUN_DIR" <<'PY'
import json
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])

def resolve_patch(selection_file: Path) -> Path | None:
    try:
        selected = json.loads(selection_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = selected.get("selected_patch")
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = selection_file.parent / path
    return path if path.is_file() else None

selection_files = sorted(
    run_dir.glob("**/selected_patch.json"),
    key=lambda path: path.stat().st_mtime,
    reverse=True,
)
for selection_file in selection_files:
    patch_path = resolve_patch(selection_file)
    if patch_path is not None:
        print(patch_path)
        raise SystemExit(0)

patch_files = sorted(
    run_dir.glob("**/extracted_patch_*.diff"),
    key=lambda path: path.stat().st_mtime,
    reverse=True,
)
for patch_path in patch_files:
    if patch_path.is_file() and patch_path.read_text(encoding="utf-8", errors="replace").strip():
        print(patch_path)
        raise SystemExit(0)

raise SystemExit(1)
PY
)"; then
  PATCH_FILE=""
fi

if [ -z "$PATCH_FILE" ]; then
  echo "AutoCodeRover completed but no selected patch was found under $ACR_RUN_DIR." >&2
  update_wrapper_metadata "patch_missing" "65"
  exit 65
fi

echo "Applying AutoCodeRover patch: $PATCH_FILE" >&2
set +e
git -C "$REPO" apply --whitespace=nowarn "$PATCH_FILE"
PATCH_APPLY_EXIT_CODE=$?
set -e
if [ "$PATCH_APPLY_EXIT_CODE" -ne 0 ]; then
  update_wrapper_metadata "patch_apply_failed" "$PATCH_APPLY_EXIT_CODE" "$PATCH_FILE"
  exit "$PATCH_APPLY_EXIT_CODE"
fi

update_wrapper_metadata "patch_applied" "0" "$PATCH_FILE"
