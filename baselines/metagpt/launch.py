from __future__ import annotations

import argparse
import faulthandler
import inspect
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


BOOTSTRAP_API_KEY = "sk-metagpt-oci-bootstrap"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch MetaGPT against an existing OCI runtime repository."
    )
    parser.add_argument("--baseline-repo", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-type", default="deepseek")
    parser.add_argument("--base-url")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--n-round", type=int, default=10)
    parser.add_argument("--investment", type=float, default=3.0)
    parser.add_argument("--max-auto-summarize-code", type=int, default=0)
    parser.add_argument("--run-tests", action="store_true")
    return parser.parse_args()


def required_path(value: str, *, directory: bool) -> Path:
    path = Path(value).resolve()
    exists = path.is_dir() if directory else path.is_file()
    if not exists:
        kind = "directory" if directory else "file"
        raise FileNotFoundError(f"Missing required {kind}: {path}")
    return path


def resolve_api_key() -> tuple[str, str]:
    for name in ("METAGPT_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value, name
    raise RuntimeError(
        "Missing API key: set METAGPT_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY."
    )


def resolve_base_url(explicit: str | None, api_type: str) -> str:
    configured = (
        explicit
        or os.environ.get("METAGPT_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or os.environ.get("OPENAI_BASE_URL")
    )
    if configured:
        return configured
    if api_type == "deepseek":
        return "https://api.deepseek.com"
    return "https://api.openai.com/v1"


def write_bootstrap_config(home: Path, *, api_type: str, model: str, base_url: str) -> Path:
    config_dir = home / ".metagpt"
    config_dir.mkdir(parents=True, exist_ok=True)
    try:
        config_dir.chmod(0o700)
    except OSError:
        pass
    config_path = config_dir / "config2.yaml"
    payload = {
        "llm": {
            "api_type": api_type,
            "api_key": BOOTSTRAP_API_KEY,
            "base_url": base_url,
            "model": model,
            "calc_usage": False,
        },
        "repair_llm_output": True,
    }
    config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        config_path.chmod(0o600)
    except OSError:
        pass
    return config_path


def git_revision(repo: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or None


def write_metadata(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def redact(value: str, secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    return redacted


def main() -> int:
    args = parse_args()
    if args.n_round <= 0:
        raise ValueError("--n-round must be greater than zero")
    if args.investment <= 0:
        raise ValueError("--investment must be greater than zero")
    if args.max_auto_summarize_code < -1:
        raise ValueError("--max-auto-summarize-code must be -1 or greater")

    baseline_repo = required_path(args.baseline_repo, directory=True)
    repo = required_path(args.repo, directory=True)
    task_file = required_path(args.task_file, directory=False)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output_dir / "launcher_metadata.json"

    api_key, api_key_source = resolve_api_key()
    base_url = resolve_base_url(args.base_url, args.api_type)
    write_bootstrap_config(
        Path.home(), api_type=args.api_type, model=args.model, base_url=base_url
    )

    os.environ["METAGPT_PROJECT_ROOT"] = str(baseline_repo)
    sys.path.insert(0, str(baseline_repo))

    metadata: dict[str, Any] = {
        "status": "starting",
        "baseline_repo": str(baseline_repo),
        "baseline_revision": git_revision(baseline_repo),
        "repo": str(repo),
        "task_file": str(task_file),
        "model": args.model,
        "api_type": args.api_type,
        "base_url": base_url,
        "api_key_source": api_key_source,
        "n_round": args.n_round,
        "investment": args.investment,
        "max_auto_summarize_code": args.max_auto_summarize_code,
        "run_tests": args.run_tests,
    }
    write_metadata(metadata_path, metadata)

    try:
        import metagpt.config2 as config_module
        from metagpt.configs.llm_config import LLMConfig
        from metagpt.software_company import generate_repo

        config_module.config.llm = LLMConfig(
            api_type=args.api_type,
            api_key=api_key,
            base_url=base_url,
            model=args.model,
            temperature=args.temperature,
            calc_usage=False,
        )
        config_module.config.repair_llm_output = True

        signature = inspect.signature(generate_repo)
        if "project_path" not in signature.parameters:
            raise RuntimeError(
                "This MetaGPT revision lacks generate_repo(project_path=...)."
            )

        parameters = {
            "idea": task_file.read_text(encoding="utf-8"),
            "investment": args.investment,
            "n_round": args.n_round,
            "code_review": True,
            "run_tests": args.run_tests,
            "implement": True,
            "project_name": repo.name,
            "inc": True,
            "project_path": str(repo),
            "reqa_file": "",
            "max_auto_summarize_code": args.max_auto_summarize_code,
            "recover_path": None,
        }
        supported = {
            name: value for name, value in parameters.items() if name in signature.parameters
        }
        metadata["status"] = "running_generate_repo"
        metadata["generate_repo_started_at_unix"] = time.time()
        metadata["launcher_pid"] = os.getpid()
        metadata["generate_repo_parameters"] = sorted(supported)
        write_metadata(metadata_path, metadata)

        faulthandler.enable()
        faulthandler.dump_traceback_later(300, repeat=True)
        try:
            result = generate_repo(**supported)
        finally:
            faulthandler.cancel_dump_traceback_later()
        metadata["status"] = "completed"
        metadata["result_project_path"] = str(result) if result is not None else None
        metadata["generate_repo_finished_at_unix"] = time.time()
        write_metadata(metadata_path, metadata)
        return 0
    except Exception as exc:
        metadata["status"] = "failed"
        metadata["error_type"] = type(exc).__name__
        metadata["error"] = redact(str(exc), (api_key,))
        write_metadata(metadata_path, metadata)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
