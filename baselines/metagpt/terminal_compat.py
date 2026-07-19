"""Runtime compatibility fixes for affected MetaGPT Terminal revisions."""

from __future__ import annotations

import contextvars
import functools
from typing import Any


IMPLEMENTATION = "oci-metagpt-terminal-reader"
IMPLEMENTATION_VERSION = 1
EXPECTED_MARKER = "\x18\x19\x1b\x18\n"
_DAEMON_MODE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "metagpt_terminal_daemon_mode", default=False
)
_LINE_BREAK_BYTES = (
    b"\n",
    b"\r",
    b"\v",
    b"\f",
    b"\x1c",
    b"\x1d",
    b"\x1e",
    b"\x85",
)


class TerminalProcessEOF(RuntimeError):
    """Raised when the persistent shell closes before writing its end marker."""


async def _report_output(
    terminal: Any,
    observer: Any,
    payload: bytes,
    cmd_output: list[str],
    *,
    daemon: bool,
) -> None:
    if not payload:
        return
    text = payload.decode(errors="ignore")
    if not text:
        return
    await observer.async_report(text, "output")
    cmd_output.append(text)
    if daemon:
        await terminal.stdout_queue.put(text)


def install_terminal_compat(terminal_module: Any | None = None) -> dict[str, Any]:
    """Patch MetaGPT's marker reader without editing the upstream checkout."""

    if terminal_module is None:
        import metagpt.tools.libs.terminal as terminal_module

    terminal_class = terminal_module.Terminal
    marker = terminal_module.END_MARKER_VALUE
    marker_hex = marker.encode().hex()
    existing = getattr(terminal_class, "__oci_terminal_compat__", None)
    if existing:
        return {
            **existing,
            "status": "already_applied",
        }

    if marker != EXPECTED_MARKER:
        return {
            "implementation": IMPLEMENTATION,
            "implementation_version": IMPLEMENTATION_VERSION,
            "status": "not_applied",
            "reason": "unsupported upstream terminal marker protocol",
            "marker_hex": marker_hex,
            "patched_methods": [],
            "eof_detection": False,
            "daemon_queue_forwarding": False,
        }

    original_reader = terminal_class._read_and_process_output
    original_run_command = terminal_class.run_command

    @functools.wraps(original_reader)
    async def compatible_reader(self: Any, cmd: str, daemon: bool = False) -> str:
        effective_daemon = bool(daemon or _DAEMON_MODE.get())
        marker_bytes = terminal_module.END_MARKER_VALUE.encode()
        async with self.observer as observer:
            cmd_output: list[str] = []
            await observer.async_report(cmd + self.command_terminator, "cmd")
            pending = b""
            while True:
                chunk = await self.process.stdout.read(1)
                if not chunk:
                    await _report_output(
                        self,
                        observer,
                        pending,
                        cmd_output,
                        daemon=effective_daemon,
                    )
                    returncode = getattr(self.process, "returncode", None)
                    raise TerminalProcessEOF(
                        "MetaGPT terminal shell reached EOF before the end marker "
                        f"(returncode={returncode!r}, command={cmd!r})"
                    )

                pending += chunk
                marker_index = pending.find(marker_bytes)
                if marker_index >= 0:
                    await _report_output(
                        self,
                        observer,
                        pending[:marker_index],
                        cmd_output,
                        daemon=effective_daemon,
                    )
                    return "".join(cmd_output)

                if chunk in _LINE_BREAK_BYTES:
                    await _report_output(
                        self,
                        observer,
                        pending,
                        cmd_output,
                        daemon=effective_daemon,
                    )
                    pending = b""

    @functools.wraps(original_run_command)
    async def compatible_run_command(
        self: Any, cmd: str, daemon: bool = False
    ) -> str:
        token = _DAEMON_MODE.set(bool(daemon))
        try:
            return await original_run_command(self, cmd, daemon=daemon)
        finally:
            _DAEMON_MODE.reset(token)

    terminal_class._read_and_process_output = compatible_reader
    terminal_class.run_command = compatible_run_command
    details = {
        "implementation": IMPLEMENTATION,
        "implementation_version": IMPLEMENTATION_VERSION,
        "status": "applied",
        "reason": "newline-terminated marker can remain in the trailing buffer",
        "marker_hex": marker_hex,
        "patched_methods": [
            "Terminal._read_and_process_output",
            "Terminal.run_command",
        ],
        "eof_detection": True,
        "daemon_queue_forwarding": True,
    }
    terminal_class.__oci_terminal_compat__ = details
    return details.copy()
