from __future__ import annotations

import argparse
import faulthandler
import inspect
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from command_compat import (
    InvalidMetaGPTCommand,
    get_command_compat_state,
    install_command_compat,
)
from terminal_compat import install_terminal_compat


BOOTSTRAP_API_KEY = "sk-metagpt-oci-bootstrap"


class DirtyTargetRepository(RuntimeError):
    """Raised when the supposedly fresh experiment worktree is already dirty."""


class NoRepositoryChanges(RuntimeError):
    """Raised when MetaGPT returns without changing tracked repository files."""


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
            "calc_usage": True,
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


def git_diff(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "diff", "HEAD", "--binary", "--no-ext-diff"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Unable to collect git diff from target repository: {result.stderr.strip()}"
        )
    return result.stdout


def bind_metagpt_workspace(config: Any, repo: Path) -> dict[str, Any]:
    """Bind dynamic MetaGPT workspace settings before roles/tools are imported."""

    os.chdir(repo)
    os.environ["SWE_CMD_WORK_DIR"] = str(repo)
    details: dict[str, Any] = {
        "process_cwd": str(Path.cwd()),
        "swe_cmd_work_dir": os.environ["SWE_CMD_WORK_DIR"],
        "config_workspace_bound": False,
    }
    workspace = getattr(config, "workspace", None)
    if workspace is not None and hasattr(workspace, "path"):
        workspace.path = repo
        details["config_workspace_bound"] = True
        details["config_workspace_path"] = str(workspace.path)
    else:
        details["config_workspace_path"] = None
    return details


