"""Profile-aware entrypoints for mini-SWE-agent and Agentless."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile

from model_profiles import load_runtime_profile
from model_transport import bind_litellm, bind_openai, completion_parameters


def main() -> None:
    parser = argparse.ArgumentParser(allow_abbrev=False, )
    parser.add_argument("--kind", required=True, choices=("mini_swe_agent", "agentless_oci"))
    parser.add_argument("--baseline-repo", required=True)
    parser.add_argument("--model-config", required=True)
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--task-jsonl")
    parser.add_argument("--loc-jsonl")
    parser.add_argument("--case-id")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--max-samples", type=int, default=1)
    args = parser.parse_args()
    profile = load_runtime_profile(args.model_config)
    bind_openai(profile)
    repo = Path(args.baseline_repo).resolve()
    if args.kind == "mini_swe_agent":
        bind_litellm(profile)
        sys.path.insert(0, str(repo / "src"))
        # Prevent mini's user-level .env/config from changing this experiment.
        with tempfile.TemporaryDirectory(prefix="oci-mini-") as config_dir:
            os.environ["MSWEA_GLOBAL_CONFIG_DIR"] = config_dir
            os.environ["MSWEA_CONFIGURED"] = "true"
            from minisweagent.config import builtin_config_dir
            import yaml
            config = yaml.safe_load((builtin_config_dir / "mini.yaml").read_text())
            model_kwargs = completion_parameters(profile, {})
            model_kwargs.pop("model")
            model_kwargs.update(api_base=profile.settings["base_url"], drop_params=False)
            config["model"].update({
                "model_class": "litellm",
                "model_name": "openai/" + profile.settings["model"],
                "cost_tracking": "ignore_errors",
                "model_kwargs": model_kwargs,
            })
            config_path = Path(config_dir) / "mini.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            sys.argv = ["mini", "-c", str(config_path), "-y", "-t", Path(args.task_file).read_text(), "-o", args.output, "--exit-immediately"]
            runpy.run_module("minisweagent.run.mini", run_name="__main__")
    else:
        if not all((args.task_jsonl, args.loc_jsonl, args.case_id)):
            parser.error("Agentless requires --task-jsonl, --loc-jsonl and --case-id")
        sys.path.insert(0, str(repo))
        os.environ.setdefault("GIT_AUTHOR_NAME", "Agentless Runner")
        os.environ.setdefault("GIT_AUTHOR_EMAIL", "agentless@example.com")
        os.environ.setdefault("GIT_COMMITTER_NAME", "Agentless Runner")
        os.environ.setdefault("GIT_COMMITTER_EMAIL", "agentless@example.com")
        import agentless.util.model as models
        original = models.make_model

        def make_model(**kwargs):
            kwargs.update(model=profile.settings["model"], temperature=profile.settings["temperature"] if profile.settings["temperature"] is not None else 1, max_tokens=profile.settings["max_tokens"])
            return original(**kwargs)

        models.make_model = make_model
        model = profile.settings["model"]
        # Upstream insists DeepSeek-named models use its compatible decoder.
        # Both decoders use the profile-bound OpenAI client and endpoint.
        backend = "deepseek" if "deepseek" in model else "openai"
        sys.argv = ["repair.py", "--oci_task_file", args.task_jsonl, "--loc_file", args.loc_jsonl, "--output_folder", args.output, "--target_id", args.case_id, "--top_n", str(args.top_n), "--model", model, "--backend", backend, "--diff_format", "--cot", "--gen_and_process", "--num_threads", "1", "--max_samples", str(args.max_samples)]
        runpy.run_module("agentless.repair.repair", run_name="__main__")


if __name__ == "__main__":
    main()
