#!/usr/bin/env python3
"""Run upstream PatchAgent against an OCI runtime worktree.

PatchAgent's public builders target OSS-Fuzz C/C++ and Jazzer Java projects.
This adapter supplies the same PatchTask/agent workflow with an OCI-oriented
builder. Candidate patches are build-checked internally and the experiment
runner performs the authoritative OCI oracle after this launcher returns.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from functools import cached_property
from pathlib import Path
from typing import Any, Iterable


IGNORED_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "target",
    "third_party",
    "vendor",
}
MAX_INDEXED_FILE_BYTES = 1_048_576
NO_CHANGES_EXIT_CODE = 65


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch PatchAgent with an OCI-compatible builder."
    )
    parser.add_argument("--baseline-repo", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--build-command", required=True)
    parser.add_argument("--source-extensions", default="")
    parser.add_argument("--build-timeout-seconds", type=int, default=600)
    parser.add_argument("--base-url")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use upstream's one-attempt, 15-iteration fast generator.",
    )
    return parser.parse_args()


def required_path(value: str, *, directory: bool) -> Path:
    path = Path(value).resolve()
    valid = path.is_dir() if directory else path.is_file()
    if not valid:
        kind = "directory" if directory else "file"
        raise FileNotFoundError(f"Required {kind} does not exist: {path}")
    return path


def parse_source_extensions(value: str) -> tuple[str, ...]:
    extensions: list[str] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        extension = item if item.startswith(".") else f".{item}"
        if extension not in extensions:
            extensions.append(extension)
    return tuple(extensions)


def iter_source_files(root: Path, extensions: tuple[str, ...]) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or (extensions and path.suffix not in extensions):
            continue
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        try:
            if path.stat().st_size > MAX_INDEXED_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


def locate_symbol_text(
    root: Path,
    symbol: str,
    extensions: tuple[str, ...],
    *,
    limit: int = 20,
) -> list[str]:
    """Return likely language-independent symbol definitions."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_:$.-]*", symbol):
        return []
    token = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])")
    definition = re.compile(
        rf"(?:\bfunc\b.*|\bfn\b|\b(?:struct|enum|union|type|const|static)\b.*|"
        rf"[A-Za-z_][A-Za-z0-9_\s:*<>,\[\]]+)\b{re.escape(symbol)}\s*(?:\(|\{{|=|;)"
    )
    likely: list[str] = []
    fallback: list[str] = []
    for path in iter_source_files(root, extensions):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        for line_number, line in enumerate(lines, 1):
            if not token.search(line):
                continue
            location = f"{relative}:{line_number}"
            (likely if definition.search(line) else fallback).append(location)
            if len(likely) >= limit:
                return likely[:limit]
    return (likely + fallback)[:limit]


def git_revision(repo: Path) -> str | None:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.stdout.strip() or None


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
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Unable to inspect target repository: {result.stderr.strip()}")
    return result.stdout


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def remove_nested_git_metadata(root: Path) -> list[str]:
    """Remove copied Git control files while preserving materialized sources."""
    root = root.resolve()
    candidates = {path for path in root.rglob(".git")}
    root_dot_git = root / ".git"
    if root_dot_git.exists() or root_dot_git.is_symlink():
        candidates.add(root_dot_git)

    removed: list[str] = []
    for path in sorted(candidates, key=lambda item: len(item.parts), reverse=True):
        try:
            relative = path.resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise RuntimeError(
                f"Refusing to remove Git metadata outside isolated workspace: {path}"
            ) from exc

        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        else:
            continue
        removed.append(relative.as_posix())
    return sorted(removed)


