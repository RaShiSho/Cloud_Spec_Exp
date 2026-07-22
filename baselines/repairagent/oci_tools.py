from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".tox",
    ".venv",
    "node_modules",
    "target",
    "vendor",
}


def repository() -> Path:
    value = os.environ.get("REPAIRAGENT_OCI_REPO", "")
    if not value:
        raise RuntimeError("REPAIRAGENT_OCI_REPO is not configured")
    path = Path(value).resolve()
    if not path.is_dir():
        raise RuntimeError(f"OCI repository does not exist: {path}")
    return path


def task_text() -> str:
    value = os.environ.get("REPAIRAGENT_OCI_TASK_FILE", "")
    if not value:
        return "No OCI task description was supplied."
    path = Path(value).resolve()
    return path.read_text(encoding="utf-8", errors="replace")


def source_extensions() -> set[str]:
    raw = os.environ.get("REPAIRAGENT_OCI_SOURCE_EXTENSIONS", "")
    return {
        item if item.startswith(".") else f".{item}"
        for item in (part.strip() for part in raw.split(","))
        if item
    }


def resolve_repo_path(value: str | os.PathLike[str]) -> Path:
    root = repository()
    candidate = Path(value)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path escapes the OCI repository: {value}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"Source file does not exist: {value}")
    return resolved


def iter_source_files() -> Iterable[Path]:
    root = repository()
    extensions = source_extensions()
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
        current = Path(current_root)
        for filename in filenames:
            path = current / filename
            if extensions and path.suffix not in extensions:
                continue
            yield path


def source_inventory(limit: int = 200) -> str:
    root = repository()
    paths = [path.relative_to(root).as_posix() for path in iter_source_files()]
    paths.sort()
    selected = paths[:limit]
    suffix = f"\n... {len(paths) - limit} additional source files omitted" if len(paths) > limit else ""
    return "\n".join(selected) + suffix


def read_range(filepath: str, startline: int, endline: int) -> str:
    path = resolve_repo_path(filepath)
    if startline < 1 or endline < startline:
        raise ValueError("Expected 1 <= startline <= endline")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    selected = [f"Line {index}: {lines[index - 1]}" for index in range(startline, min(endline, len(lines)) + 1)]
    if endline > len(lines):
        selected.append("EOF")
    return "\n".join(selected)


def search_code(keywords: list[str], *, max_matches: int = 120) -> str:
    normalized = [str(keyword).strip().lower() for keyword in keywords if str(keyword).strip()]
    if not normalized:
        return "No non-empty search keywords were supplied."
    root = repository()
    matches: list[str] = []
    for path in iter_source_files():
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            lowered = line.lower()
            found = [keyword for keyword in normalized if keyword in lowered]
            if found:
                relative = path.relative_to(root).as_posix()
                excerpt = line.strip()
                if len(excerpt) > 240:
                    excerpt = excerpt[:237] + "..."
                matches.append(f"{relative}:{line_number}: [{', '.join(found)}] {excerpt}")
                if len(matches) >= max_matches:
                    return "\n".join(matches) + "\n... match limit reached"
    return "\n".join(matches) if matches else "No matches found."


_SYMBOL_PATTERNS = (
    re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(
        r"^\s*(?:[A-Za-z_][\w\s*]+\s+)+([A-Za-z_][A-Za-z0-9_]*)\s*\([^;]*\)\s*(?:\{|$)"
    ),
)


def list_symbols(filepath: str) -> str:
    path = resolve_repo_path(filepath)
    symbols: list[str] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        for pattern in _SYMBOL_PATTERNS:
            match = pattern.search(line)
            if match:
                symbols.append(f"{match.group(1)} (line {line_number})")
                break
    return "\n".join(symbols[:200]) if symbols else "No function-like symbols found by the language-neutral scanner."


def extract_symbol(filepath: str, method_name: str, *, context_lines: int = 80) -> str:
    path = resolve_repo_path(filepath)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    needle = re.compile(rf"\b{re.escape(method_name)}\b")
    for index, line in enumerate(lines):
        if needle.search(line):
            start = max(0, index - 5)
            end = min(len(lines), index + context_lines)
            return "\n".join(f"Line {number + 1}: {lines[number]}" for number in range(start, end))
    return f"Symbol not found in {filepath}: {method_name}"


