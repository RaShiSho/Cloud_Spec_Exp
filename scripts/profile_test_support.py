"""Offline fixtures shared by adapter and configuration tests."""
from pathlib import Path
import json

from model_profiles import ResolvedProfile


def test_profile(**settings):
    values = {"protocol": "openai", "model": "test-model", "base_url": "https://gateway.example/v1", "api_key_env": "TEST_MODEL_KEY", "temperature": 0.25, "max_tokens": 4321, "token_limit_parameter": "max_tokens"}
    values.update(settings)
    return ResolvedProfile("test", values, values["api_key_env"] + " (environment)", "test-secret-never-print")


def write_snapshot(path: Path, profile: ResolvedProfile | None = None):
    profile = profile or test_profile()
    path.write_text(json.dumps(profile.public()), encoding="utf-8")
    return path
