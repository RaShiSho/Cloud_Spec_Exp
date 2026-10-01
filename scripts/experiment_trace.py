"""Small, append-only execution trace without prompts or credentials."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any


def trace_event(path: str | Path | None, event: str, **fields: Any) -> None:
    if not path:
        return
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        row = {"time": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(), "event": event, **fields}
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"execution trace unavailable: {type(exc).__name__}", file=sys.stderr, flush=True)


def trace_model_request(settings: dict[str, Any], params: dict[str, Any]) -> None:
    trace_event(
        os.environ.get("OCI_MODEL_EVENT_LOG"), "model_request",
        model=settings["model"], base_url=settings["base_url"],
        temperature=params.get("temperature"),
        token_limit_parameter=settings["token_limit_parameter"],
        token_limit=params.get(settings["token_limit_parameter"]),
        stream=bool(params.get("stream", False)),
        message_count=len(params.get("messages") or []),
    )
