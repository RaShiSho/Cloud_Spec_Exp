"""Re-run the diagnostic fixtures without API calls or production source edits."""
import argparse
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "diagnostics"


def mini_probe():
    sys.path.insert(0, str(ROOT / "external/baselines/mini-swe-agent/src"))
    with tempfile.TemporaryDirectory(prefix="oci-mini-probe-") as tmp:
        os.environ["MSWEA_GLOBAL_CONFIG_DIR"] = tmp
        os.environ["MSWEA_CONFIGURED"] = "true"
        from minisweagent.config import get_config_from_spec
        p = Path(tmp) / "mini.json"
        p.write_text(json.dumps({"model": {"model_name": "placeholder"}}))
        report = {"json_file_exists": p.exists()}
        try:
            report["json_only_result"] = get_config_from_spec(p)
        except Exception as exc:
            report["json_only_error"] = {"type": type(exc).__name__, "message": str(exc)}
        p.with_suffix(".yaml").write_bytes(p.read_bytes())
        report["same_json_content_with_yaml_suffix"] = get_config_from_spec(p)
        return report


def agentless_probe():
    sys.path.insert(0, str(ROOT / "external/baselines/Agentless"))
    from agentless.repair.repair import _post_process_multifile_repair
    raw_file = OUT.parent / "controlled/agentless-oci-adapted/crun-13/agentless-output/output.jsonl"
    raw = json.loads(raw_file.read_text().splitlines()[0])["raw_output"][0]
    logger = logging.getLogger("offline-probe")
    logger.addHandler(logging.NullHandler())
    actual = _post_process_multifile_repair(raw, {}, logger, {}, diff_format=True)
    fixture = "```python\n### sample.c\n<<<<<<< SEARCH\nint value = 1;\n=======\nint value = 2;\n>>>>>>> REPLACE\n```"
    control = _post_process_multifile_repair(fixture, {"sample.c": "int value = 1;\n"}, logger, {"sample.c": [(1, 1)]}, diff_format=True)
    return {"actual_response_parse": actual, "valid_format_fixture_parse": control}


def repairagent_probe():
    spec = importlib.util.spec_from_file_location("oci_tools_probe", ROOT / "baselines/repairagent/oci_tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix="oci-repair-tools-probe-") as tmp:
        root = Path(tmp)
        os.environ["REPAIRAGENT_OCI_REPO"] = tmp
        os.environ["REPAIRAGENT_OCI_SOURCE_EXTENSIONS"] = ".c,.h"
        (root / "sample.c").write_text("/* example process header */\nexecvp(args[0], args);\nint\nfind_executable (const char *path)\n{\n  return 0;\n}\n")
        report = {"string_input_search": module.search_code("execvp"), "list_input_search": module.search_code(["execvp"]), "gnu_style_function_scan": module.list_symbols("sample.c")}
        (root / "single_line.c").write_text("int find_executable (const char *path)\n{\n  return 0;\n}\n")
        report["single_line_return_type_function_scan"] = module.list_symbols("single_line.c")
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("mini", "agentless", "repairagent"))
    args = parser.parse_args()
    payload = {"probe": args.kind, "result": {"mini": mini_probe, "agentless": agentless_probe, "repairagent": repairagent_probe}[args.kind]()}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{args.kind}-offline-replay.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
