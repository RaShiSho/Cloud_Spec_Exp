from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
ADAPTER_DIR = REPO_ROOT / "baselines" / "metagpt"
sys.path.insert(0, str(ADAPTER_DIR))
from terminal_compat import (  # noqa: E402
    EXPECTED_MARKER,
    TerminalProcessEOF,
    install_terminal_compat,
)


class FakeStdout:
    def __init__(self, payload: bytes) -> None:
        self.payload = bytearray(payload)

    async def read(self, size: int) -> bytes:
        await asyncio.sleep(0)
        if not self.payload:
            return b""
        data = bytes(self.payload[:size])
        del self.payload[:size]
        return data


class FakeProcess:
    def __init__(self, payload: bytes, *, returncode: int | None = None) -> None:
        self.stdout = FakeStdout(payload)
        self.returncode = returncode


class FakeObserver:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def __aenter__(self) -> FakeObserver:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def async_report(self, value: str, name: str) -> None:
        self.events.append((name, value))


def fake_terminal_module(payload: bytes, *, returncode: int | None = None) -> Any:
    class FakeTerminal:
        def __init__(self) -> None:
            self.command_terminator = "\n"
            self.observer = FakeObserver()
            self.stdout_queue: asyncio.Queue[str] = asyncio.Queue()
            self.process = FakeProcess(payload, returncode=returncode)
            self.background_task: asyncio.Task[str] | None = None

        async def _read_and_process_output(
            self, cmd: str, daemon: bool = False
        ) -> str:
            raise AssertionError("vulnerable reader should be patched")

        async def run_command(self, cmd: str, daemon: bool = False) -> str:
            if daemon:
                self.background_task = asyncio.create_task(
                    self._read_and_process_output(cmd)
                )
                return ""
            return await self._read_and_process_output(cmd)

    return types.SimpleNamespace(
        END_MARKER_VALUE=EXPECTED_MARKER,
        DEFAULT_WORKSPACE_ROOT=Path("/upstream/workspace"),
        Terminal=FakeTerminal,
    )


class TerminalCompatTests(unittest.IsolatedAsyncioTestCase):
    async def test_marker_as_final_bytes_returns_without_an_extra_byte(self) -> None:
        module = fake_terminal_module(b"/tmp/workspace\n" + EXPECTED_MARKER.encode())
        details = install_terminal_compat(module)
        terminal = module.Terminal()

        output = await asyncio.wait_for(
            terminal.run_command("pwd"), timeout=1.0
        )

        self.assertEqual(output, "/tmp/workspace\n")
        self.assertEqual(details["status"], "applied")
        self.assertEqual(
            terminal.observer.events,
            [("cmd", "pwd\n"), ("output", "/tmp/workspace\n")],
        )

    async def test_output_without_trailing_newline_is_preserved(self) -> None:
        module = fake_terminal_module(b"alpha" + EXPECTED_MARKER.encode())
        install_terminal_compat(module)
        terminal = module.Terminal()

        output = await terminal.run_command("printf alpha")

        self.assertEqual(output, "alpha")
        self.assertEqual(terminal.observer.events[-1], ("output", "alpha"))

    async def test_carriage_return_progress_is_streamed(self) -> None:
        module = fake_terminal_module(b"10%\r20%\r" + EXPECTED_MARKER.encode())
        install_terminal_compat(module)
        terminal = module.Terminal()

        output = await terminal.run_command("progress")

        self.assertEqual(output, "10%\r20%\r")
        self.assertEqual(
            terminal.observer.events,
            [
                ("cmd", "progress\n"),
                ("output", "10%\r"),
                ("output", "20%\r"),
            ],
        )

    async def test_eof_before_marker_raises_instead_of_spinning(self) -> None:
        module = fake_terminal_module(b"partial", returncode=7)
        install_terminal_compat(module)
        terminal = module.Terminal()

        with self.assertRaisesRegex(TerminalProcessEOF, "returncode=7"):
            await asyncio.wait_for(terminal.run_command("broken"), timeout=1.0)

        self.assertEqual(terminal.observer.events[-1], ("output", "partial"))

    async def test_daemon_mode_forwards_output_to_stdout_queue(self) -> None:
        module = fake_terminal_module(b"background\n" + EXPECTED_MARKER.encode())
        install_terminal_compat(module)
        terminal = module.Terminal()

        self.assertEqual(await terminal.run_command("job", daemon=True), "")
        self.assertIsNotNone(terminal.background_task)
        await asyncio.wait_for(terminal.background_task, timeout=1.0)

        self.assertEqual(await terminal.stdout_queue.get(), "background\n")

    async def test_foreground_mode_does_not_fill_stdout_queue(self) -> None:
        module = fake_terminal_module(b"foreground\n" + EXPECTED_MARKER.encode())
        install_terminal_compat(module)
        terminal = module.Terminal()

        await terminal.run_command("job")

        self.assertTrue(terminal.stdout_queue.empty())

    async def test_install_is_idempotent(self) -> None:
        module = fake_terminal_module(EXPECTED_MARKER.encode())

        first = install_terminal_compat(module)
        second = install_terminal_compat(module)

        self.assertEqual(first["status"], "applied")
        self.assertEqual(second["status"], "already_applied")

    async def test_overrides_upstream_terminal_workspace(self) -> None:
        module = fake_terminal_module(EXPECTED_MARKER.encode())
        target = Path.cwd() / "target-worktree"

        details = install_terminal_compat(module, working_directory=target)

        self.assertEqual(module.DEFAULT_WORKSPACE_ROOT, target.resolve())
        self.assertTrue(details["workspace_root_override"])
        self.assertEqual(details["forced_working_directory"], str(target.resolve()))

    async def test_different_upstream_marker_is_not_patched(self) -> None:
        module = fake_terminal_module(b"")
        original = module.Terminal._read_and_process_output
        module.END_MARKER_VALUE = "__NEW_UPSTREAM_MARKER__"

        details = install_terminal_compat(module)

        self.assertEqual(details["status"], "not_applied")
        self.assertIs(module.Terminal._read_and_process_output, original)


if __name__ == "__main__":
    unittest.main()
