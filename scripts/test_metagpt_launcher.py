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

    def test_fake_upstream_edits_repo_without_persisting_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_repo = root / "MetaGPT"
            package = baseline_repo / "metagpt"
            configs = package / "configs"
            configs.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (configs / "__init__.py").write_text("", encoding="utf-8")
            (package / "config2.py").write_text(
                "class Config:\n"
                "    llm = None\n"
                "    repair_llm_output = False\n"
                "config = Config()\n",
                encoding="utf-8",
            )
            (configs / "llm_config.py").write_text(
                "class LLMConfig:\n"
                "    def __init__(self, **kwargs):\n"
                "        self.__dict__.update(kwargs)\n",
                encoding="utf-8",
            )
            (package / "software_company.py").write_text(
                "from pathlib import Path\n"
                "def generate_repo(idea, project_path, n_round=5, **kwargs):\n"
                "    Path(project_path, 'metagpt-change.txt').write_text(idea, encoding='utf-8')\n"
                "    return project_path\n",
                encoding="utf-8",
            )

            candidate_repo = root / "candidate"
            candidate_repo.mkdir()
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

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (candidate_repo / "metagpt-change.txt").read_text(encoding="utf-8"),
                "repair this runtime",
            )
            metadata = json.loads(
                (output_dir / "launcher_metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["status"], "completed")
            self.assertEqual(metadata["api_key_source"], "METAGPT_API_KEY")

            persisted = "\n".join(
                path.read_text(encoding="utf-8", errors="replace")
                for path in root.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(secret, persisted)


if __name__ == "__main__":
    unittest.main()
