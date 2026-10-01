"""Diagnostic control: isolate four legacy variables without editing .env.

All other validation and execution goes through the real experiment runner.
This launcher is a test artifact, not a production configuration fix.
"""
from dataclasses import replace
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import model_profiles
import run_oci_experiment as runner

IGNORED = {"MSWEA_COST_TRACKING", "MSWEA_MODEL_NAME", "OPENAI_API_BASE", "OPENAI_BASE_URL"}


def diagnostic_profile(name, *, require_key=True):
    merged = {**model_profiles.read_dotenv(ROOT / ".env"), **os.environ}
    filtered = {key: value for key, value in merged.items() if key not in IGNORED}
    profile = model_profiles.resolve_profile(
        name, dotenv_path=Path("/dev/null"), environ=filtered, require_key=require_key,
    )
    return replace(profile, key_source=f"{profile.settings['api_key_env']} (project .env / environment, diagnostic legacy-variable isolation)")


if __name__ == "__main__":
    print("DIAGNOSTIC CONTROL: filter only " + ", ".join(sorted(IGNORED)), file=sys.stderr, flush=True)
    runner.resolve_profile = diagnostic_profile
    sys.exit(runner.main())
