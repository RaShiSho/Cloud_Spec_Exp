"""The single model configuration boundary for OCI experiments and adapters.

Registry/snapshot files contain references to credentials, never credentials.
Only OpenAI-compatible chat-completion endpoints are supported by all adapters.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "configs" / "model_profiles.yaml"
PROFILE_FIELDS = {"protocol", "model", "base_url", "api_key_env", "temperature", "max_tokens", "token_limit_parameter"}
# These previously changed routing or sampling outside the experiment YAML.
LEGACY_MODEL_ENV = {
    "OPENAI_API_BASE", "OPENAI_BASE_URL", "OPENAI_API_BASE_URL", "OPENAI_MODEL",
    "OPENAI_API_TYPE", "OPENAI_API_VERSION", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID",
    "AZURE_OPENAI_ENDPOINT", "DEEPSEEK_API_BASE", "DEEPSEEK_BASE_URL",
    "MSWEA_MODEL_NAME", "MSWEA_MODEL_CLASS", "MSWEA_MINI_CONFIG_PATH",
    "ACR_MODEL", "ACR_MODEL_TEMPERATURE", "ACR_TOKEN_LIMIT", "METAGPT_API_TYPE", "METAGPT_BASE_URL",
    "PATCHAGENT_BASE_URL", "REPAIRAGENT_BASE_URL", "REPAIRAGENT_TEMPERATURE",
    "FAST_LLM", "SMART_LLM", "FAST_TOKEN_LIMIT", "SMART_TOKEN_LIMIT", "TEMPERATURE", "USE_AZURE", "OPENAI_KEY",
    "MSWEA_COST_TRACKING", "MSWEA_GLOBAL_CONFIG_DIR",
    "ACR_TASK_ID", "ACR_CONDA_ENV", "ACR_PYTHON",
    "METAGPT_CONDA_ENV", "METAGPT_PYTHON", "REPAIRAGENT_CONDA_ENV", "REPAIRAGENT_PYTHON",
    "PATCHAGENT_CONDA_ENV", "PATCHAGENT_PYTHON",
}
LEGACY_KEY_ENV = {"OPENAI_API_KEY", "DEEPSEEK_API_KEY", "METAGPT_API_KEY", "REPAIRAGENT_API_KEY", "PATCHAGENT_API_KEY"}


class ConfigError(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader: UniqueLoader, node: Any, deep: bool = False) -> dict:
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ConfigError(f"YAML keys must be strings (line {key_node.start_mark.line + 1})")
        if key in result:
            raise ConfigError(f"Duplicate YAML field {key!r} (line {key_node.start_mark.line + 1})")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def read_yaml(path: str | Path) -> dict[str, Any]:
    try:
        data = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=UniqueLoader)
    except yaml.YAMLError as exc:
        # YAML's default error includes the offending line, possibly a secret.
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1}" if mark else ""
        raise ConfigError(f"Invalid YAML in {path}{location}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"Expected a YAML mapping: {path}")
    return data


def fields(value: Any, allowed: set[str], location: str, required: set[str] | None = None) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{location} must be a mapping")
    unknown = set(value) - allowed
    if unknown:
        raise ConfigError(f"{location}: unsupported/unused fields: {', '.join(sorted(unknown))}")
    missing = (required or set()) - set(value)
    if missing:
        raise ConfigError(f"{location}: missing fields: {', '.join(sorted(missing))}")
    return value


def nonempty(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ConfigError(f"{location} must be a nonempty string without surrounding whitespace")
    return value


def validate_profile(value: Any, location: str) -> dict[str, Any]:
    data = fields(value, PROFILE_FIELDS, location, PROFILE_FIELDS)
    for key in ("protocol", "model", "base_url", "api_key_env", "token_limit_parameter"):
        nonempty(data[key], f"{location}.{key}")
    if data["protocol"] != "openai":
        raise ConfigError(f"{location}.protocol: only 'openai' chat completions are supported")
    try:
        url = urlsplit(data["base_url"])
        url.port  # Validate malformed and out-of-range ports before launching.
    except ValueError:
        raise ConfigError(f"{location}.base_url is not a valid URL") from None
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment or any(char.isspace() for char in data["base_url"]):
        raise ConfigError(f"{location}.base_url must be an HTTP(S) endpoint without credentials, query or fragment")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", data["api_key_env"]):
        raise ConfigError(f"{location}.api_key_env must name an environment variable")
    if data["api_key_env"] in LEGACY_MODEL_ENV or data["api_key_env"].startswith("OCI_"):
        raise ConfigError(f"{location}.api_key_env uses a reserved variable")
    temperature = data["temperature"]
    if temperature is not None and (type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2):
        raise ConfigError(f"{location}.temperature must be null or a number between 0 and 2")
    if type(data["max_tokens"]) is not int or data["max_tokens"] <= 0:
        raise ConfigError(f"{location}.max_tokens must be a positive integer")
    if data["token_limit_parameter"] not in {"max_tokens", "max_completion_tokens"}:
        raise ConfigError(f"{location}.token_limit_parameter must be max_tokens or max_completion_tokens")
    return dict(data)


def load_registry(path: str | Path = REGISTRY) -> dict[str, dict[str, Any]]:
    data = fields(read_yaml(path), {"version", "profiles"}, "model registry", {"version", "profiles"})
    if type(data["version"]) is not int or data["version"] != 1:
        raise ConfigError("model registry.version must be 1")
    if not isinstance(data["profiles"], dict) or not data["profiles"]:
        raise ConfigError("model registry.profiles must be a nonempty mapping")
    return {nonempty(name, "profile name"): validate_profile(value, f"profiles.{name}") for name, value in data["profiles"].items()}


def read_dotenv(path: Path) -> dict[str, str]:
    # Use the project's dotenv syntax, without mutating the process environment.
    if __package__:
        from .oci_common import _parse_dotenv_value
    else:
        from oci_common import _parse_dotenv_value
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigError(f"Invalid .env assignment at {path}:{number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ConfigError(f"Invalid .env variable name at {path}:{number}")
        if key in result:
            raise ConfigError(f"Duplicate .env variable {key} at {path}:{number}")
        result[key] = _parse_dotenv_value(value)
    return result


@dataclass(frozen=True)
class ResolvedProfile:
    name: str
    settings: dict[str, Any]
    key_source: str
    api_key: str = field(repr=False)

    def public(self) -> dict[str, Any]:
        return {"name": self.name, **self.settings, "api_key_source": self.key_source}

    def identity(self) -> dict[str, Any]:
        # A rotated credential also invalidates resume, without persisting it.
        return {**self.public(), "credential_sha256": hashlib.sha256(self.api_key.encode()).hexdigest()}

    def child_env(self, env: Mapping[str, str] | None = None) -> dict[str, str]:
        child = dict(os.environ if env is None else env)
        for key in LEGACY_MODEL_ENV | LEGACY_KEY_ENV:
            child.pop(key, None)
        child[self.settings["api_key_env"]] = self.api_key
        return child

    def redact(self, text: str) -> str:
        return text.replace(self.api_key, "<redacted>") if self.api_key else text


def resolve_profile(name: str, *, registry_path: str | Path = REGISTRY, dotenv_path: Path | None = None, environ: Mapping[str, str] | None = None, require_key: bool = True) -> ResolvedProfile:
    registry = load_registry(registry_path)
    if name not in registry:
        raise ConfigError(f"Unknown model_profile {name!r}; available: {', '.join(registry)}")
    env = dict(os.environ if environ is None else environ)
    dotenv_path = dotenv_path if dotenv_path is not None else ROOT / ".env"
    dotenv = read_dotenv(dotenv_path)
    credential_names = {profile["api_key_env"] for profile in registry.values()}
    model_vars = credential_names | LEGACY_MODEL_ENV | LEGACY_KEY_ENV
    unknown = dotenv.keys() - model_vars - {"PIP_INDEX_URL", "PIP_DEFAULT_TIMEOUT"}
    if unknown:
        raise ConfigError("Unsupported/unused .env variables: " + ", ".join(sorted(unknown)))
    for key in dotenv.keys() & env.keys() & model_vars:
        if dotenv[key] != env[key]:
            raise ConfigError(f"Conflicting values for {key} in environment and {dotenv_path}; remove one definition")
    merged = {**dotenv, **env}
    reserved = sorted(key for key in LEGACY_MODEL_ENV if merged.get(key))
    reserved += sorted(key for key in LEGACY_KEY_ENV - credential_names if merged.get(key))
    if reserved:
        raise ConfigError("Model configuration outside the registry is not allowed: " + ", ".join(reserved))
    settings = registry[name]
    key_name = settings["api_key_env"]
    api_key = merged.get(key_name, "")
    if not api_key.strip() and require_key:
        raise ConfigError(f"Missing credential {key_name} for model_profile {name!r}")
    origins = []
    if key_name in env:
        origins.append("environment")
    if key_name in dotenv:
        origins.append(str(dotenv_path))
    source = f"{key_name} ({' + '.join(origins) or 'unset'})"
    return ResolvedProfile(name, settings, source, api_key)


def load_runtime_profile(path: str | Path) -> ResolvedProfile:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    fields(data, PROFILE_FIELDS | {"name", "api_key_source"}, "model snapshot", PROFILE_FIELDS | {"name", "api_key_source"})
    settings = validate_profile({key: data[key] for key in PROFILE_FIELDS}, "model snapshot")
    # Runner-generated execution settings are allowed; model overrides are not.
    execution_vars = {key for key in LEGACY_MODEL_ENV if key.endswith(("_CONDA_ENV", "_PYTHON"))}
    conflicts = sorted(key for key in LEGACY_MODEL_ENV - execution_vars if os.environ.get(key))
    if conflicts:
        raise ConfigError("Model overrides are not allowed with a snapshot: " + ", ".join(conflicts))
    key = os.environ.get(settings["api_key_env"], "")
    if not key:
        raise ConfigError(f"Missing credential {settings['api_key_env']} for model snapshot")
    return ResolvedProfile(data["name"], settings, data["api_key_source"], key)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
