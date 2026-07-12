from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = REPO_ROOT / "baselines" / "autocoderover" / "launch.py"
SPEC = importlib.util.spec_from_file_location("autocoderover_launcher", LAUNCHER_PATH)
assert SPEC is not None and SPEC.loader is not None
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class FakeLiteLLMGeneric:
    def __init__(self, name: str, input_cost: float, output_cost: float):
        self.name = name
        self.input_cost = input_cost
        self.output_cost = output_cost


class AutoCodeRoverLauncherTests(unittest.TestCase):
    def test_normalizes_generic_model_prefix(self) -> None:
        argv, models = launcher.normalize_model_args(
            [
                "launch.py",
                "local-issue",
                "--model",
                "litellm-generic-deepseek/deepseek-v4-flash",
                "--task-id",
                "crun-13",
            ]
        )

        self.assertEqual(argv[3], "deepseek/deepseek-v4-flash")
        self.assertEqual(models, ["deepseek/deepseek-v4-flash"])

    def test_registers_unknown_model_before_acr_parser_is_built(self) -> None:
        common = SimpleNamespace(
            MODEL_HUB={"known-model": object()},
            LiteLLMGeneric=FakeLiteLLMGeneric,
        )
        common.register_model = lambda model: common.MODEL_HUB.__setitem__(model.name, model)

        calls: list[str] = []
        acr_main = SimpleNamespace(register_all_models=lambda: calls.append("upstream"))
        launcher.install_dynamic_registration(
            acr_main,
            common,
            ["known-model", "deepseek/deepseek-v4-flash"],
        )

        acr_main.register_all_models()

        self.assertEqual(calls, ["upstream"])
        registered = common.MODEL_HUB["deepseek/deepseek-v4-flash"]
        self.assertIsInstance(registered, FakeLiteLLMGeneric)
        self.assertEqual(registered.input_cost, 0.0)
        self.assertEqual(registered.output_cost, 0.0)

    def test_discovers_non_python_sources_without_tests_or_vendor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "src").mkdir()
            (project / "src" / "main.go").write_text("package main\n", encoding="utf-8")
            (project / "src" / "main_test.go").write_text("package main\n", encoding="utf-8")
            (project / "vendor").mkdir()
            (project / "vendor" / "copy.go").write_text("package copy\n", encoding="utf-8")
            (project / "README.md").write_text("docs\n", encoding="utf-8")

            discovered = launcher.discover_source_files(str(project), {".go"})

        self.assertEqual(discovered, [str(project / "src" / "main.go")])

    def test_adds_non_python_files_to_search_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "runtime.c"
            source.write_text("int main(void) { return 0; }\n", encoding="utf-8")

            class FakeSearchBackend:
                def __init__(self, project_path: str):
                    self.project_path = project_path
                    self.parsed_files: list[str] = []
                    self._build_index()

                def _build_index(self) -> None:
                    self.parsed_files.append(str(project / "helper.py"))

            launcher.install_non_python_source_fallback(FakeSearchBackend, {".c"})
            backend = FakeSearchBackend(str(project))

        self.assertEqual(backend.parsed_files, [str(project / "helper.py"), str(source)])


if __name__ == "__main__":
    unittest.main()
