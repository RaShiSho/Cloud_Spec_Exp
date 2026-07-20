from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
ADAPTER_DIR = REPO_ROOT / "baselines" / "metagpt"
sys.path.insert(0, str(ADAPTER_DIR))
from command_compat import (  # noqa: E402
    InvalidMetaGPTCommand,
    get_command_compat_state,
    install_command_compat,
)


class MetaGPTCommandCompatTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_commands_pass_through(self) -> None:
        async def parse_commands(*args, **kwargs):
            return ([{"command_name": "end"}], True, kwargs["command_rsp"])

        module = types.SimpleNamespace(parse_commands=parse_commands)
        details = install_command_compat(module)

        result = await module.parse_commands(command_rsp="valid", llm=object())

        self.assertEqual(result, ([{"command_name": "end"}], True, "valid"))
        self.assertEqual(details["install_status"], "applied")
        self.assertEqual(get_command_compat_state()["invalid_response_count"], 0)

    async def test_missing_command_name_becomes_retry_feedback(self) -> None:
        async def parse_commands(*args, **kwargs):
            raise KeyError("command_name")

        module = types.SimpleNamespace(parse_commands=parse_commands)
        install_command_compat(module)

        message, ok, response = await module.parse_commands(
            command_rsp="{}", llm=object()
        )

        self.assertFalse(ok)
        self.assertEqual(response, "{}")
        self.assertIn("non-empty command_name", message)
        self.assertEqual(get_command_compat_state()["status"], "retrying")

    async def test_repeated_invalid_commands_fail_with_clear_error(self) -> None:
        async def parse_commands(*args, **kwargs):
            return ([{}], True, kwargs["command_rsp"])

        module = types.SimpleNamespace(parse_commands=parse_commands)
        install_command_compat(module)

        await module.parse_commands(command_rsp="{}", llm=object())
        await module.parse_commands(command_rsp="{}", llm=object())
        with self.assertRaisesRegex(InvalidMetaGPTCommand, "repeatedly returned"):
            await module.parse_commands(command_rsp="{}", llm=object())

        state = get_command_compat_state()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["invalid_response_count"], 3)


if __name__ == "__main__":
    unittest.main()
