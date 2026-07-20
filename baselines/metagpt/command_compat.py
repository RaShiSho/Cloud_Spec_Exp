"""Compatibility guard for malformed MetaGPT RoleZero command responses."""

from __future__ import annotations

import functools
import sys
from typing import Any


IMPLEMENTATION = "oci-metagpt-role-zero-command-guard"
IMPLEMENTATION_VERSION = 1
MAX_INVALID_COMMAND_RETRIES = 2
_ACTIVE_STATE: dict[str, Any] | None = None


class InvalidMetaGPTCommand(RuntimeError):
    """Raised after repeated malformed RoleZero command responses."""


def _command_response(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    value = kwargs.get("command_rsp", args[0] if args else "")
    return value if isinstance(value, str) else str(value)


def _invalid_reason(result: Any) -> str | None:
    if not isinstance(result, tuple) or len(result) != 3:
        return "parse_commands returned an invalid result shape"
    commands, ok, _ = result
    if not ok:
        return None
    if not isinstance(commands, list) or not commands:
        return "the model returned no commands"
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            return f"command {index} is not a JSON object"
        name = command.get("command_name")
        if not isinstance(name, str) or not name.strip():
            return f"command {index} has no non-empty command_name"
    return None


def _retry_or_raise(
    state: dict[str, Any],
    *,
    reason: str,
    command_rsp: str,
) -> tuple[str, bool, str]:
    state["invalid_response_count"] += 1
    state["last_error"] = reason
    count = state["invalid_response_count"]
    if count > state["max_invalid_command_retries"]:
        state["status"] = "failed"
        raise InvalidMetaGPTCommand(
            "MetaGPT repeatedly returned malformed RoleZero commands "
            f"({count} invalid responses): {reason}"
        )

    state["status"] = "retrying"
    message = (
        "The previous tool response was rejected because "
        f"{reason}. Return a fenced JSON array of command objects. Every object "
        "must contain a non-empty command_name and the appropriate args object; "
        "do not return an empty response or {}."
    )
    return message, False, command_rsp


def install_command_compat(utils_module: Any | None = None) -> dict[str, Any]:
    """Validate RoleZero commands and turn malformed output into bounded retries."""

    global _ACTIVE_STATE

    if utils_module is None:
        import metagpt.utils.role_zero_utils as utils_module

    existing = getattr(utils_module, "__oci_command_compat__", None)
    if existing:
        _ACTIVE_STATE = existing
        role_zero_module = sys.modules.get("metagpt.roles.di.role_zero")
        if role_zero_module is not None:
            role_zero_module.parse_commands = utils_module.parse_commands
        return {**existing, "install_status": "already_applied"}

    original_parse_commands = utils_module.parse_commands
    state: dict[str, Any] = {
        "implementation": IMPLEMENTATION,
        "implementation_version": IMPLEMENTATION_VERSION,
        "install_status": "applied",
        "status": "applied",
        "invalid_response_count": 0,
        "max_invalid_command_retries": MAX_INVALID_COMMAND_RETRIES,
        "last_error": None,
    }

    @functools.wraps(original_parse_commands)
    async def compatible_parse_commands(*args: Any, **kwargs: Any) -> Any:
        command_rsp = _command_response(args, kwargs)
        try:
            result = await original_parse_commands(*args, **kwargs)
        except KeyError as exc:
            if exc.args != ("command_name",):
                raise
            return _retry_or_raise(
                state,
                reason="a command object has no command_name",
                command_rsp=command_rsp,
            )

        reason = _invalid_reason(result)
        if reason is not None:
            return _retry_or_raise(
                state,
                reason=reason,
                command_rsp=command_rsp,
            )

        if state["invalid_response_count"]:
            state["status"] = "recovered"
        return result

    utils_module.parse_commands = compatible_parse_commands
    utils_module.__oci_command_compat__ = state
    role_zero_module = sys.modules.get("metagpt.roles.di.role_zero")
    if role_zero_module is not None:
        role_zero_module.parse_commands = compatible_parse_commands
    _ACTIVE_STATE = state
    return state.copy()


def get_command_compat_state() -> dict[str, Any]:
    """Return a JSON-serializable snapshot for launcher metadata."""

    if _ACTIVE_STATE is None:
        return {
            "implementation": IMPLEMENTATION,
            "implementation_version": IMPLEMENTATION_VERSION,
            "install_status": "not_installed",
            "status": "not_installed",
            "invalid_response_count": 0,
            "max_invalid_command_retries": MAX_INVALID_COMMAND_RETRIES,
            "last_error": None,
        }
    return _ACTIVE_STATE.copy()
