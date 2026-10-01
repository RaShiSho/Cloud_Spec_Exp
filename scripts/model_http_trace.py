"""Observe modern OpenAI clients without changing their HTTP/retry behavior."""
from __future__ import annotations

import functools
import inspect
import os
import time
from typing import Any
import uuid

from experiment_trace import trace_event
from model_profiles import ResolvedProfile


def install_http_trace(http_client: Any, profile: ResolvedProfile) -> None:
    path = os.environ.get("OCI_MODEL_EVENT_LOG")
    if not path or getattr(http_client, "_oci_http_trace_installed", False):
        return
    http_client._oci_http_trace_installed = True
    client_id = uuid.uuid4().hex
    active: dict[int, dict[str, Any]] = {}
    sequence = 0

    def emit(event: str, state: dict[str, Any], **fields: Any) -> None:
        trace_event(
            path,
            event,
            client_id=client_id,
            request_id=state["request_id"],
            attempt=state["attempt"],
            sdk_retry_count=state["sdk_retry_count"],
            elapsed_seconds=round(time.monotonic() - state["started"], 6),
            **fields,
        )

    def begin(request: Any, stream: bool) -> dict[str, Any]:
        nonlocal sequence
        sequence += 1
        state = {
            "request_id": uuid.uuid4().hex,
            "attempt": sequence,
            "sdk_retry_count": request.headers.get("x-stainless-retry-count"),
            "started": time.monotonic(),
        }
        active[id(request)] = state
        emit(
            "model_http_request_started", state,
            method=request.method, endpoint_path=request.url.path,
            base_url=profile.settings["base_url"],
            request_bytes=request.headers.get("content-length"),
            timeout=request.extensions.get("timeout"),
            stream=stream,
        )
        return state

    def headers_received(response: Any) -> None:
        state = active.get(id(response.request))
        if state is None:
            return
        # Keep only diagnostic headers. Never log auth, cookies, or response bodies.
        headers = {
            name: profile.redact(response.headers[name])[:256]
            for name in (
                "x-request-id", "request-id", "x-correlation-id", "cf-ray",
                "server", "via", "retry-after", "content-type", "content-length",
            )
            if name in response.headers
        }
        emit("model_http_response_headers", state, status_code=response.status_code, headers=headers)

    def failed(state: dict[str, Any], error: Exception) -> None:
        chain = []
        seen: set[int] = set()
        current: BaseException | None = error
        while current is not None and id(current) not in seen and len(chain) < 8:
            seen.add(id(current))
            chain.append({
                "type": f"{type(current).__module__}.{type(current).__name__}",
                "message": profile.redact(str(current))[:1000],
            })
            current = current.__cause__ or (
                None if current.__suppress_context__ else current.__context__
            )
        emit("model_http_request_failed", state, exception_chain=chain)

    original_send = http_client.send
    if inspect.iscoroutinefunction(original_send):
        async def response_hook(response: Any) -> None:
            headers_received(response)

        @functools.wraps(original_send)
        async def send_async(request: Any, *args: Any, **kwargs: Any) -> Any:
            stream = bool(kwargs.get("stream", False))
            state = begin(request, stream)
            try:
                response = await original_send(request, *args, **kwargs)
                emit("model_http_request_finished", state, status_code=response.status_code, body_read=not stream)
                return response
            except Exception as error:
                failed(state, error)
                raise
            finally:
                active.pop(id(request), None)

        http_client.event_hooks["response"].append(response_hook)
        http_client.send = send_async
    else:
        @functools.wraps(original_send)
        def send(request: Any, *args: Any, **kwargs: Any) -> Any:
            stream = bool(kwargs.get("stream", False))
            state = begin(request, stream)
            try:
                response = original_send(request, *args, **kwargs)
                emit("model_http_request_finished", state, status_code=response.status_code, body_read=not stream)
                return response
            except Exception as error:
                failed(state, error)
                raise
            finally:
                active.pop(id(request), None)

        http_client.event_hooks["response"].append(headers_received)
        http_client.send = send