def write_metadata(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def resolve_cost_rates() -> tuple[float, float] | None:
    prompt_value = os.environ.get("METAGPT_PROMPT_COST_PER_1K")
    completion_value = os.environ.get("METAGPT_COMPLETION_COST_PER_1K")
    if prompt_value is None and completion_value is None:
        return None
    if prompt_value is None or completion_value is None:
        raise RuntimeError(
            "Set both METAGPT_PROMPT_COST_PER_1K and "
            "METAGPT_COMPLETION_COST_PER_1K, or neither."
        )
    try:
        prompt_rate = float(prompt_value)
        completion_rate = float(completion_value)
    except ValueError as exc:
        raise RuntimeError("MetaGPT cost rates must be numeric.") from exc
    if prompt_rate < 0 or completion_rate < 0:
        raise RuntimeError("MetaGPT cost rates must be non-negative.")
    return prompt_rate, completion_rate


def install_stream_usage_options(
    async_completions_class: type[Any],
    *,
    metadata: dict[str, Any],
    metadata_path: Path,
) -> dict[str, Any]:
    """Request authoritative usage data on every streamed Chat Completions call."""

    original = getattr(async_completions_class, "create", None)
    tracking: dict[str, Any] = {
        "status": "unavailable",
        "strategy": None,
        "stream_requests_with_usage": 0,
    }
    metadata["stream_usage_options"] = tracking
    if not callable(original):
        tracking["error"] = "async_chat_completions_create_not_found"
        write_metadata(metadata_path, metadata)
        return tracking
    if getattr(original, "__oci_include_stream_usage__", False):
        tracking["status"] = "already_applied"
        write_metadata(metadata_path, metadata)
        return tracking

    try:
        supports_direct_parameter = (
            "stream_options" in inspect.signature(original).parameters
        )
    except (TypeError, ValueError):
        supports_direct_parameter = False
    strategy = "stream_options_parameter" if supports_direct_parameter else "extra_body"
    tracking.update({"status": "applied", "strategy": strategy})
    lock = threading.Lock()

    async def create_with_stream_usage(
        self: Any, *args: Any, **kwargs: Any
    ) -> Any:
        if kwargs.get("stream") is True:
            if supports_direct_parameter:
                current = kwargs.get("stream_options")
                options = dict(current) if isinstance(current, dict) else {}
                options["include_usage"] = True
                kwargs["stream_options"] = options
            else:
                current = kwargs.get("extra_body")
                extra_body = dict(current) if isinstance(current, dict) else {}
                current_options = extra_body.get("stream_options")
                options = (
                    dict(current_options)
                    if isinstance(current_options, dict)
                    else {}
                )
                options["include_usage"] = True
                extra_body["stream_options"] = options
                kwargs["extra_body"] = extra_body
            with lock:
                tracking["stream_requests_with_usage"] += 1
                try:
                    write_metadata(metadata_path, metadata)
                except OSError:
                    pass
        return await original(self, *args, **kwargs)

    create_with_stream_usage.__oci_include_stream_usage__ = True
    setattr(async_completions_class, "create", create_with_stream_usage)
    write_metadata(metadata_path, metadata)
    return tracking


def install_usage_tracking(
    cost_module: Any,
    *,
    metadata: dict[str, Any],
    metadata_path: Path,
    configured_rates: tuple[float, float] | None,
) -> dict[str, Any]:
    """Record each usage update without depending on MetaGPT's final Context."""

    metrics: dict[str, Any] = {
        "schema_version": 1,
        "tokens": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "cost_usd": None,
        "llm_calls": 0,
        "models": [],
        "priced_llm_calls": 0,
        "unpriced_llm_calls": 0,
        "cost_source": None,
        "warnings": [],
    }
    if configured_rates is not None:
        metrics["cost_source"] = "configured_rates_per_1k_tokens"
        metrics["configured_rates_usd_per_1k_tokens"] = {
            "prompt": configured_rates[0],
            "completion": configured_rates[1],
        }
    metadata["llm_metrics"] = metrics

    lock = threading.Lock()
    active = threading.local()
    accumulated_cost = 0.0
    patched_classes: list[str] = []

    def persist() -> None:
        try:
            write_metadata(metadata_path, metadata)
        except OSError:
            # Metrics collection must not turn a successful repair into a failure.
            pass

    def record(
        manager: Any,
        *,
        prompt_tokens: Any,
        completion_tokens: Any,
        model: Any,
        cost_before: Any,
        cost_after: Any,
    ) -> None:
        nonlocal accumulated_cost
        if isinstance(prompt_tokens, bool) or not isinstance(prompt_tokens, (int, float)):
            return
        if isinstance(completion_tokens, bool) or not isinstance(
            completion_tokens, (int, float)
        ):
            return
        prompt = int(prompt_tokens)
        completion = int(completion_tokens)
        if prompt < 0 or completion < 0:
            return

        model_name = str(model) if model is not None else "<unknown>"
        with lock:
            metrics["tokens"]["prompt_tokens"] += prompt
            metrics["tokens"]["completion_tokens"] += completion
            metrics["tokens"]["total_tokens"] += prompt + completion
            metrics["llm_calls"] += 1
            if model_name not in metrics["models"]:
                metrics["models"].append(model_name)

            priced = False
            if configured_rates is not None:
                accumulated_cost += (
                    prompt * configured_rates[0]
                    + completion * configured_rates[1]
                ) / 1000
                priced = True
            else:
                token_costs = getattr(manager, "token_costs", None)
                model_has_rate = (
                    isinstance(token_costs, dict) and model_name in token_costs
                )
                if (
                    model_has_rate
                    and isinstance(cost_before, (int, float))
                    and not isinstance(cost_before, bool)
                    and isinstance(cost_after, (int, float))
                    and not isinstance(cost_after, bool)
                    and cost_after >= cost_before
                ):
                    accumulated_cost += float(cost_after - cost_before)
                    priced = True
                    metrics["cost_source"] = "metagpt_cost_manager"

            if priced:
                metrics["priced_llm_calls"] += 1
            else:
                metrics["unpriced_llm_calls"] += 1
                warning = f"missing_model_price:{model_name}"
                if warning not in metrics["warnings"]:
                    metrics["warnings"].append(warning)

            if metrics["unpriced_llm_calls"] == 0:
                metrics["cost_usd"] = round(accumulated_cost, 12)
            else:
                metrics["cost_usd"] = None
            persist()

    for class_name in (
        "CostManager",
        "TokenCostManager",
        "FireworksCostManager",
    ):
        manager_class = getattr(cost_module, class_name, None)
        original = (
            manager_class.__dict__.get("update_cost")
            if isinstance(manager_class, type)
            else None
        )
        if not callable(original) or getattr(original, "__oci_usage_tracking__", False):
            continue

        def tracked_update_cost(
            self: Any,
            prompt_tokens: Any,
            completion_tokens: Any,
            model: Any,
            *args: Any,
            _original: Any = original,
            **kwargs: Any,
        ) -> Any:
            depth = getattr(active, "depth", 0)
            active.depth = depth + 1
            cost_before = getattr(self, "total_cost", None)
            try:
                return _original(
                    self,
                    prompt_tokens,
                    completion_tokens,
                    model,
                    *args,
                    **kwargs,
                )
            finally:
                active.depth = depth
                if depth == 0:
                    record(
                        self,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        model=model,
                        cost_before=cost_before,
                        cost_after=getattr(self, "total_cost", None),
                    )

        tracked_update_cost.__oci_usage_tracking__ = True
        setattr(manager_class, "update_cost", tracked_update_cost)
        patched_classes.append(class_name)

    metadata["llm_usage_tracking"] = {
        "status": "applied" if patched_classes else "unavailable",
        "patched_classes": patched_classes,
    }
    if not patched_classes:
        metrics["warnings"].append("metagpt_cost_manager_not_found")
    persist()
    return metrics


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
    configured_rates = resolve_cost_rates()
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
        "playwright_browsers_path": os.environ.get("PLAYWRIGHT_BROWSERS_PATH"),
    }
    write_metadata(metadata_path, metadata)

    try:
        import metagpt.config2 as config_module
        from metagpt.configs.llm_config import LLMConfig
        from metagpt.utils import cost_manager as cost_module
        try:
            from openai.resources.chat.completions import AsyncCompletions
        except ImportError:
            from openai.resources.chat.completions.completions import (
                AsyncCompletions,
            )

        config_module.config.llm = LLMConfig(
            api_type=args.api_type,
            api_key=api_key,
            base_url=base_url,
            model=args.model,
            temperature=args.temperature,
            calc_usage=True,
        )
        config_module.config.repair_llm_output = True
        stream_usage_tracking = install_stream_usage_options(
            AsyncCompletions,
            metadata=metadata,
            metadata_path=metadata_path,
        )
        if stream_usage_tracking["status"] not in ("applied", "already_applied"):
            raise RuntimeError(
                "Unable to enable usage reporting for streamed OpenAI requests"
            )
        install_usage_tracking(
            cost_module,
            metadata=metadata,
            metadata_path=metadata_path,
            configured_rates=configured_rates,
        )

        initial_diff = git_diff(repo)
        metadata["initial_diff_size_bytes"] = len(initial_diff.encode("utf-8"))
        if initial_diff.strip():
            raise DirtyTargetRepository(
                "Target worktree already contains tracked changes before MetaGPT starts"
            )

        metadata["workspace_binding"] = bind_metagpt_workspace(
            config_module.config, repo
        )

        metadata["terminal_compat"] = install_terminal_compat(
            working_directory=repo
        )
        metadata["command_compat"] = install_command_compat()
        write_metadata(metadata_path, metadata)

        from metagpt.software_company import generate_repo

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
            metadata["generate_repo_finished_at_unix"] = time.time()
        metadata["command_compat"] = get_command_compat_state()
        patch = git_diff(repo)
        metadata["worktree_diff_size_bytes"] = len(patch.encode("utf-8"))
        if metadata["command_compat"]["status"] == "failed":
            raise InvalidMetaGPTCommand(
                "MetaGPT stopped after repeated malformed RoleZero commands: "
                f"{metadata['command_compat']['last_error']}"
            )
        if not patch.strip():
            raise NoRepositoryChanges(
                "MetaGPT returned without changing tracked files in the target worktree"
            )
        metadata["status"] = "completed"
        metadata["result_project_path"] = str(result) if result is not None else None
        write_metadata(metadata_path, metadata)
        return 0
    except Exception as exc:
        metadata["command_compat"] = get_command_compat_state()
        metadata["status"] = "failed"
        metadata["error_type"] = type(exc).__name__
        metadata["error"] = redact(str(exc), (api_key,))
        write_metadata(metadata_path, metadata)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
