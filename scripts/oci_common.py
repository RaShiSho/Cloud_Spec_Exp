from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only on minimal hosts.
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[1]
GARBLE_MARKERS = ("?" * 4, chr(0xFFFD), chr(0x6769), chr(0x9418), chr(0x95BF))
REQUIRED_CASE_FILES = (
    "base_config.json",
    "buggy_config.json",
    "repro.sh",
    "expected_diff.txt",
    "README.md",
)
DEFAULT_EXTENSIONS = {
    "runc": [".go"],
    "crun": [".c", ".h"],
    "youki": [".rs"],
}
IGNORED_FILE_PARTS = {
    ".git",
    "vendor",
    "node_modules",
    "target",
    "build",
    "dist",
    ".cache",
    "__pycache__",
}


def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_double:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            if index == 0 or value[index - 1].isspace():
                return value[:index]
    return value


def _parse_dotenv_value(raw_value: str) -> str:
    value = _strip_inline_comment(raw_value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
        if raw_value.strip().startswith('"'):
            value = value.encode("utf-8").decode("unicode_escape")
    return value


def load_dotenv(path: str | Path | None = None, override: bool = False) -> dict[str, str]:
    dotenv_path = Path(path) if path is not None else REPO_ROOT / ".env"
    if not dotenv_path.exists():
        return {}

    loaded: dict[str, str] = {}
    with dotenv_path.open("r", encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].lstrip()
            if "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            key = key.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError(f"Invalid .env key at {dotenv_path}:{line_number}: {key}")
            if key in os.environ and not override:
                continue
            value = _parse_dotenv_value(raw_value)
            os.environ[key] = value
            loaded[key] = value
    return loaded


@dataclass
class CommandResult:
    command: str | list[str]
    cwd: str | None
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "error": self.error,
        }


def load_config(path: str | Path) -> dict[str, Any]:
    load_dotenv()
    if yaml is None:
        raise RuntimeError("PyYAML is required to read YAML config files: pip install PyYAML")
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a YAML mapping: {path}")
    return data