def configure_openai_environment(base_url: str | None) -> tuple[str, str]:
    key_source = ""
    for name in ("PATCHAGENT_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        value = os.environ.get(name)
        if value:
            os.environ["OPENAI_API_KEY"] = value
            key_source = name
            break
    if not key_source:
        raise RuntimeError(
            "Missing API key: set PATCHAGENT_API_KEY, DEEPSEEK_API_KEY, "
            "or OPENAI_API_KEY."
        )

    resolved_base_url = (
        base_url
        or os.environ.get("PATCHAGENT_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or "https://api.deepseek.com"
    )
    os.environ["OPENAI_BASE_URL"] = resolved_base_url
    return key_source, resolved_base_url


def apply_patch_to_target(repo: Path, patch: str) -> None:
    encoded = patch.encode("utf-8")
    check = subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo), "apply", "--check"],
        input=encoded,
        capture_output=True,
        check=False,
    )
    if check.returncode != 0:
        raise RuntimeError(
            "PatchAgent patch does not apply to the target worktree: "
            + check.stderr.decode("utf-8", errors="replace").strip()
        )
    applied = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repo}",
            "-C",
            str(repo),
            "apply",
            "--whitespace=nowarn",
        ],
        input=encoded,
        capture_output=True,
        check=False,
    )
    if applied.returncode != 0:
        raise RuntimeError(
            "Unable to apply PatchAgent patch: "
            + applied.stderr.decode("utf-8", errors="replace").strip()
        )


