from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ADAPTER_DIR = Path(__file__).resolve().parents[1] / "baselines" / "repairagent"
COMMANDS_PATH = ADAPTER_DIR / "oci_commands.py"
sys.path.insert(0, str(ADAPTER_DIR))


def load_oci_commands():
    autogpt = types.ModuleType("autogpt")
    autogpt.__path__ = []
    agents = types.ModuleType("autogpt.agents")
    agents.__path__ = []
    agent_module = types.ModuleType("autogpt.agents.agent")
    command_decorator = types.ModuleType("autogpt.command_decorator")

    class Agent:
        pass

    def command(*args, **kwargs):
        del args, kwargs

        def decorate(function):
            return function

        return decorate

    agent_module.Agent = Agent
    command_decorator.command = command
    modules = {
        "autogpt": autogpt,
        "autogpt.agents": agents,
        "autogpt.agents.agent": agent_module,
        "autogpt.command_decorator": command_decorator,
    }
    spec = importlib.util.spec_from_file_location(
        "repairagent_oci_commands_under_test",
        COMMANDS_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class RepairAgentOciCommandsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.commands = load_oci_commands()

    def test_write_fix_keeps_state_transition_marker_before_long_output(self) -> None:
        report = (
            "Candidate retained; build validation reports 0 failing tests. "
            "Behavioral correctness is pending the external OCI oracle.\n"
            + ("build-output\n" * 600)
        )
        with mock.patch.object(
            self.commands.oci_tools,
            "apply_and_validate",
            return_value=report,
        ):
            result = self.commands.write_fix("oci", 1, [], object())

        expected_marker = (
            "\n **Note:** You are automatically switched to the state "
            "'trying out candidate fixes'"
        )
        self.assertTrue(result.startswith(expected_marker))
        self.assertIn(expected_marker, result[:4000])
        self.assertGreater(len(result), 4000)
        self.assertIn("pending the external OCI oracle", result)


if __name__ == "__main__":
    unittest.main()