def resolve_path(value: str | Path | None, root: Path = REPO_ROOT) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return root / path


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def ensure_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def write_text(path: Path, text: str | bytes | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ensure_text(text), encoding="utf-8", newline="\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def shell_quote(value: Any) -> str:
    return shlex.quote(str(value))


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def executable_exists(value: str | None, cwd: Path | None = None) -> bool:
    if not value:
        return False
    path = Path(value)
    if path.is_absolute():
        return path.exists()
    if cwd is not None and (cwd / path).exists():
        return True
    return shutil.which(value) is not None


def run_command(
    command: str | list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
    shell: bool | None = None,
) -> CommandResult:
    use_shell = isinstance(command, str) if shell is None else shell
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            timeout=timeout,
            shell=use_shell,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        return CommandResult(
            command=command,
            cwd=str(cwd) if cwd else None,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=command,
            cwd=str(cwd) if cwd else None,
            returncode=124,
            stdout=ensure_text(exc.stdout),
            stderr=ensure_text(exc.stderr),
            timed_out=True,
            error=f"timeout after {timeout}s",
        )
    except OSError as exc:
        return CommandResult(
            command=command,
            cwd=str(cwd) if cwd else None,
            returncode=127,
            stdout="",
            stderr=str(exc),
            error=str(exc),
        )


def case_runtime(case_id: str) -> str:
    return case_id.split("-", 1)[0]


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "item"


def configured_buggy_ref_case_ids(config: dict[str, Any]) -> set[str]:
    """Return case ids that have a non-empty per-case buggy revision."""
    case_ids: set[str] = set()
    for runtime_cfg in config.get("runtimes", {}).values():
        if not isinstance(runtime_cfg, dict):
            continue
        by_case = runtime_cfg.get("buggy_ref_by_case") or runtime_cfg.get("buggy_refs") or {}
        if isinstance(by_case, dict):
            case_ids.update(str(case_id) for case_id, ref in by_case.items() if ref)
        elif isinstance(by_case, list):
            case_ids.update(str(case_id) for case_id in by_case if case_id)
    return case_ids


def load_oci_cases(config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    benchmark = config.get("benchmark", {})
    metadata_file = resolve_path(benchmark.get("metadata_file"))
    cases_dir = resolve_path(benchmark.get("cases_dir"))
    problems: list[str] = []
    if metadata_file is None or not metadata_file.exists():
        return [], [f"missing metadata_file: {metadata_file}"]
    if cases_dir is None or not cases_dir.exists():
        problems.append(f"missing cases_dir: {cases_dir}")

    with metadata_file.open("r", encoding="utf-8") as f:
        metadata = json.load(f)
    if not isinstance(metadata, list):
        raise ValueError(f"metadata.json must be a JSON array: {metadata_file}")

    selection = benchmark.get("selection", {})
    mode = selection.get("mode", "first_n")
    if mode == "all":
        selected_metadata = metadata
    elif mode == "first_n":
        count = int(selection.get("count", 20))
        selected_metadata = metadata[:count]
    elif mode == "buggy_refs":
        configured_case_ids = configured_buggy_ref_case_ids(config)
        selected_metadata = [
            entry for entry in metadata if entry.get("number") in configured_case_ids
        ]
    else:
        raise ValueError(f"Unsupported benchmark.selection.mode: {mode}")

    cases: list[dict[str, Any]] = []
    for index, entry in enumerate(selected_metadata, start=1):
        case_id = entry.get("number")
        if not case_id:
            problems.append(f"metadata entry {index} is missing number")
            continue
        case_dir = cases_dir / case_id if cases_dir else Path(case_id)
        missing = [name for name in REQUIRED_CASE_FILES if not (case_dir / name).exists()]
        if missing:
            problems.append(f"{case_id}: missing {', '.join(missing)} in {case_dir}")
        cases.append(
            {
                "index": index,
                "case_id": case_id,
                "runtime": case_runtime(case_id),
                "title": entry.get("title", ""),
                "url": entry.get("url", ""),
                "category": (entry.get("analysis") or {}).get("category", ""),
                "case_dir": str(case_dir),
                "missing_files": missing,
            }
        )
    return cases, problems


def read_case_text(case: dict[str, Any]) -> dict[str, str]:
    case_dir = Path(case["case_dir"])
    result: dict[str, str] = {}
    for name in ("README.md", "expected_diff.txt"):
        path = case_dir / name
        result[name] = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    return result


def build_task_text(
    case: dict[str, Any],
    runtime_cfg: dict[str, Any],
    worktree_dir: str | Path | None = None,
) -> str:
    texts = read_case_text(case)
    case_dir = Path(case["case_dir"]).resolve()
    rootfs_tar = case_dir.parent.parent / "alpine-base.tar.gz"
    build_command = runtime_cfg.get("build_command", "")
    runtime_path = runtime_cfg.get("runtime_path", "")
    target_repo = Path(worktree_dir).resolve() if worktree_dir is not None else None
    target_instructions = []
    if target_repo is not None:
        target_instructions = [
            "Writable target repository (the only location where source changes are allowed):",
            str(target_repo),
            "",
            "Required first command:",
            f"cd {shlex.quote(str(target_repo))} && git rev-parse HEAD && git status --short",
            "",
            "Inspect, edit, build, and collect git diff only in the writable target repository.",
            "Do not inspect or modify the source checkout under external/subjects; it may be at a different revision.",
            "Use absolute paths when calling Editor tools, and ensure every edited path is inside the writable target repository.",
            "",
        ]
    return "\n".join(
        [
            f"Fix OCI runtime bug case {case['case_id']}.",
            "",
            f"Target runtime: {case['runtime']}",
            f"Title: {case.get('title', '')}",
            f"Upstream issue: {case.get('url', '')}",
            f"Category: {case.get('category', '')}",
            "",
            "Goal:",
            "Modify the runtime source code so the candidate runtime behavior matches the configured reference runtime for the OCI reproduction case.",
            "Do not edit the dataset, generated worktree metadata, or oracle scripts.",
            "",
            *target_instructions,
            "Reproduction bundle absolute path (read-only):",
            str(case_dir),
            "",
            "Rootfs tar absolute path:",
            str(rootfs_tar),
            "",
            "Run reproduction commands from the reproduction bundle directory.",
            "",
            "Build command that will be used after your changes:",
            build_command,
            "",
            "Candidate runtime path after build:",
            str(runtime_path),
            "",
            "Expected differential behavior and validation notes:",
            texts.get("expected_diff.txt", "").strip(),
            "",
            "Case README:",
            texts.get("README.md", "").strip(),
        ]
    ).strip() + "\n"


def scan_candidate_files(
    repo_dir: Path,
    prompt_text: str,
    extensions: list[str],
    limit: int = 5,
) -> list[str]:
    tokens = {
        token
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", prompt_text.lower())
        if token not in {"the", "and", "that", "this", "with", "runtime", "case"}
    }
    scored: list[tuple[int, str]] = []
    for path in repo_dir.rglob("*"):
        if not path.is_file() or path.suffix not in extensions:
            continue
        rel = path.relative_to(repo_dir).as_posix()
        parts = set(Path(rel).parts)
        if parts & IGNORED_FILE_PARTS:
            continue
        haystack = rel.lower()
        score = sum(3 for token in tokens if token in haystack)
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")[:131072].lower()
        except OSError:
            content = ""
        score += sum(1 for token in tokens if token in content)
        if score > 0:
            scored.append((score, rel))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [rel for _, rel in scored[:limit]]


def check_garble_markers(paths: list[Path]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in GARBLE_MARKERS:
            if marker in text:
                hits.append(f"{path}: contains {marker}")
    return hits


def python_executable_name() -> str:
    return Path(sys.executable).name or "python"
