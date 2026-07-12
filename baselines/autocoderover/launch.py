#!/usr/bin/env python3
"""Launch AutoCodeRover with arbitrary LiteLLM model names.

AutoCodeRover accepts ``litellm-generic-*`` in its model factory, but its CLI
restricts ``--model`` to the statically registered model list.  Register the
requested dynamic models before AutoCodeRover builds that argument parser.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any


LITELLM_GENERIC_PREFIX = "litellm-generic-"
IGNORED_SOURCE_PARTS = {
    ".git",
    ".tox",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "target",
    "test",
    "tests",
    "third_party",
    "vendor",
}
MAX_SOURCE_FILE_BYTES = 1_048_576


def normalize_model_args(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Return ACR argv and the real LiteLLM model names it must register."""
    normalized = list(argv)
    requested: list[str] = []

    index = 1
    while index < len(normalized):
        argument = normalized[index]
        if argument == "--model":
            index += 1
            while index < len(normalized) and not normalized[index].startswith("--"):
                model_name = normalized[index]
                if model_name.startswith(LITELLM_GENERIC_PREFIX):
                    model_name = model_name.removeprefix(LITELLM_GENERIC_PREFIX)
                    normalized[index] = model_name
                requested.append(model_name)
                index += 1
            continue
        if argument.startswith("--model="):
            model_name = argument.split("=", 1)[1]
            if model_name.startswith(LITELLM_GENERIC_PREFIX):
                model_name = model_name.removeprefix(LITELLM_GENERIC_PREFIX)
                normalized[index] = f"--model={model_name}"
            requested.append(model_name)
        index += 1

    return normalized, requested


def install_dynamic_registration(
    acr_main: Any,
    common: Any,
    model_names: Sequence[str],
) -> None:
    """Extend ACR's static registry before it constructs ``--model`` choices."""
    original_register_all_models = acr_main.register_all_models

    def register_all_models() -> None:
        original_register_all_models()
        for model_name in model_names:
            if model_name in common.MODEL_HUB:
                continue
            common.register_model(common.LiteLLMGeneric(model_name, 0.0, 0.0))

    acr_main.register_all_models = register_all_models


def parse_source_extensions(value: str) -> set[str]:
    extensions: set[str] = set()
    for item in value.split(","):
        extension = item.strip()
        if not extension:
            continue
        extensions.add(extension if extension.startswith(".") else f".{extension}")
    return extensions


def discover_source_files(project_path: str, extensions: set[str]) -> list[str]:
    project = Path(project_path)
    discovered: list[str] = []
    for path in sorted(project.rglob("*")):
        if not path.is_file() or path.suffix not in extensions:
            continue
        relative = path.relative_to(project)
        if any(part in IGNORED_SOURCE_PARTS for part in relative.parts):
            continue
        if path.name.endswith("_test.go") or path.name.startswith("test_"):
            continue
        try:
            if path.stat().st_size > MAX_SOURCE_FILE_BYTES:
                continue
        except OSError:
            continue
        discovered.append(str(path))
    return discovered


def install_non_python_source_fallback(search_backend: Any, extensions: set[str]) -> None:
    """Expose non-Python files to ACR's text/file search APIs.

    Class and method indexes remain Python-only.  Code search, line search and
    whole-file retrieval can still operate because they iterate ``parsed_files``.
    """
    if not extensions:
        return
    original_build_index = search_backend._build_index

    def build_index(instance: Any) -> None:
        original_build_index(instance)
        indexed = set(instance.parsed_files)
        for source_file in discover_source_files(instance.project_path, extensions):
            if source_file not in indexed:
                instance.parsed_files.append(source_file)
                indexed.add(source_file)

    search_backend._build_index = build_index


def main() -> int:
    normalized_argv, model_names = normalize_model_args(sys.argv)
    sys.argv = normalized_argv

    try:
        from app import main as acr_main
        from app.model import common
        from app.search.search_backend import SearchBackend
    except ImportError as exc:
        print(
            "Unable to import AutoCodeRover. Run this launcher with the "
            "AutoCodeRover repository on PYTHONPATH and its Python environment active: "
            f"{exc}",
            file=sys.stderr,
        )
        return 2

    install_dynamic_registration(acr_main, common, model_names)
    extensions = parse_source_extensions(os.getenv("ACR_SOURCE_EXTENSIONS", ""))
    install_non_python_source_fallback(SearchBackend, extensions)
    acr_main.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
