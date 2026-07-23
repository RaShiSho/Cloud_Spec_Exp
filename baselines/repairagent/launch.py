from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ADAPTER_DIR = Path(__file__).resolve().parent
PROJECT_NAME = "oci"
BUG_INDEX = "1"
CYCLE_INSTRUCTION = """Determine exactly one command to use based on the goals, the current state, and the progress made so far.
Respond with exactly one JSON object and no Markdown code fences or surrounding text. The object must have this shape:
{
  "thoughts": "Explain the relevant evidence, reasoning, and immediate next step.",
  "command": {
    "name": "Copy exactly one command name from the current state's Commands section.",
    "args": {}
  }
}
Use only commands listed for the current state. Use the exact argument names defined for the selected command, and include every required argument.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch RepairAgent with OCI-compatible tools.")
    parser.add_argument("--baseline-repo", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--test-command", required=True)
    parser.add_argument("--source-extensions", default="")
    parser.add_argument("--max-cycles", type=int, default=40)
    parser.add_argument("--test-timeout-seconds", type=int, default=600)
    parser.add_argument("--base-url", default="")
    return parser.parse_args()


def required_path(value: str, *, directory: bool) -> Path:
    path = Path(value).resolve()
    valid = path.is_dir() if directory else path.is_file()
    if not valid:
        kind = "directory" if directory else "file"
        raise FileNotFoundError(f"Required {kind} does not exist: {path}")
    return path


def git_revision(repo: Path) -> str | None:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    value = result.stdout.strip()
    return value or None


def git_diff(repo: Path) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repo}",
            "-C",
            str(repo),
            "diff",
            "HEAD",
            "--binary",
            "--no-ext-diff",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Unable to inspect target worktree: {result.stderr.strip()}")
    return result.stdout


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def prepare_run_layout(output_dir: Path, baseline_root: Path, task_file: Path) -> Path:
    run_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"
    run_dir = output_dir / "repairagent-runs" / run_name
    workspace = run_dir / "auto_gpt_workspace"
    (workspace / f"{PROJECT_NAME}_{BUG_INDEX}_buggy").mkdir(parents=True)
    experiment_dir = run_dir / "experimental_setups" / "experiment_1"
    for name in (
        "logs",
        "responses",
        "external_fixes",
        "saved_contexts",
        "mutations_history",
        "plausible_patches",
    ):
        (experiment_dir / name).mkdir(parents=True, exist_ok=True)
    (run_dir / "experimental_setups" / "experiments_list.txt").write_text(
        "experiment_1\n", encoding="utf-8"
    )
    (run_dir / "plugins").mkdir()

    role = (
        "You are RepairAgent adapted to repair OCI runtimes written in Go, C, or Rust. "
        "Use only the supplied commands. Inspect the issue and source, form a hypothesis, "
        "then apply line-oriented fixes. A successful build is necessary but the external "
        "OCI oracle remains the final authority."
    )
    goals = [
        f'Locate the Bug: systematically identify the bug within the project "{PROJECT_NAME}" and bug index "{BUG_INDEX}".',
        "Understand the OCI runtime behavior described in the task.",
        "Inspect only the candidate runtime worktree through the supplied tools.",
        "Propose and validate source changes without modifying the upstream RepairAgent checkout.",
        "Finish only after retaining a non-empty candidate patch.",
    ]
    ai_settings = "ai_goals:\n" + "".join(
        f"- {json.dumps(goal, ensure_ascii=False)}\n" for goal in goals
    )
    ai_settings += "ai_name: RepairAgent-OCI\nai_role: |\n  " + role.replace("\n", "\n  ") + "\napi_budget: 0.0\n"
    (run_dir / "ai_settings.yaml").write_text(ai_settings, encoding="utf-8")

    upstream_prompt = baseline_root / "prompt_settings.yaml"
    if upstream_prompt.is_file():
        shutil.copyfile(upstream_prompt, run_dir / "prompt_settings.yaml")
    else:
        (run_dir / "prompt_settings.yaml").write_text("constraints: []\nresources: []\nbest_practices: []\n", encoding="utf-8")

    states = {
        "collect information to understand the bug": (
            "## Current state\nCollect evidence from the OCI task and relevant runtime source, then express a concrete hypothesis."
        ),
        "collect information to fix the bug": (
            "## Current state\nSearch related Go/C/Rust code and read focused ranges needed to design a fix."
        ),
        "trying out candidate fixes": (
            "## Current state\nApply a focused candidate with write_fix. Failed builds are reverted; passing builds remain for the external oracle."
        ),
    }
    commands_by_state = {
        "collect information to understand the bug": "\n".join(
            (
                "1. extract_test_code: Read a repository reproduction/test file, or return the OCI task. Params: project_name, bug_index, test_file_path.",
                "2. read_range: Read numbered source lines. Params: project_name, bug_index, filepath, startline, endline.",
                "3. express_hypothesis: State a concrete root-cause hypothesis. Params: hypothesis.",
            )
        ),
        "collect information to fix the bug": "\n".join(
            (
                "1. search_code_base: Text-search configured source extensions. Params: project_name, bug_index, key_words.",
                "2. get_classes_and_methods: List function-like symbols in a file. Params: project_name, bug_index, file_path.",
                "3. extract_method_code: Read code around a named symbol. Params: project_name, bug_index, filepath, method_name.",
                "4. extract_similar_functions_calls: Search identifiers from a snippet. Params: project_name, bug_index, file_path, code_snippet.",
                "5. read_range: Read numbered source lines. Params: project_name, bug_index, filepath, startline, endline.",
                "6. write_fix: Apply and build a candidate. Params: project_name, bug_index, changes_dicts.",
            )
        ),
        "trying out candidate fixes": "\n".join(
            (
                "1. write_fix: Apply and build a candidate. Params: project_name, bug_index, changes_dicts.",
                "2. try_fixes: Try candidates and retain the first buildable one. Params: project_name, bug_index, fixes_list.",
                "3. read_range: Read numbered source lines. Params: project_name, bug_index, filepath, startline, endline.",
                "4. go_back_to_collect_more_info: Return to information gathering. Params: reason_for_going_back.",
                "5. discard_hypothesis: Return to bug understanding. Params: reason_for_discarding.",
                "6. goals_accomplished: Stop after a non-empty retained patch. Params: reason.",
            )
        ),
    }
    commands_interface = {
        "express_hypothesis": ["hypothesis"],
        "discard_hypothesis": ["reason_for_discarding"],
        "go_back_to_collect_more_info": ["reason_for_going_back"],
        "run_tests": ["project_name", "bug_index"],
        "read_range": ["project_name", "bug_index", "filepath", "startline", "endline"],
        "write_range": ["project_name", "bug_index", "changes_dicts"],
        "write_fix": ["project_name", "bug_index", "changes_dicts"],
        "get_classes_and_methods": ["project_name", "bug_index", "file_path"],
        "search_code_base": ["project_name", "bug_index", "key_words"],
        "extract_test_code": ["project_name", "bug_index", "test_file_path"],
        "extract_similar_functions_calls": ["project_name", "bug_index", "file_path", "code_snippet"],
        "extract_method_code": ["project_name", "bug_index", "filepath", "method_name"],
        "try_fixes": ["project_name", "bug_index", "fixes_list"],
    }
    write_json(run_dir / "states_description.json", states)
    write_json(run_dir / "commands_by_state.json", commands_by_state)
    write_json(run_dir / "commands_interface.json", commands_interface)
    write_json(
        run_dir / "hyperparams.json",
        {
            "budget_control": {"name": "FULL-TRACK", "params": {"#fixes": 1}},
            "repetition_handling": "RESTRICT",
            "external_fix_strategy": 0,
            "commands_limit": int(os.environ.get("REPAIRAGENT_OCI_MAX_CYCLES", "40")),
        },
    )
    (run_dir / "plugins_config.yaml").write_text("{}\n", encoding="utf-8")
    (run_dir / "cycle_instruction_text.txt").write_text(
        CYCLE_INSTRUCTION, encoding="utf-8"
    )
    (run_dir / "hints.txt").write_text(
        "Prefer minimal changes supported by the issue and inspected source.\n", encoding="utf-8"
    )
    (run_dir / "fix_format").write_text(
        """Use a JSON list with one dictionary per source file. Each dictionary has:
