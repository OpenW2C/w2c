"""Installer --ref flag, the cloud-sessions help topic, and its platform snippets."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "cloud-sessions.md"


def run_install(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(REPO / "install.sh"), "--dry-run", *args],
        capture_output=True, text=True, check=False,
    )


class InstallRefTests(unittest.TestCase):
    def test_install_dry_run_reports_ref(self) -> None:
        # Piped install: no local checkout beside the script, so it would clone the ref.
        script = (REPO / "install.sh").read_text(encoding="utf-8")
        env = dict(os.environ, W2C_REPO_URL=str(REPO))
        proc = subprocess.run(
            ["bash", "-s", "--", "--dry-run", "--ref", "v9.9.9"],
            input=script, capture_output=True, text=True, env=env, check=False,
        )
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("v9.9.9", out)

    def test_dry_run_defaults_ref_to_main_on_network_install(self) -> None:
        script = (REPO / "install.sh").read_text(encoding="utf-8")
        env = dict(os.environ, W2C_REPO_URL=str(REPO))
        proc = subprocess.run(
            ["bash", "-s", "--", "--dry-run"],
            input=script, capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ref main", proc.stdout + proc.stderr)

    def test_local_checkout_ignores_ref(self) -> None:
        proc = run_install("--ref", "v9.9.9")
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("--ref is ignored", out)

    def test_local_checkout_without_ref_prints_no_ref_line(self) -> None:
        proc = run_install()
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("--ref is ignored", proc.stdout + proc.stderr)

    def test_ref_needs_a_value(self) -> None:
        proc = run_install("--ref")
        self.assertNotEqual(proc.returncode, 0)


class CloudSessionsDocTests(unittest.TestCase):
    def test_help_cloud_sessions_prints_doc(self) -> None:
        env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
        proc = subprocess.run(
            [sys.executable, "-m", "w2c", "help", "cloud-sessions"],
            capture_output=True, text=True, env=env, cwd=str(REPO), check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, DOC.read_text(encoding="utf-8"))

    def _sections(self) -> dict[str, str]:
        text = DOC.read_text(encoding="utf-8")
        parts = re.split(r"^### ", text, flags=re.M)[1:]
        return {p.splitlines()[0].strip(): p for p in parts}

    def test_each_platform_snippet_is_complete(self) -> None:
        sections = self._sections()
        for name in ("Claude Code and Codex", "GitHub Copilot", "Cursor"):
            self.assertIn(name, sections)
            body = sections[name]
            for needle in ("--ref v3.2.0", "@fission-ai/openspec@1.16.0",
                           "w2c install-skills", ".local/bin"):
                self.assertIn(needle, body, f"{name}: {needle}")
            self.assertLess(body.index("--ref v3.2.0"), body.index("@fission-ai/openspec@1.16.0"))
            self.assertLess(body.index("@fission-ai/openspec@1.16.0"), body.index("w2c install-skills"))
        self.assertIn("copilot-setup-steps:", sections["GitHub Copilot"])
        self.assertIn(".github/workflows/copilot-setup-steps.yml", sections["GitHub Copilot"])
        self.assertIn(".cursor/environment.json", sections["Cursor"])
        self.assertIn('"install"', sections["Cursor"])

    def test_bashrc_line_is_appended_once(self) -> None:
        line = 'export PATH="$HOME/.local/bin:$PATH"'
        guarded = f"grep -qxF '{line}' ~/.bashrc || echo '{line}' >> ~/.bashrc"
        sections = self._sections()
        self.assertIn(guarded, sections["Claude Code and Codex"])
        cursor_guarded = "{ " + guarded.replace('"', '\\"') + "; }"
        self.assertIn(cursor_guarded, sections["Cursor"])
        text = DOC.read_text(encoding="utf-8")
        self.assertEqual(text.count("appends `export PATH="), 2)
        self.assertNotIn("to `~/.bashrc` if", text)
        home = Path(tempfile.mkdtemp(prefix="w2c-bashrc-"))
        self.addCleanup(shutil.rmtree, home, True)
        for _ in range(2):
            subprocess.run(["bash", "-c", guarded], env=dict(os.environ, HOME=str(home)), check=True,
                           capture_output=True)
        self.assertEqual((home / ".bashrc").read_text(encoding="utf-8"), line + "\n")

    def test_doc_covers_ephemeral_skills_push_and_uvx(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        for needle in ("W2C_EPHEMERAL", "CLAUDE_CODE_REMOTE", "CODESPACES", "GITHUB_ACTIONS",
                       "work-to-chores-cloud", "do-chores-cloud", "grilling", "brainstorming",
                       "requesting-code-review", "uvx --from git+https://github.com/OpenW2C/w2c@v3.2.0"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
