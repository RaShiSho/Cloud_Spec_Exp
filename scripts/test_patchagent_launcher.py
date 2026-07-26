from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "baselines" / "patchagent" / "launch.py"
SPEC = importlib.util.spec_from_file_location("patchagent_oci_launcher", LAUNCHER)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PatchAgentLauncherTests(unittest.TestCase):
    def test_parse_source_extensions_normalizes_and_deduplicates(self) -> None:
        self.assertEqual(
            MODULE.parse_source_extensions(".c,h, rs, .c"),
            (".c", ".h", ".rs"),
        )

    def test_locate_symbol_text_supports_c_go_and_rust(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "sample.c").write_text(
                "static int parse_config(void) { return 0; }\n", encoding="utf-8"
            )
            (root / "sample.go").write_text(
                "func parseBundle(path string) error { return nil }\n", encoding="utf-8"
            )
            (root / "sample.rs").write_text(
                "pub fn load_spec() -> Result<(), ()> { Ok(()) }\n", encoding="utf-8"
            )

            self.assertEqual(
                MODULE.locate_symbol_text(root, "parse_config", (".c",)),
                ["sample.c:1"],
            )
            self.assertEqual(
                MODULE.locate_symbol_text(root, "parseBundle", (".go",)),
                ["sample.go:1"],
            )
            self.assertEqual(
                MODULE.locate_symbol_text(root, "load_spec", (".rs",)),
                ["sample.rs:1"],
            )

    def test_locate_symbol_rejects_non_identifier_input(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            self.assertEqual(
                MODULE.locate_symbol_text(Path(raw), "../secret", (".c",)),
                [],
            )

    def test_remove_nested_git_metadata_preserves_submodule_sources(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / ".git").write_text(
                "gitdir: /tmp/superproject/worktrees/case\n", encoding="utf-8"
            )
            submodule = root / "libocispec"
            submodule.mkdir()
            (submodule / ".git").write_text(
                "gitdir: ../../.git/modules/libocispec\n", encoding="utf-8"
            )
            (submodule / "runtime_spec_schema_config.c").write_text(
                "int parse_spec(void) { return 0; }\n", encoding="utf-8"
            )
            nested = submodule / "vendor"
            (nested / ".git").mkdir(parents=True)
            (nested / ".git" / "config").write_text("[core]\n", encoding="utf-8")
            (root / ".github").mkdir()

            removed = MODULE.remove_nested_git_metadata(root)

            self.assertEqual(
                removed,
                [".git", "libocispec/.git", "libocispec/vendor/.git"],
            )
            self.assertFalse((root / ".git").exists())
            self.assertFalse((submodule / ".git").exists())
            self.assertFalse((nested / ".git").exists())
            self.assertTrue(
                (submodule / "runtime_spec_schema_config.c").is_file()
            )
            self.assertTrue((root / ".github").is_dir())


if __name__ == "__main__":
    unittest.main()