file_name (repository-relative path), insertions (line_number and new_lines),
deletions (one-based line numbers), and modifications (line_number and modified_line).
For every insertion, new_lines MUST be a JSON list of strings, with one complete
source line per list item. Do not return new_lines as one multiline string.
All line numbers refer to the file content shown by read_range.
Example: [{"file_name":"path/file.c","insertions":[{"line_number":10,
"new_lines":["first inserted line","second inserted line"]}],"deletions":[],
"modifications":[{"line_number":10,"modified_line":"new source line"}]}]
""",
        encoding="utf-8",
    )
    shutil.copyfile(task_file, run_dir / "task.md")
    return run_dir


def install_oci_tool_layer() -> None:
    import autogpt.commands
    import autogpt.commands.defects4j_static as static_tools

    import oci_tools

    autogpt.commands.COMMAND_CATEGORIES = [
        "autogpt.commands.system",
        "oci_commands",
        "autogpt.commands.states",
    ]
    static_tools.get_info = lambda name, index, workspace: (
        oci_tools.task_text() + "\n\nSource files:\n" + oci_tools.source_inventory()
    )
    static_tools.run_tests = lambda name, index, workspace: (
        (lambda result: ("0 failing tests.\n" if result[0] else "Validation failed.\n") + result[1])(
            oci_tools.run_validation()
        )
    )
    static_tools.create_fix_template = lambda name, index: (
        '[{"file_name":"path/to/source","insertions":[],"deletions":[],"modifications":[]}]'
    )
    static_tools.get_detailed_list_of_buggy_lines = lambda name, index: oci_tools.task_text()
    static_tools.query_for_mutants = lambda *args, **kwargs: "[]"


def run() -> int:
    args = parse_args()
    if args.max_cycles < 1 or args.test_timeout_seconds < 1:
        raise ValueError("--max-cycles and --test-timeout-seconds must be positive")
    baseline_repo = required_path(args.baseline_repo, directory=True)
    baseline_root = baseline_repo / "repair_agent"
    required_path(str(baseline_root / "autogpt" / "agents" / "base.py"), directory=False)
    repo = required_path(args.repo, directory=True)
    task_file = required_path(args.task_file, directory=False)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    initial_diff = git_diff(repo)
    if initial_diff:
        raise RuntimeError("RepairAgent requires a clean target worktree before launch")

    os.environ.update(
        {
            "REPAIRAGENT_OCI_REPO": str(repo),
            "REPAIRAGENT_OCI_TASK_FILE": str(task_file),
            "REPAIRAGENT_OCI_TEST_COMMAND": args.test_command,
            "REPAIRAGENT_OCI_SOURCE_EXTENSIONS": args.source_extensions,
            "REPAIRAGENT_OCI_TEST_TIMEOUT": str(args.test_timeout_seconds),
            "REPAIRAGENT_OCI_MAX_CYCLES": str(args.max_cycles),
            "TEMPERATURE": os.environ.get("REPAIRAGENT_TEMPERATURE", "0"),
            "CHAT_MESSAGES_ENABLED": "False",
            "PLAIN_OUTPUT": "True",
        }
    )
    if args.base_url:
        os.environ["OPENAI_API_BASE_URL"] = args.base_url

    run_dir = prepare_run_layout(output_dir, baseline_root, task_file)
    metadata_path = output_dir / "launcher_metadata.json"
    metadata = {
        "status": "starting",
        "baseline_revision": git_revision(baseline_repo),
        "baseline_root": str(baseline_root),
        "repo": str(repo),
        "task_file": str(task_file),
        "run_dir": str(run_dir),
        "model": args.model,
        "max_cycles": args.max_cycles,
        "test_command": args.test_command,
        "test_timeout_seconds": args.test_timeout_seconds,
        "source_extensions": args.source_extensions,
        "adapter_mode": "upstream_fsm_with_oci_tool_layer",
    }
    write_json(metadata_path, metadata)

    sys.path.insert(0, str(ADAPTER_DIR))
    sys.path.insert(0, str(baseline_root))
    previous_cwd = Path.cwd()
    try:
        os.chdir(run_dir)
        install_oci_tool_layer()
        from autogpt.app.main import run_auto_gpt

        try:
            run_auto_gpt(
                continuous=True,
                continuous_limit=args.max_cycles,
                ai_settings="ai_settings.yaml",
                prompt_settings="prompt_settings.yaml",
                skip_reprompt=True,
                speak=False,
                debug=False,
                gpt3only=False,
                gpt4only=False,
                memory_type="json_file",
                browser_name="",
                allow_downloads=False,
                skip_news=True,
                working_directory=run_dir,
                workspace_directory=run_dir / "auto_gpt_workspace",
                install_plugin_deps=False,
                experiment_file=str(run_dir / "hyperparams.json"),
                model=args.model,
            )
        except SystemExit as exc:
            if exc.code not in (None, 0):
                raise
    except Exception as exc:
        metadata.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        write_json(metadata_path, metadata)
        raise
    finally:
        os.chdir(previous_cwd)

    final_diff = git_diff(repo)
    if not final_diff:
        metadata.update({"status": "no_repository_changes", "patch_size_bytes": 0})
        write_json(metadata_path, metadata)
        return 65
    metadata.update(
        {
            "status": "completed",
            "patch_size_bytes": len(final_diff.encode("utf-8")),
        }
    )
    write_json(metadata_path, metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
