#!/usr/bin/env bash
set -euo pipefail

BASELINE_NAME="autocoderover"
BASELINE_REPO=""
REPO=""
TASK_FILE=""
OUTPUT_DIR=""
MODEL=""

usage() {
  cat >&2 <<'EOF'
Usage: run_oci_repair.sh --baseline-repo DIR --repo DIR --task-file FILE --output-dir DIR --model MODEL

This is a Cloud-Spec-Exp OCI adapter skeleton for AutoCodeRover.
It invokes AutoCodeRover upstream local-issue mode and applies the selected
patch back to the OCI worktree so the experiment runner can collect git diff.
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
if [ ! -f "$BASELINE_REPO/app/main.py" ]; then
  echo "Missing AutoCodeRover entrypoint: $BASELINE_REPO/app/main.py" >&2
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

ACR_RUN_DIR="$OUTPUT_DIR/acr-run"
ACR_MODEL_NAME="${ACR_MODEL:-$MODEL}"
ACR_MODEL_TEMPERATURE="${ACR_MODEL_TEMPERATURE:-0}"
ACR_TASK_ID="${ACR_TASK_ID:-$(basename "$(dirname "$TASK_FILE")")}"
mkdir -p "$ACR_RUN_DIR"

"$PYTHON_BIN" - "$BASELINE_NAME" "$BASELINE_REPO" "$REPO" "$TASK_FILE" "$OUTPUT_DIR" "$MODEL" "$ACR_MODEL_NAME" "$ACR_MODEL_TEMPERATURE" "$ACR_TASK_ID" "$(pwd)" <<'PY'
import json
import sys
from pathlib import Path

baseline, baseline_repo, repo, task_file, output_dir, model, acr_model, acr_temperature, acr_task_id, cwd = sys.argv[1:]
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
    "cwd": cwd,
    "adapter_status": "starting",
}
Path(output_dir, "wrapper_metadata.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

if [ -z "${ACR_MODEL:-}" ] && [[ "$ACR_MODEL_NAME" == */* ]]; then
  echo "Warning: AutoCodeRover may reject model '$ACR_MODEL_NAME'. Set ACR_MODEL to an upstream-supported model if needed." >&2
fi

echo "Starting AutoCodeRover local-issue mode." >&2
(
  cd "$BASELINE_REPO"
  if [ -z "${OPENAI_KEY:-}" ] && [ -n "${OPENAI_API_KEY:-}" ]; then
    export OPENAI_KEY="$OPENAI_API_KEY"
  fi
  PYTHONPATH="$BASELINE_REPO${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" app/main.py local-issue \
    --output-dir "$ACR_RUN_DIR" \
    --model "$ACR_MODEL_NAME" \
    --model-temperature "$ACR_MODEL_TEMPERATURE" \
    --task-id "$ACR_TASK_ID" \
    --local-repo "$REPO" \
    --issue-file "$TASK_FILE"
)

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
  exit 65
fi

echo "Applying AutoCodeRover patch: $PATCH_FILE" >&2
git -C "$REPO" apply --whitespace=nowarn "$PATCH_FILE"

"$PYTHON_BIN" - "$OUTPUT_DIR" "$PATCH_FILE" <<'PY'
import json
import sys
from pathlib import Path

output_dir, patch_file = sys.argv[1:]
path = Path(output_dir, "wrapper_metadata.json")
payload = json.loads(path.read_text(encoding="utf-8"))
payload["adapter_status"] = "patch_applied"
payload["selected_patch"] = patch_file
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
