from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "baselines" / "metagpt" / "launch.py"
sys.path.insert(0, str(LAUNCHER.parent))
from launch import redact  # noqa: E402


class MetaGPTLauncherTests(unittest.TestCase):
    def test_redacts_api_key_from_error_text(self) -> None:
        self.assertEqual(
            redact("request failed for secret-key", ("secret-key",)),
            "request failed for <redacted>",
        )

    def _prepare_fake_upstream(self, root: Path, *, make_change: bool) -> Path:
        baseline_repo = root / "MetaGPT"
        package = baseline_repo / "metagpt"
        configs = package / "configs"
        terminal_libs = package / "tools" / "libs"
        utils = package / "utils"
        configs.mkdir(parents=True)
        terminal_libs.mkdir(parents=True)
        utils.mkdir(parents=True)
        for package_dir in (package, configs, package / "tools", terminal_libs, utils):
            (package_dir / "__init__.py").write_text("", encoding="utf-8")
        (package / "config2.py").write_text(
            "from pathlib import Path\n"
            "class Workspace:\n"
            "    path = Path('/upstream/workspace')\n"
            "class Config:\n"
            "    llm = None\n"
            "    repair_llm_output = False\n"
            "    workspace = Workspace()\n"
            "config = Config()\n",
            encoding="utf-8",
        )
        (configs / "llm_config.py").write_text(
            "class LLMConfig:\n"
            "    def __init__(self, **kwargs):\n"
            "        self.__dict__.update(kwargs)\n",
            encoding="utf-8",
        )
        (terminal_libs / "terminal.py").write_text(
            "from pathlib import Path\n"
            "END_MARKER_VALUE = '\\x18\\x19\\x1b\\x18\\n'\n"
            "DEFAULT_WORKSPACE_ROOT = Path('/upstream/workspace')\n"
            "class Terminal:\n"
            "    async def _read_and_process_output(self, cmd, daemon=False):\n"
            "        raise RuntimeError('vulnerable reader was not patched')\n"
            "    async def run_command(self, cmd, daemon=False):\n"
            "        return await self._read_and_process_output(cmd, daemon=daemon)\n",
            encoding="utf-8",
        )
        (utils / "role_zero_utils.py").write_text(
            "async def parse_commands(command_rsp, llm, exclusive_tool_commands=None):\n"
            "    return ([{'command_name': 'end'}], True, command_rsp)\n",
            encoding="utf-8",
        )
        (package / "software_company.py").write_text(
            "from pathlib import Path\n"
            "import subprocess\n"
            "from metagpt.config2 import config\n"
            "from metagpt.tools.libs import terminal\n"
            "from metagpt.utils import role_zero_utils\n"
            f"MAKE_CHANGE = {make_change!r}\n"
            "def generate_repo(idea, project_path, n_round=5, **kwargs):\n"
            "    project = Path(project_path)\n"
            "    assert Path.cwd() == project\n"
            "    assert config.workspace.path == project\n"
            "    assert terminal.DEFAULT_WORKSPACE_ROOT == project\n"
            "    assert getattr(terminal.Terminal, '__oci_terminal_compat__', None)\n"
            "    assert getattr(role_zero_utils, '__oci_command_compat__', None)\n"
            "    if MAKE_CHANGE:\n"
            "        Path(project, 'runtime.c').write_text(idea, encoding='utf-8')\n"
            "        subprocess.run(['git', '-C', str(project), 'add', 'runtime.c'], check=True)\n"
            "    return project_path\n",
            encoding="utf-8",
        )
        return baseline_repo

    def _prepare_candidate(self, root: Path) -> Path:
        candidate_repo = root / "candidate"
        candidate_repo.mkdir()
        (candidate_repo / "runtime.c").write_text("original\n", encoding="utf-8")
        subprocess.run(["git", "init", "--quiet", str(candidate_repo)], check=True)
        subprocess.run(
            ["git", "-C", str(candidate_repo), "add", "runtime.c"], check=True
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(candidate_repo),
                "-c",
                "user.name=MetaGPT Test",
                "-c",
                "user.email=metagpt-test@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "test(candidate): initialize fixture",
            ],
            check=True,
        )
        return candidate_repo

    def _run_launcher(
        self, root: Path, baseline_repo: Path, candidate_repo: Path
    ) -> tuple[subprocess.CompletedProcess[str], Path, str]:
        task_file = root / "task.md"
        task_file.write_text("repair this runtime", encoding="utf-8")
        output_dir = root / "output"
        home = root / "home"
        secret = "test-secret-must-not-be-persisted"
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "METAGPT_API_KEY": secret,
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                str(LAUNCHER),
                "--baseline-repo",
                str(baseline_repo),
                "--repo",
                str(candidate_repo),
                "--task-file",
                str(task_file),
                "--output-dir",
                str(output_dir),
                "--model",
                "fake-model",
                "--n-round",
                "1",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return result, output_dir, secret

    def test_fake_upstream_edits_bound_worktree_without_persisting_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_repo = self._prepare_fake_upstream(root, make_change=True)
            candidate_repo = self._prepare_candidate(root)

            result, output_dir, secret = self._run_launcher(
                root, baseline_repo, candidate_repo
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (candidate_repo / "runtime.c").read_text(encoding="utf-8"),
                "repair this runtime",
            )
            metadata = json.loads(
                (output_dir / "launcher_metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["status"], "completed")
            self.assertEqual(metadata["api_key_source"], "METAGPT_API_KEY")
            self.assertEqual(metadata["terminal_compat"]["status"], "applied")
            self.assertTrue(metadata["terminal_compat"]["workspace_root_override"])
            self.assertEqual(metadata["command_compat"]["status"], "applied")
            self.assertEqual(
                metadata["workspace_binding"]["process_cwd"], str(candidate_repo)
            )
            self.assertGreater(metadata["worktree_diff_size_bytes"], 0)
            self.assertGreater(metadata["launcher_pid"], 0)
            self.assertIn("generate_repo_started_at_unix", metadata)
            self.assertIn("generate_repo_finished_at_unix", metadata)

            persisted = "\n".join(
                path.read_text(encoding="utf-8", errors="replace")
                for path in root.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(secret, persisted)

    def test_launcher_fails_when_metagpt_produces_no_tracked_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_repo = self._prepare_fake_upstream(root, make_change=False)
            candidate_repo = self._prepare_candidate(root)

            result, output_dir, _ = self._run_launcher(
                root, baseline_repo, candidate_repo
            )

            self.assertNotEqual(result.returncode, 0)
            metadata = json.loads(
                (output_dir / "launcher_metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["status"], "failed")
            self.assertEqual(metadata["error_type"], "NoRepositoryChanges")
            self.assertEqual(metadata["worktree_diff_size_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