def _normalize_new_line(value: Any) -> str:
    text = str(value)
    return text if text.endswith("\n") else text + "\n"


def apply_change_set(changes: list[dict[str, Any]]) -> dict[Path, str]:
    if not isinstance(changes, list) or not changes:
        raise ValueError("changes_dicts must be a non-empty list")
    originals: dict[Path, str] = {}
    try:
        for change in changes:
            if not isinstance(change, dict) or not change.get("file_name"):
                raise ValueError("Every change must contain file_name")
            path = resolve_repo_path(str(change["file_name"]))
            original = path.read_text(encoding="utf-8", errors="strict")
            originals.setdefault(path, original)
            lines = original.splitlines(keepends=True)

            deletions = {int(value) for value in change.get("deletions", [])}
            modifications = {
                int(item["line_number"]): _normalize_new_line(item.get("modified_line", ""))
                for item in change.get("modifications", [])
            }
            insertions: dict[int, list[str]] = {}
            for item in change.get("insertions", []):
                line_number = int(item["line_number"])
                insertions.setdefault(line_number, []).extend(
                    _normalize_new_line(value) for value in item.get("new_lines", [])
                )

            touched = deletions | set(modifications) | set(insertions)
            if any(line_number < 1 or line_number > len(lines) + 1 for line_number in touched):
                raise ValueError(f"Edit line outside 1..{len(lines) + 1} for {change['file_name']}")
            if deletions & set(modifications):
                raise ValueError(f"A line cannot be both deleted and modified: {change['file_name']}")

            output: list[str] = []
            for line_number in range(1, len(lines) + 2):
                output.extend(insertions.get(line_number, []))
                if line_number == len(lines) + 1:
                    continue
                if line_number in deletions:
                    continue
                output.append(modifications.get(line_number, lines[line_number - 1]))
            path.write_text("".join(output), encoding="utf-8", newline="")
    except Exception:
        restore_files(originals)
        raise
    return originals


def restore_files(originals: dict[Path, str]) -> None:
    for path, content in originals.items():
        path.write_text(content, encoding="utf-8", newline="")


def _git_dirty_paths() -> set[str]:
    root = repository()
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={root}",
            "-C",
            str(root),
            "diff",
            "HEAD",
            "--name-only",
            "--no-ext-diff",
            "--",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _restore_build_side_effects(preexisting_dirty: set[str]) -> None:
    root = repository()
    for relative in sorted(_git_dirty_paths() - preexisting_dirty):
        result = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={root}",
                "-C",
                str(root),
                "show",
                f"HEAD:{relative}",
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            continue
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(result.stdout)


def run_validation() -> tuple[bool, str]:
    command = os.environ.get("REPAIRAGENT_OCI_TEST_COMMAND", "").strip()
    if not command:
        return True, "No adapter test command was configured."
    timeout = int(os.environ.get("REPAIRAGENT_OCI_TEST_TIMEOUT", "600"))
    preexisting_dirty = _git_dirty_paths()
    try:
        result = subprocess.run(
            command,
            cwd=repository(),
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(part for part in (exc.stdout or "", exc.stderr or "") if part)
        _restore_build_side_effects(preexisting_dirty)
        return False, f"Validation timed out after {timeout}s.\n{output[-6000:]}"
    _restore_build_side_effects(preexisting_dirty)
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if len(output) > 6000:
        output = output[-6000:]
    return result.returncode == 0, f"returncode={result.returncode}\n{output}"


def apply_and_validate(changes: list[dict[str, Any]]) -> str:
    originals: dict[Path, str] = {}
    try:
        originals = apply_change_set(changes)
        passed, output = run_validation()
    except Exception:
        if originals:
            restore_files(originals)
        raise
    if not passed:
        restore_files(originals)
        return "Candidate rejected and reverted; validation has failing tests or build errors.\n" + output
    return "Candidate retained; validation reports 0 failing tests.\n" + output