def main() -> int:
    args = parse_args()
    if args.build_timeout_seconds < 1:
        raise ValueError("--build-timeout-seconds must be positive")

    baseline_repo = required_path(args.baseline_repo, directory=True)
    required_path(
        str(baseline_repo / "patchagent" / "agent" / "generator.py"), directory=False
    )
    repo = required_path(args.repo, directory=True)
    task_file = required_path(args.task_file, directory=False)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / "launcher_metadata.json"

    if git_diff(repo):
        raise RuntimeError("PatchAgent requires a clean target worktree before launch")

    key_source, base_url = configure_openai_environment(args.base_url)
    extensions = parse_source_extensions(args.source_extensions)
    task_text = task_file.read_text(encoding="utf-8", errors="replace")
    workspace = output_dir / "workspace"

    sys.path.insert(0, str(baseline_repo))
    from patchagent.agent.generator import agent_generator
    from patchagent.agent.clike import common as clike_common
    from patchagent.builder import Builder, PoC
    from patchagent.builder.utils import safe_subprocess_run
    from patchagent.lang import Lang
    from patchagent.lsp.language import LanguageServer
    from patchagent.parser.cwe import CWE
    from patchagent.parser.sanitizer import Sanitizer, SanitizerReport
    from patchagent.task import PatchTask, ValidationResult
    from git import Repo
    from langchain_core.tools import StructuredTool

    class OCIPoC(PoC):
        pass

    class OCITaskReport(SanitizerReport):
        def __init__(self, content: str):
            super().__init__(Sanitizer.UnknownSanitizer, content, CWE.UNKNOWN, [])

    class OCITextLanguageServer(LanguageServer):
        def locate_symbol(self, symbol: str) -> list[str]:
            return locate_symbol_text(self.source_path, symbol, extensions)

        def find_definition(self, path: Path, line: int, column: int) -> list[str]:
            return []

        def hover(self, path: Path, line: int, column: int) -> None:
            return None

    class OCIBuilder(Builder):
        def __init__(self) -> None:
            self.removed_git_metadata: list[str] = []
            super().__init__(
                project=repo.name,
                source_path=repo,
                workspace=workspace,
                clean_up=True,
            )

        @cached_property
        def language(self) -> Lang:
            return Lang.CLIKE

        @cached_property
        def language_server(self) -> LanguageServer:
            return OCITextLanguageServer(self.source_path)

        @cached_property
        def source_repo(self) -> Repo:
            """Create an isolated repo even when the input is a linked worktree."""
            target_path = self.workspace / "git" / self.org_source_path.name
            if not target_path.is_dir():
                shutil.copytree(self.source_path, target_path, symlinks=True)

            self.removed_git_metadata = remove_nested_git_metadata(target_path)

            source_repo = Repo.init(target_path)
            if not source_repo.head.is_valid():
                source_repo.git.add("--all")
                source_repo.index.commit("Initial commit")
            return source_repo

        def _prepare(self, patch: str) -> Path:
            source_repo = self.source_repo
            source_repo.git.reset("--hard")
            source_repo.git.clean("-fdx")
            source_path = Path(source_repo.working_dir)
            if patch:
                safe_subprocess_run(
                    ["git", "apply"], source_path, input=patch.encode("utf-8")
                )
            return source_path

        def build(self, patch: str = "") -> None:
            source_path = self._prepare(patch)
            safe_subprocess_run(
                ["bash", "-lc", args.build_command],
                source_path,
                timeout=args.build_timeout_seconds,
                env=os.environ.copy(),
            )

        def replay(self, poc: PoC, patch: str = "") -> SanitizerReport | None:
            if patch:
                return None
            return OCITaskReport(task_text)

        def function_test(self, patch: str = "") -> None:
            # build() has already validated compilation. The runner invokes the
            # differential OCI oracle after the selected patch is applied.
            return None

    def create_oci_locate_tool(
        task: PatchTask, auto_hint: bool = False
    ) -> StructuredTool:
        """Avoid upstream's libclang fallback for unsupported Go/Rust input."""

        def locate(symbol: str) -> str:
            """Return likely source definitions of a symbol."""
            locations = task.builder.language_server.locate_symbol(symbol)
            args_payload = {"symbol": symbol}
            if locations:
                result_payload = (
                    f"Here is the location of the symbol {symbol}:\n"
                    + "\n".join(locations)
                )
            else:
                result_payload = (
                    f"Sorry, we cannot locate the symbol {symbol} in the "
                    "configured OCI source files."
                )
            task.current_context.add_tool_call(
                "locate", args_payload, result_payload
            )
            return result_payload

        return StructuredTool.from_function(locate)

    # CommonCLikeAgent imported create_locate_tool into its module namespace.
    # Replace that binding, not upstream files, so C/Go/Rust all use the
    # adapter's deterministic text index and never enter the C-only clang AST
    # fallback. viewcode and validate remain upstream implementations.
    clike_common.create_locate_tool = create_oci_locate_tool

    metadata: dict[str, Any] = {
        "status": "starting",
        "baseline_repo": str(baseline_repo),
        "baseline_revision": git_revision(baseline_repo),
        "repo": str(repo),
        "task_file": str(task_file),
        "model": args.model,
        "base_url": base_url,
        "api_key_source": key_source,
        "build_command": args.build_command,
        "build_timeout_seconds": args.build_timeout_seconds,
        "source_extensions": list(extensions),
        "fast": args.fast,
        "adapter_mode": "upstream_agent_with_oci_builder",
        "internal_validation": "patch_format_and_build",
        "behavior_validation": "deferred_to_runner_oci_oracle",
    }
    write_json(metadata_path, metadata)

    patch_task = PatchTask(
        [OCIPoC()],
        OCIBuilder(),
        log_file=output_dir / "trajectory.json",
    )
    result, report = patch_task.initialize()
    metadata["removed_git_metadata"] = patch_task.builder.removed_git_metadata
    if result != ValidationResult.BugDetected:
        metadata.update(
            {
                "status": "initialization_failed",
                "initialization_result": result.value,
                "initialization_report": report,
            }
        )
        write_json(metadata_path, metadata)
        print(
            f"PatchAgent initialization failed ({result.value}):\n{report}",
            file=sys.stderr,
        )
        return 2

    try:
        patch = patch_task.repair(agent_generator(model=args.model, fast=args.fast))
        if not patch or not patch.strip():
            metadata.update({"status": "no_patch", "patch_size_bytes": 0})
            write_json(metadata_path, metadata)
            return NO_CHANGES_EXIT_CODE

        patch_path = output_dir / "generated_patch.diff"
        patch_path.write_text(patch, encoding="utf-8")
        apply_patch_to_target(repo, patch)
        final_diff = git_diff(repo)
        if not final_diff:
            metadata.update({"status": "no_repository_changes", "patch_size_bytes": 0})
            write_json(metadata_path, metadata)
            return NO_CHANGES_EXIT_CODE
    except Exception as exc:
        metadata.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        write_json(metadata_path, metadata)
        raise

    metadata.update(
        {
            "status": "completed",
            "patch_file": str(patch_path),
            "patch_size_bytes": len(final_diff.encode("utf-8")),
            "attempts": len(patch_task.contexts),
        }
    )
    write_json(metadata_path, metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
