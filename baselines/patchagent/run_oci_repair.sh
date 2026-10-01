#!/usr/bin/env bash
set -euo pipefail

BASELINE_REPO=""
REPO=""
TASK_FILE=""
OUTPUT_DIR=""
MODEL_CONFIG=""
BUILD_COMMAND=""
SOURCE_EXTENSIONS=""
TIMEOUT_SECONDS="0"
BUILD_TIMEOUT_SECONDS="600"
FAST="false"

usage() {
  cat >&2 <<'EOF'
Usage: run_oci_repair.sh --baseline-repo DIR --repo DIR --task-file FILE \
  --output-dir DIR --model-config FILE --build-command COMMAND [options]

Run upstream PatchAgent with the Cloud-Spec-Exp OCI builder.

Options:
  --source-extensions LIST    Comma-separated source suffixes.
  --timeout-seconds N         Stop the whole PatchAgent run after N seconds.
  --build-timeout-seconds N   Timeout for each candidate build.
  --fast                      One randomized upstream attempt (15 iterations).

Environment:
  PATCHAGENT_CONDA_ENV        Run with "conda run -n ENV python".
  PATCHAGENT_PYTHON           Otherwise use this Python executable.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --baseline-repo) BASELINE_REPO="${2:-}"; shift 2 ;;
    --repo) REPO="${2:-}"; shift 2 ;;
    --task-file) TASK_FILE="${2:-}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
    --model-config) MODEL_CONFIG="${2:-}"; shift 2 ;;
    --build-command) BUILD_COMMAND="${2:-}"; shift 2 ;;
    --source-extensions) SOURCE_EXTENSIONS="${2:-}"; shift 2 ;;
    --timeout-seconds) TIMEOUT_SECONDS="${2:-}"; shift 2 ;;
    --build-timeout-seconds) BUILD_TIMEOUT_SECONDS="${2:-}"; shift 2 ;;
    --fast) FAST="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

if [ -z "$BASELINE_REPO" ] || [ -z "$REPO" ] || [ -z "$TASK_FILE" ] || \
   [ -z "$OUTPUT_DIR" ] || [ -z "$MODEL_CONFIG" ] || [ -z "$BUILD_COMMAND" ]; then
  echo "Missing required argument." >&2
  usage
  exit 2
fi

for pair in "timeout-seconds:$TIMEOUT_SECONDS" "build-timeout-seconds:$BUILD_TIMEOUT_SECONDS"; do
  name="${pair%%:*}"
  value="${pair#*:}"
  case "$value" in
    ''|*[!0-9]*) echo "--$name must be a non-negative integer: $value" >&2; exit 2 ;;
  esac
done
if [ "$BUILD_TIMEOUT_SECONDS" -eq 0 ]; then
  echo "--build-timeout-seconds must be positive." >&2
  exit 2
fi

if [ ! -f "$BASELINE_REPO/patchagent/agent/generator.py" ]; then
  echo "Missing PatchAgent checkout: $BASELINE_REPO" >&2
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
mkdir -p "$OUTPUT_DIR"

initialize_submodules() {
  if [ ! -f "$REPO/.gitmodules" ]; then
    echo "Target worktree has no Git submodules." >&2
    return
  fi

  echo "Initializing target worktree submodules." >&2
  git -C "$REPO" submodule sync --recursive
  git -C "$REPO" submodule update --init --recursive

  local status
  status="$(git -C "$REPO" submodule status --recursive)"
  while IFS= read -r line; do
    case "$line" in
      -*) echo "Uninitialized submodule after update: $line" >&2; exit 2 ;;
      +*) echo "Submodule is not at the recorded revision: $line" >&2; exit 2 ;;
      U*) echo "Submodule has unresolved conflicts: $line" >&2; exit 2 ;;
    esac
  done <<< "$status"
  printf '%s\n' "$status" >&2
}

initialize_submodules

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Missing python3/python." >&2
  exit 2
fi

if [ -n "${PATCHAGENT_CONDA_ENV:-}" ]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "PATCHAGENT_CONDA_ENV is set, but conda is not available." >&2
    exit 2
  fi
  PYTHON_COMMAND=(conda run --no-capture-output -n "$PATCHAGENT_CONDA_ENV" python)
elif [ -n "${PATCHAGENT_PYTHON:-}" ]; then
  PYTHON_COMMAND=("$PATCHAGENT_PYTHON")
else
  PYTHON_COMMAND=("$PYTHON_BIN")
fi

if [ "$TIMEOUT_SECONDS" -gt 0 ] && ! command -v timeout >/dev/null 2>&1; then
  echo "--timeout-seconds requires GNU timeout on PATH." >&2
  exit 2
fi

COMMAND=(
  "${PYTHON_COMMAND[@]}" "$LAUNCHER"
  --baseline-repo "$BASELINE_REPO"
  --repo "$REPO"
  --task-file "$TASK_FILE"
  --output-dir "$OUTPUT_DIR"
  --model-config "$MODEL_CONFIG"
  --build-command "$BUILD_COMMAND"
  --source-extensions "$SOURCE_EXTENSIONS"
  --build-timeout-seconds "$BUILD_TIMEOUT_SECONDS"
)
if [ "$FAST" = "true" ]; then
  COMMAND+=(--fast)
fi

if [ "$TIMEOUT_SECONDS" -gt 0 ]; then
  timeout --signal=TERM --kill-after=30s "${TIMEOUT_SECONDS}s" "${COMMAND[@]}"
else
  "${COMMAND[@]}"
fi
