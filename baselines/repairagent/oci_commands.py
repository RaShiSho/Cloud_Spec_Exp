from __future__ import annotations

import re
from typing import Any

from autogpt.agents.agent import Agent
from autogpt.command_decorator import command

import oci_tools


COMMAND_CATEGORY = "oci_runtime"
COMMAND_CATEGORY_TITLE = "OCI Runtime Repair"


def _parameter(description: str, type_name: str = "string") -> dict[str, Any]:
    return {"type": type_name, "description": description, "required": True}


@command(
    "get_info",
    "Return the OCI issue description and a bounded source-file inventory.",
    {
        "project_name": _parameter("Compatibility project name."),
        "bug_index": _parameter("Compatibility bug index.", "integer"),
    },
)
def get_info(project_name: str, bug_index: int, agent: Agent) -> str:
    del project_name, bug_index, agent
    return oci_tools.task_text() + "\n\nSource files:\n" + oci_tools.source_inventory()


@command(
    "run_tests",
    "Run the configured OCI runtime build command against the current candidate.",
    {
        "project_name": _parameter("Compatibility project name."),
        "bug_index": _parameter("Compatibility bug index.", "integer"),
    },
)
def run_tests(project_name: str, bug_index: int, agent: Agent) -> str:
    del project_name, bug_index, agent
    passed, output = oci_tools.run_validation()
    status = "0 failing tests" if passed else "validation has failing tests or build errors"
    return f"{status}.\n{output}"


@command(
    "read_range",
    "Read an inclusive range of numbered lines from a source file.",
    {
        "project_name": _parameter("Compatibility project name."),
        "bug_index": _parameter("Compatibility bug index.", "integer"),
        "filepath": _parameter("Repository-relative source path."),
        "startline": _parameter("First line, one based.", "integer"),
        "endline": _parameter("Last line, inclusive.", "integer"),
    },
)
def read_range(
    project_name: str,
    bug_index: int,
    filepath: str,
    startline: int,
    endline: int,
    agent: Agent,
) -> str:
    del project_name, bug_index, agent
    return oci_tools.read_range(filepath, int(startline), int(endline))


@command(
    "search_code_base",
    "Search Go, C, header, or Rust source text for keywords and return file/line matches.",
    {
        "project_name": _parameter("Compatibility project name."),
        "bug_index": _parameter("Compatibility bug index.", "integer"),
        "key_words": _parameter("Keywords to search for.", "list"),
    },
)
def search_code_base(
    project_name: str,
    bug_index: int,
    key_words: list[str],
    agent: Agent,
) -> str:
    del project_name, bug_index, agent
    return oci_tools.search_code(key_words)


@command(
    "get_classes_and_methods",
    "List function-like symbols recognized by the language-neutral source scanner.",
    {
        "project_name": _parameter("Compatibility project name."),
        "bug_index": _parameter("Compatibility bug index.", "integer"),
        "file_path": _parameter("Repository-relative source path."),
    },
)
def get_classes_and_methods(
    project_name: str,
    bug_index: int,
    file_path: str,
    agent: Agent,
) -> str:
    del project_name, bug_index, agent
    return oci_tools.list_symbols(file_path)


@command(
    "extract_method_code",
    "Read a bounded source region surrounding a named function-like symbol.",
    {
        "project_name": _parameter("Compatibility project name."),
        "bug_index": _parameter("Compatibility bug index.", "integer"),
        "filepath": _parameter("Repository-relative source path."),
        "method_name": _parameter("Function or method name."),
    },
)
def extract_method_code(
    project_name: str,
    bug_index: int,
    filepath: str,
    method_name: str,
    agent: Agent,
) -> str:
    del project_name, bug_index, agent
    return oci_tools.extract_symbol(filepath, method_name)


@command(
    "extract_similar_functions_calls",
    "Search the source tree for identifiers found in a supplied code snippet.",
    {
        "project_name": _parameter("Compatibility project name."),
        "bug_index": _parameter("Compatibility bug index."),
        "file_path": _parameter("Repository-relative source path."),
        "code_snippet": _parameter("Code whose identifiers should be searched."),
    },
)
def extract_similar_functions_calls(
    project_name: str,
    bug_index: str,
    file_path: str,
    code_snippet: str,
    agent: Agent,
) -> str:
    del project_name, bug_index, file_path, agent
    identifiers = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", code_snippet)
    keywords = list(dict.fromkeys(identifiers))[:12]
    return oci_tools.search_code(keywords)


@command(
    "extract_test_code",
    "Read a source file named by the task, or return the OCI task when no file is available.",
    {
        "project_name": _parameter("Compatibility project name."),
        "bug_index": _parameter("Compatibility bug index."),
        "test_file_path": _parameter("Repository-relative test or reproduction file."),
    },
)
def extract_test_code(
    project_name: str,
    bug_index: str,
    test_file_path: str,
    agent: Agent,
) -> str:
    del project_name, bug_index, agent
    try:
        return oci_tools.read_range(test_file_path, 1, 400)
    except (FileNotFoundError, ValueError):
        return "The requested file is outside the runtime source tree; use this OCI task instead:\n" + oci_tools.task_text()


def _fix_parameters(argument_name: str) -> dict[str, Any]:
    return {
        "project_name": _parameter("Compatibility project name."),
        "bug_index": _parameter("Compatibility bug index.", "integer"),
        argument_name: _parameter("Line-oriented RepairAgent change dictionaries.", "list"),
    }


@command(
    "write_fix",
    "Apply line edits transactionally, run the runtime build, retain passing edits, and revert failing edits.",
    _fix_parameters("changes_dicts"),
)
def write_fix(
    project_name: str,
    bug_index: int,
    changes_dicts: list[dict[str, Any]],
    agent: Agent,
) -> str:
    del project_name, bug_index, agent
    return oci_tools.apply_and_validate(changes_dicts) + "\n **Note:** You are automatically switched to the state 'trying out candidate fixes'"


@command(
    "write_range",
    "Compatibility alias for write_fix.",
    _fix_parameters("changes_dicts"),
)
def write_range(
    project_name: str,
    bug_index: int,
    changes_dicts: list[dict[str, Any]],
    agent: Agent,
) -> str:
    return write_fix(project_name, bug_index, changes_dicts, agent)


@command(
    "try_fixes",
    "Try candidate fixes in order and retain the first one whose runtime build succeeds.",
    _fix_parameters("fixes_list"),
)
def try_fixes(
    project_name: str,
    bug_index: int,
    fixes_list: list[Any],
    agent: Agent,
) -> str:
    del project_name, bug_index, agent
    reports: list[str] = []
    for index, candidate in enumerate(fixes_list):
        changes = candidate.get("changes_dicts") if isinstance(candidate, dict) and "changes_dicts" in candidate else candidate
        if isinstance(changes, dict):
            changes = [changes]
        report = oci_tools.apply_and_validate(changes)
        reports.append(f"Fix {index}: {report}")
        if " 0 failing test" in report:
            return "A candidate passed and was retained.\n" + "\n".join(reports)
    return "No candidate passed; all attempted edits were reverted.\n" + "\n".join(reports)
