#!/usr/bin/env python3
"""Run a minimal MetaGPT Terminal probe without using a real LLM API key."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path


BOOTSTRAP_API_KEY = "sk-metagpt-terminal-probe"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that MetaGPT Terminal can run and close a shell command."
    )
    parser.add_argument(
        "--baseline-repo",
        default=os.environ.get("METAGPT_PROJECT_ROOT", "."),
        help="Path to the MetaGPT source checkout (default: METAGPT_PROJECT_ROOT or cwd).",
    )
    parser.add_argument("--command", default="pwd")
    parser.add_argument("--command-timeout", type=float, default=10.0)
    return parser.parse_args()


def prepare_environment(baseline_repo: Path, home: Path) -> Path:
    package_dir = baseline_repo / "metagpt"
    if not package_dir.is_dir():
        raise FileNotFoundError(f"Missing MetaGPT package directory: {package_dir}")

    config_dir = home / ".metagpt"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config2.yaml"
    config = {
        "llm": {
            "api_type": "deepseek",
            "api_key": BOOTSTRAP_API_KEY,
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
            "calc_usage": False,
        },
        "repair_llm_output": True,
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    try:
        config_path.chmod(0o600)
    except OSError:
        pass

    os.environ["HOME"] = str(home)
    os.environ["METAGPT_PROJECT_ROOT"] = str(baseline_repo)
    sys.path.insert(0, str(baseline_repo))
    return config_path


async def run_probe(command: str, command_timeout: float) -> None:
    # Import only after the isolated HOME bootstrap config has been written.
    from metagpt.tools.libs.terminal import Terminal

    terminal = Terminal()
    try:
        print(f"开始执行 {command}", flush=True)
        output = await asyncio.wait_for(
            terminal.run_command(command), timeout=command_timeout
        )
        print(f"终端输出：{output!r}", flush=True)
    finally:
        await asyncio.wait_for(terminal.close(), timeout=5.0)


def main() -> int:
    args = parse_args()
    if args.command_timeout <= 0:
        raise ValueError("--command-timeout must be greater than zero")

    baseline_repo = Path(args.baseline_repo).expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="metagpt-terminal-probe-") as temp_home:
        config_path = prepare_environment(baseline_repo, Path(temp_home))
        print(f"MetaGPT 源码目录：{baseline_repo}", flush=True)
        print(f"临时 bootstrap 配置：{config_path}", flush=True)
        asyncio.run(run_probe(args.command, args.command_timeout))
    print("MetaGPT Terminal 探针通过", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
