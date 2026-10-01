from __future__ import annotations

import copy
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from experiment_config import validate_experiment
from model_profiles import ConfigError, ROOT, load_registry, read_yaml, resolve_profile
import model_profiles
from oci_common import load_config
from profile_test_support import test_profile
from run_identity import execution_inputs, run_identity
import run_oci_experiment as runner


class ModelProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.registry = self.root / "profiles.yaml"
        self.dotenv = self.root / ".env"
        self.data = {"version": 1, "profiles": {"test": test_profile().settings, "other": test_profile(api_key_env="OTHER_KEY").settings}}
        self.save_registry()

    def save_registry(self):
        self.registry.write_text(yaml.safe_dump(self.data))

    def resolve(self, env=None, **kwargs):
        return resolve_profile("test", registry_path=self.registry, dotenv_path=self.dotenv, environ=env or {}, **kwargs)

    def test_key_comes_only_from_named_variable(self):
        self.dotenv.write_text("TEST_MODEL_KEY='chosen-secret'\nOTHER_KEY=unselected\n")
        profile = self.resolve()
        self.assertEqual(profile.api_key, "chosen-secret")
        self.assertIn(str(self.dotenv), profile.key_source)
        self.assertNotIn("chosen-secret", json.dumps(profile.public()))
        self.assertNotIn("chosen-secret", json.dumps(profile.identity()))
        self.assertNotIn("chosen-secret", repr(profile))
        with self.assertRaisesRegex(ConfigError, "Missing credential TEST_MODEL_KEY"):
            self.dotenv.unlink()
            self.resolve({"OTHER_KEY": "no-fallback"})

    def test_shell_dotenv_conflicts_never_show_values(self):
        self.dotenv.write_text("TEST_MODEL_KEY=file-secret\n")
        with self.assertRaises(ConfigError) as error:
            self.resolve({"TEST_MODEL_KEY": "shell-secret"})
        self.assertIn("TEST_MODEL_KEY", str(error.exception))
        self.assertNotIn("file-secret", str(error.exception))
        self.assertNotIn("shell-secret", str(error.exception))
        profile = self.resolve({"TEST_MODEL_KEY": "file-secret"})
        self.assertIn("environment +", profile.key_source)

    def test_no_legacy_model_or_endpoint_environment(self):
        for key in ("OPENAI_BASE_URL", "OPENAI_API_BASE", "METAGPT_BASE_URL", "MSWEA_MODEL_NAME", "REPAIRAGENT_TEMPERATURE", "ACR_MODEL", "PATCHAGENT_BASE_URL"):
            with self.subTest(key=key), self.assertRaisesRegex(ConfigError, key):
                self.resolve({"TEST_MODEL_KEY": "secret", key: "unused-override"})

    def test_unknown_dotenv_entries_and_duplicate_assignments_fail(self):
        for text in ("MODEL_NMAE=x\n", "TEST_MODEL_KEY=a\nTEST_MODEL_KEY=a\n", "not-an-assignment\n"):
            self.dotenv.write_text(text)
            with self.subTest(text=text), self.assertRaises(ConfigError):
                self.resolve()

    def test_invalid_profile_fields_are_rejected_even_if_not_selected(self):
        for key, value in (("api_key", "never-print-this-key"), ("temperatur", 0.8), ("provider", "deepseek")):
            self.data["profiles"]["other"] = {**test_profile().settings, key: value}
            self.save_registry()
            with self.subTest(key=key), self.assertRaises(ConfigError) as error:
                self.resolve({"TEST_MODEL_KEY": "secret"})
            self.assertNotIn("never-print-this-key", str(error.exception))

    def test_required_fields_and_values_are_validated(self):
        for key, value in (("protocol", "anthropic"), ("base_url", "https://user:password@example.com/v1"), ("base_url", "https://example.com/v1?api_key=secret"), ("api_key_env", "not a name"), ("temperature", "0.5"), ("temperature", True), ("temperature", float("nan")), ("max_tokens", 0), ("max_tokens", True), ("token_limit_parameter", "not_used")):
            self.data["profiles"]["test"] = {**test_profile().settings, key: value}
            self.save_registry()
            with self.subTest(key=key, value=value), self.assertRaises(ConfigError):
                load_registry(self.registry)
        self.data["profiles"]["test"] = test_profile().settings.copy()
        del self.data["profiles"]["test"]["base_url"]
        self.save_registry()
        with self.assertRaisesRegex(ConfigError, "missing fields: base_url"):
            load_registry(self.registry)

    def test_duplicate_yaml_and_merge_overrides_are_rejected(self):
        for text in ("x: 1\nx: 2\n", "a: &a {x: 1}\nb: {<<: *a, x: 2}\n"):
            self.registry.write_text(text)
            with self.assertRaises(ConfigError):
                read_yaml(self.registry)

    def test_missing_credential_allowed_only_for_dry_run(self):
        self.assertEqual(self.resolve(require_key=False).api_key, "")
        with self.assertRaises(ConfigError):
            self.resolve()

    def test_unknown_profile_is_actionable(self):
        with self.assertRaisesRegex(ConfigError, "available: other, test"):
            resolve_profile("missing", registry_path=self.registry, dotenv_path=self.dotenv, environ={})


class ExperimentSchemaTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "configs" / "experiment.metagpt.yaml")

    def test_all_shipped_experiments_validate(self):
        profiles = load_registry()
        for path in (ROOT / "configs").glob("experiment.*.yaml"):
            with self.subTest(path=path.name):
                config = load_config(path)
                self.assertIn(config["model_profile"], profiles)

    def test_root_and_baseline_model_overrides_rejected(self):
        for location in ("root", "baseline"):
            for field in ("model", "provider", "temperature", "base_url", "api_key", "model_profile" if location == "baseline" else "model_overrides"):
                config = copy.deepcopy(self.config)
                target = config if location == "root" else config["baselines"][0]
                target[field] = "forbidden"
                with self.subTest(location=location, field=field), self.assertRaises(ConfigError):
                    validate_experiment(config)

    def test_unknown_and_unused_options_fail(self):
        mutations = [
            lambda c: c["experiment"].update(keep_failed_workdirs=True),
            lambda c: c["oracle"].update(command="unused"),
            lambda c: c["benchmark"]["selection"].update(count=5),
            lambda c: c["baselines"][0].update(command="override --model wrong"),
            lambda c: c["baselines"][0].update(top_n_files=5),
            lambda c: c["baselines"][0].update(adapter="unused"),
            lambda c: c["baselines"][0].update(timeout_seconds="30"),
            lambda c: c["runtimes"]["runc"].update(buggy_ref="A", default_ref="B"),
            lambda c: c["baselines"].append(copy.deepcopy(c["baselines"][0])),
        ]
        for mutation in mutations:
            config = copy.deepcopy(self.config)
            mutation(config)
            with self.subTest(config=config), self.assertRaises(ConfigError):
                validate_experiment(config)


class RunIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "runtime.c").write_text("first\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-qm", "first"], check=True)
        case_dir = self.root / "case"
        case_dir.mkdir()
        (case_dir / "README.md").write_text("original bug")
        self.config = {
            "experiment": {"name": "test", "output_dir": str(self.root / "results"), "worktree_root": str(self.root / "worktrees"), "timeout_seconds": 30},
            "model_profile": "test", "benchmark": {"rootfs_tar": str(self.root / "rootfs.tar")},
            "runtimes": {"crun": {"source_dir": str(repo), "build_command": "make", "runtime_path": "crun", "reference_runtime": "/bin/true"}},
            "oracle": {"timeout_seconds": 1},
        }
        self.baseline = {"kind": "metagpt", "name": "metagpt", "repo_dir": str(repo)}
        self.config["baselines"] = [self.baseline]
        self.case = {"case_id": "crun-1", "case_dir": str(case_dir), "runtime": "crun"}
        self.profile = test_profile()
        self.inputs = execution_inputs(self.config, [self.baseline])

    def identity(self, config=None, profile=None):
        return run_identity(config or self.config, self.baseline, self.case, profile or self.profile, self.inputs)

    def test_canonical_config_and_profile_are_stable_without_plaintext_secrets(self):
        first = self.identity()
        reversed_config = dict(reversed(list(self.config.items())))
        self.assertEqual(first["fingerprint"], self.identity(reversed_config)["fingerprint"])
        self.assertNotIn(self.profile.api_key, json.dumps(first))

    def test_model_endpoint_sampling_key_and_source_changes_invalidate(self):
        original = self.identity()["fingerprint"]
        for field, value in (("model", "other-model"), ("base_url", "https://new.example/v1"), ("temperature", 0.9), ("max_tokens", 999), ("token_limit_parameter", "max_completion_tokens"), ("api_key_env", "NEW_KEY")):
            profile = replace(self.profile, settings={**self.profile.settings, field: value})
            with self.subTest(field=field):
                self.assertNotEqual(original, self.identity(profile=profile)["fingerprint"])
        for profile in (replace(self.profile, name="alias"), replace(self.profile, api_key="rotated"), replace(self.profile, key_source="elsewhere")):
            self.assertNotEqual(original, self.identity(profile=profile)["fingerprint"])

    def test_experiment_baseline_runtime_and_input_changes_invalidate(self):
        original = self.identity()["fingerprint"]
        for section, field, value in (("experiment", "timeout_seconds", 31), ("oracle", "timeout_seconds", 2)):
            changed = copy.deepcopy(self.config)
            changed[section][field] = value
            self.assertNotEqual(original, self.identity(changed)["fingerprint"])
        changed = copy.deepcopy(self.config)
        changed["runtimes"]["crun"]["build_command"] = "make other"
        self.assertNotEqual(original, self.identity(changed)["fingerprint"])
        changed = copy.deepcopy(self.config)
        changed["baselines"][0]["n_round"] = 55
        self.assertNotEqual(original, self.identity(changed)["fingerprint"])
        (Path(self.case["case_dir"]) / "README.md").write_text("changed input")
        self.assertNotEqual(original, self.identity()["fingerprint"])

    def test_startup_preview_and_all_resume_checks_precede_execution(self):
        args = mock.Mock(clean=False, resume=True, dry_run=False, config="fixture.yaml", case=None, baseline=None, limit=None)
        other = {**self.case, "case_id": "crun-2"}
        output = runner.output_dir_for_run(self.config, self.baseline, other)
        output.mkdir(parents=True)
        (output / "metadata.json").write_text('{"status":"done","config_fingerprint":"old"}')
        stderr = io.StringIO()
        with (
            mock.patch.object(runner, "parse_args", return_value=args),
            mock.patch.object(runner, "load_config", return_value=self.config),
            mock.patch.object(runner, "resolve_profile", return_value=self.profile),
            mock.patch.object(runner, "selected_cases", return_value=([self.case, other], [])),
            mock.patch.object(runner, "preflight", return_value=[]),
            mock.patch.object(runner, "run_one") as run,
            mock.patch("sys.stderr", stderr),
        ):
            self.assertEqual(runner.main(), 2)
        run.assert_not_called()
        self.assertIn(self.profile.settings["model"], stderr.getvalue())
        self.assertIn(self.profile.settings["base_url"], stderr.getvalue())
        self.assertIn(self.profile.settings["api_key_env"], stderr.getvalue())
        self.assertNotIn(self.profile.api_key, stderr.getvalue())
        self.assertIn("configuration changed", stderr.getvalue())
        self.assertEqual(json.loads((output / "metadata.json").read_text())["config_fingerprint"], "old")

    def test_matching_completed_run_is_skipped_without_cleanup(self):
        identity = self.identity()
        output = runner.output_dir_for_run(self.config, self.baseline, self.case)
        output.mkdir(parents=True)
        (output / "metadata.json").write_text(json.dumps({"status": "done", "config_fingerprint": identity["fingerprint"]}))
        (output / "oracle.json").write_text('{"status":"pass"}')
        args = mock.Mock(clean=False, resume=True, dry_run=False, config="fixture.yaml", case=None, baseline=None, limit=None)
        with (
            mock.patch.object(runner, "parse_args", return_value=args),
            mock.patch.object(runner, "load_config", return_value=self.config),
            mock.patch.object(runner, "resolve_profile", return_value=self.profile),
            mock.patch.object(runner, "selected_cases", return_value=([self.case], [])),
            mock.patch.object(runner, "preflight", return_value=[]),
            mock.patch.object(runner, "run_one") as run,
            mock.patch.object(runner, "clean_previous_run") as clean,
            mock.patch("builtins.print"),
        ):
            self.assertEqual(runner.main(), 0)
        run.assert_not_called()
        clean.assert_not_called()

    def test_real_dry_run_reads_config_and_prints_safe_plan_without_writes(self):
        config = copy.deepcopy(self.config)
        config["model_profile"] = "deepseek-official"
        metadata = self.root / "metadata.json"
        metadata.write_text('[{"number":"crun-1","title":"test"}]')
        cases = self.root / "cases"
        case = cases / "crun-1"
        case.mkdir(parents=True)
        for name in ("base_config.json", "buggy_config.json", "repro.sh", "expected_diff.txt", "README.md"):
            (case / name).write_text("fixture")
        Path(config["benchmark"]["rootfs_tar"]).write_text("fixture rootfs")
        config["benchmark"].update(metadata_file=str(metadata), cases_dir=str(cases), selection={"mode": "all"})
        config_path = self.root / "experiment.yaml"
        config_path.write_text(yaml.safe_dump(config))
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(model_profiles, "ROOT", self.root),
            mock.patch.dict(os.environ, {"PATH": os.environ["PATH"], "DEEPSEEK_API_KEY": "offline-dummy-credential"}, clear=True),
            mock.patch.object(sys, "argv", ["runner", "--config", str(config_path), "--dry-run"]),
            mock.patch("sys.stdout", stdout),
            mock.patch("sys.stderr", stderr),
        ):
            self.assertEqual(runner.main(), 0, stderr.getvalue())
        plan = json.loads(stdout.getvalue())
        self.assertEqual(plan["model_profile"]["name"], "deepseek-official")
        self.assertEqual(len(plan["runs"][0]["config_fingerprint"]), 64)
        self.assertNotIn("offline-dummy-credential", stdout.getvalue() + stderr.getvalue())
        self.assertFalse(Path(config["experiment"]["output_dir"]).exists())


if __name__ == "__main__":
    unittest.main()
