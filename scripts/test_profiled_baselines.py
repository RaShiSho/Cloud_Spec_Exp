from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_profiles import ROOT
from profile_test_support import test_profile, write_snapshot
import launch_profiled_baseline as launcher


class ProfiledBaselineTests(unittest.TestCase):
    def test_wrappers_reject_old_model_and_endpoint_overrides(self):
        for name in ("metagpt", "repairagent", "patchagent", "autocoderover"):
            for option in ("--model", "--base-url"):
                with self.subTest(baseline=name, option=option):
                    result = subprocess.run(["bash", str(ROOT / "baselines" / name / "run_oci_repair.sh"), option, "override"], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("Unknown argument", result.stderr)

    def test_mini_uses_isolated_config_with_resolved_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mini.yaml").write_text("model: {}\nagent: {}\n")
            task = root / "task.md"
            task.write_text("repair this")
            profile = test_profile()
            snapshot = write_snapshot(root / "profile.json", profile)
            package = types.ModuleType("minisweagent")
            package.__path__ = []
            config_module = types.ModuleType("minisweagent.config")
            config_module.builtin_config_dir = root
            modules = {"minisweagent": package, "minisweagent.config": config_module}
            argv = ["launcher", "--kind", "mini_swe_agent", "--baseline-repo", str(root), "--model-config", str(snapshot), "--task-file", str(task), "--output", str(root / "trajectory.json")]

            def run_module(name, **kwargs):
                self.assertEqual(name, "minisweagent.run.mini")
                path = Path(sys.argv[sys.argv.index("-c") + 1])
                config = json.loads(path.read_text())
                settings = config["model"]
                self.assertEqual(settings["model_class"], "litellm")
                self.assertEqual(settings["model_name"], "openai/test-model")
                self.assertEqual(settings["model_kwargs"]["temperature"], 0.25)
                self.assertEqual(settings["model_kwargs"]["api_base"], profile.settings["base_url"])
                self.assertNotIn(profile.api_key, path.read_text())
                self.assertEqual(Path(os.environ["MSWEA_GLOBAL_CONFIG_DIR"]), path.parent)
                self.assertTrue(os.environ["MSWEA_CONFIGURED"])

            with (
                mock.patch.dict(sys.modules, modules),
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(sys, "path", sys.path.copy()),
                mock.patch.dict(os.environ, {"TEST_MODEL_KEY": profile.api_key}, clear=True),
                mock.patch.object(launcher, "bind_openai") as bind,
                mock.patch.object(launcher, "bind_litellm") as bind_lite,
                mock.patch.object(launcher.runpy, "run_module", side_effect=run_module),
            ):
                launcher.main()
            bind.assert_called_once_with(profile)
            bind_lite.assert_called_once_with(profile)

    def test_agentless_sampling_and_backend_use_same_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = test_profile(model="deepseek-custom")
            snapshot = write_snapshot(root / "profile.json", profile)
            package = types.ModuleType("agentless")
            package.__path__ = []
            util = types.ModuleType("agentless.util")
            util.__path__ = []
            models = types.ModuleType("agentless.util.model")
            models.make_model = mock.Mock(return_value="decoder")
            original = models.make_model
            modules = {"agentless": package, "agentless.util": util, "agentless.util.model": models}
            argv = ["launcher", "--kind", "agentless_oci", "--baseline-repo", str(root), "--model-config", str(snapshot), "--task-file", "task.md", "--output", str(root / "output"), "--task-jsonl", "task.jsonl", "--loc-jsonl", "loc.jsonl", "--case-id", "crun-1"]

            def run_module(name, **kwargs):
                self.assertEqual(name, "agentless.repair.repair")
                self.assertEqual(sys.argv[sys.argv.index("--model") + 1], profile.settings["model"])
                self.assertEqual(sys.argv[sys.argv.index("--backend") + 1], "deepseek")
                # Simulate greedy and later upstream decoder construction.
                for temperature in (0, 0.8):
                    self.assertEqual(models.make_model(model="internal", backend="deepseek", logger=None, temperature=temperature, max_tokens=1024), "decoder")

            with (
                mock.patch.dict(sys.modules, modules),
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(sys, "path", sys.path.copy()),
                mock.patch.dict(os.environ, {"TEST_MODEL_KEY": profile.api_key}, clear=True),
                mock.patch.object(launcher, "bind_openai") as bind,
                mock.patch.object(launcher.runpy, "run_module", side_effect=run_module),
            ):
                launcher.main()
            bind.assert_called_once_with(profile)
            self.assertEqual(original.call_count, 2)
            for call in original.call_args_list:
                self.assertEqual(call.kwargs["model"], "deepseek-custom")
                self.assertEqual(call.kwargs["temperature"], 0.25)
                self.assertEqual(call.kwargs["max_tokens"], 4321)


if __name__ == "__main__":
    unittest.main()
