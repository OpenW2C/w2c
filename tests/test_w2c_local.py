#!/usr/bin/env python3
"""Tests for local-first W2C config, gitignore, migrate, and registry."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-local-test-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config" / ".w2c" / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "share" / "w2c")

from w2c import cli as w2c  # noqa: E402
from w2c import local as w2c_local  # noqa: E402
from w2c import git_delivery as w2c_gd  # noqa: E402


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


class W2CLocalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="w2c-repo-"))
        _git(self.tmp, "init", "-q")
        _git(self.tmp, "config", "user.email", "test@example.com")
        _git(self.tmp, "config", "user.name", "test")

    def test_init_writes_repo_config_and_registers(self) -> None:
        self.assertEqual(w2c.cmd_init(self.tmp, git_delivery="slice-commit-milestone-push-pr"), 0)
        cfg = self.tmp / ".w2c" / "config.toml"
        self.assertTrue(cfg.is_file())
        self.assertFalse(w2c_local.is_track_enabled(self.tmp))
        self.assertEqual(
            w2c_local.load_repo_config(self.tmp)["git_delivery"],
            "slice-commit-milestone-push-pr",
        )
        projects = w2c_local.load_global_config()["projects"]
        self.assertIn(str(self.tmp.resolve()), projects)

    def test_init_requires_git_delivery_without_tty(self) -> None:
        with mock.patch.object(w2c_gd.sys.stdin, "isatty", return_value=False):
            with self.assertRaises(w2c.W2CError) as ctx:
                w2c.cmd_init(self.tmp)
        self.assertIn("git_delivery", str(ctx.exception))

    def test_init_rejects_invalid_git_delivery(self) -> None:
        with self.assertRaises(w2c.W2CError) as ctx:
            w2c.cmd_init(self.tmp, git_delivery="nope")
        self.assertIn("invalid", str(ctx.exception).lower())

    def test_migrate_adopt_requires_git_delivery_when_missing(self) -> None:
        self.assertEqual(w2c.cmd_init(self.tmp, git_delivery="slice-commit-milestone-push-pr"), 0)
        # Strip git_delivery from config
        w2c_local.write_repo_config(self.tmp, track=False, git_delivery=None)
        # Force dump without key
        cfg = self.tmp / ".w2c" / "config.toml"
        cfg.write_text('track = false\nworktree_ledger = "symlink"\n', encoding="utf-8")
        with mock.patch.object(w2c_gd.sys.stdin, "isatty", return_value=False):
            with self.assertRaises(w2c.W2CError):
                w2c.cmd_migrate(self.tmp, "adopt")
        self.assertEqual(
            w2c.cmd_migrate(self.tmp, "adopt", git_delivery="milestone-commit-milestone-push-pr"),
            0,
        )
        self.assertEqual(
            w2c_local.load_repo_config(self.tmp)["git_delivery"],
            "milestone-commit-milestone-push-pr",
        )

    def test_init_writes_copilot_instructions(self) -> None:
        self.assertEqual(w2c.cmd_init(self.tmp, git_delivery="slice-commit-milestone-push-pr"), 0)
        self.assertTrue((self.tmp / ".github/instructions/work-to-chores.instructions.md").is_file())
        self.assertTrue((self.tmp / ".github/instructions/do-chores.instructions.md").is_file())

    def test_gitignore_default_ignores_ledger_and_copilot(self) -> None:
        w2c.cmd_init(self.tmp, git_delivery="slice-commit-milestone-push-pr")
        inst = self.tmp / ".github" / "instructions" / "work-to-chores.instructions.md"
        gi = (self.tmp / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".w2c/", gi)
        self.assertIn("work-to-chores.instructions.md", gi)
        proc = subprocess.run(["git", "-C", str(self.tmp), "check-ignore", "-q", ".w2c/STATE.md"])
        self.assertEqual(proc.returncode, 0)
        proc2 = subprocess.run(["git", "-C", str(self.tmp), "check-ignore", "-q", str(inst)])
        self.assertEqual(proc2.returncode, 0)

    def test_track_keeps_runtime_ignored_only(self) -> None:
        w2c.cmd_init(self.tmp, track=True, git_delivery="slice-commit-milestone-push-pr")
        runtime = self.tmp / ".w2c" / "runtime" / "events.jsonl"
        runtime.parent.mkdir(parents=True, exist_ok=True)
        runtime.write_text("{}" + chr(10), encoding="utf-8")
        gi = (self.tmp / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".w2c/runtime/", gi)
        self.assertNotIn(".w2c/\n", gi.replace(".w2c/runtime/", ""))
        self.assertTrue(w2c_local.is_track_enabled(self.tmp))
        proc = subprocess.run(["git", "-C", str(self.tmp), "check-ignore", "-q", ".w2c/STATE.md"])
        self.assertNotEqual(proc.returncode, 0)
        proc_r = subprocess.run(["git", "-C", str(self.tmp), "check-ignore", "-q", str(runtime)])
        self.assertEqual(proc_r.returncode, 0)

    def test_migrate_untrack_keeps_files_and_clears_index(self) -> None:
        w2c.cmd_init(self.tmp, track=True, git_delivery="slice-commit-milestone-push-pr")
        state = self.tmp / ".w2c" / "STATE.md"
        _git(self.tmp, "add", ".w2c/STATE.md")
        _git(self.tmp, "add", ".gitignore")
        _git(self.tmp, "commit", "-qm", "track w2c")
        tracked = w2c_local.git_ls_tracked_w2c(self.tmp)
        self.assertTrue(any("STATE.md" in t for t in tracked))
        backup = w2c_local.migrate_untrack(self.tmp)
        self.assertTrue(state.is_file())
        self.assertTrue(backup.is_dir())
        tracked_after = w2c_local.git_ls_tracked_w2c(self.tmp)
        self.assertFalse(any("STATE.md" in t for t in tracked_after))
        gi = (self.tmp / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".w2c/", gi)

    def test_migrate_adopt_restores_from_backup(self) -> None:
        w2c.cmd_init(self.tmp, git_delivery="slice-commit-milestone-push-pr")
        w2c_local.ensure_gitignore(self.tmp, track=False)
        w2c_local.backup_w2c_assets(self.tmp)
        import shutil
        shutil.rmtree(self.tmp / ".w2c")
        restored = w2c_local.migrate_adopt(self.tmp)
        self.assertTrue((self.tmp / ".w2c" / "STATE.md").is_file())
        self.assertIn(".w2c/", restored)

    def test_gitignore_rewrites_keep_the_cloud_lines_in_a_cloud_repo(self) -> None:
        copilot = (".github/instructions/work-to-chores.instructions.md",
                   ".github/instructions/do-chores.instructions.md")
        w2c.cmd_init(self.tmp, git_delivery="slice-commit-milestone-push-pr", planning="cloud")
        gi = self.tmp / ".gitignore"
        for run in (lambda: w2c.cmd_gitignore_ensure(self.tmp, False),
                    lambda: w2c_local.migrate_untrack(self.tmp),
                    lambda: w2c_local.migrate_adopt(self.tmp)):
            run()
            lines = gi.read_text(encoding="utf-8").splitlines()
            self.assertIn(".w2c/", lines)
            for line in copilot:
                self.assertNotIn(line, lines)
        self.assertEqual(w2c_local.load_repo_config(self.tmp)["planning"], "cloud")

    def test_gitignore_rewrites_keep_the_2_2_lines_in_a_2_2_repo(self) -> None:
        w2c.cmd_init(self.tmp, git_delivery="slice-commit-milestone-push-pr")
        gi = self.tmp / ".gitignore"
        for run in (lambda: w2c.cmd_gitignore_ensure(self.tmp, False),
                    lambda: w2c_local.migrate_untrack(self.tmp),
                    lambda: w2c_local.migrate_adopt(self.tmp)):
            run()
            lines = gi.read_text(encoding="utf-8").splitlines()
            for line in w2c_local.DEFAULT_GITIGNORE_MARKERS:
                self.assertIn(line, lines)

    def test_register_unregister_roundtrip(self) -> None:
        w2c.cmd_init(self.tmp, git_delivery="slice-commit-milestone-push-pr")
        self.assertEqual(w2c.cmd_unregister(self.tmp), 0)
        self.assertNotIn(str(self.tmp.resolve()), w2c_local.load_global_config()["projects"])
        self.assertEqual(w2c.cmd_register(self.tmp), 0)
        self.assertIn(str(self.tmp.resolve()), w2c_local.load_global_config()["projects"])

    # ---- cloud-mode Copilot files -------------------------------------
    GD = "slice-commit-milestone-push-pr"

    def _fake_skills(self, names=("work-to-chores-cloud", "do-chores-cloud")) -> Path:
        base = Path(tempfile.mkdtemp(prefix="w2c-skills-"))
        for n in names:
            d = base / n
            d.mkdir()
            (d / "SKILL.md").write_text(f"BODY {n}\n", encoding="utf-8")
            (d / "SKILL.copilot.md").write_text('---\napplyTo: "**"\n---\n', encoding="utf-8")
        real = w2c.skills_dir()
        for n in ("work-to-chores", "do-chores"):
            if real is not None and (real / n).is_dir():
                shutil.copytree(real / n, base / n)
        return base

    def _init(self, skills: Path, **kw) -> int:
        with mock.patch.object(w2c, "skills_dir", return_value=skills):
            return w2c.cmd_init(self.tmp, git_delivery=self.GD, **kw)

    def test_cloud_init_writes_neutral_copilot_files_not_ignored(self) -> None:
        skills = self._fake_skills()
        self.assertEqual(self._init(skills, planning="cloud"), 0)
        inst = self.tmp / ".github" / "instructions"
        plan = inst / "plan-work.instructions.md"
        do = inst / "do-work.instructions.md"
        self.assertIn("BODY work-to-chores-cloud", plan.read_text(encoding="utf-8"))
        self.assertIn('applyTo: "**"', plan.read_text(encoding="utf-8"))
        self.assertIn("BODY do-chores-cloud", do.read_text(encoding="utf-8"))
        self.assertFalse((inst / "work-to-chores.instructions.md").exists())
        gi = (self.tmp / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".w2c/", gi)
        self.assertFalse(any("instructions" in ln for ln in gi))
        for f in (plan, do):
            rc = subprocess.run(["git", "-C", str(self.tmp), "check-ignore", "-q", str(f)]).returncode
            self.assertNotEqual(rc, 0)

    def test_cloud_init_missing_skill_prints_note(self) -> None:
        skills = self._fake_skills(names=("work-to-chores-cloud",))
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(self._init(skills, planning="cloud"), 0)
        self.assertIn("NOTE missing skill do-chores-cloud; Copilot file not written", buf.getvalue())
        self.assertNotIn("missing skill work-to-chores-cloud", buf.getvalue())
        inst = self.tmp / ".github" / "instructions"
        self.assertTrue((inst / "plan-work.instructions.md").is_file())
        self.assertFalse((inst / "do-work.instructions.md").exists())

    def test_switching_default_to_cloud_replaces_copilot_files_after_flag(self) -> None:
        skills = self._fake_skills()
        self.assertEqual(self._init(skills), 0)
        inst = self.tmp / ".github" / "instructions"
        old = [inst / "work-to-chores.instructions.md", inst / "do-chores.instructions.md"]
        self.assertTrue(all(f.is_file() for f in old))
        gi_before = (self.tmp / ".gitignore").read_text(encoding="utf-8")
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            self._init(skills, planning="cloud")
        self.assertIn("NEED_COPILOT_REPLACE", buf.getvalue())
        self.assertTrue(all(f.is_file() for f in old))
        self.assertEqual((self.tmp / ".gitignore").read_text(encoding="utf-8"), gi_before)
        self.assertNotEqual(w2c_local.load_repo_config(self.tmp).get("planning"), "cloud")
        self.assertFalse((inst / "plan-work.instructions.md").exists())
        self.assertEqual(self._init(skills, planning="cloud", replace_copilot=True), 0)
        self.assertFalse(any(f.exists() for f in old))
        gi = (self.tmp / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("work-to-chores.instructions.md", gi)
        self.assertNotIn("do-chores.instructions.md", gi)
        self.assertIn(".w2c/", gi)
        self.assertTrue((inst / "plan-work.instructions.md").is_file())
        self.assertTrue((inst / "do-work.instructions.md").is_file())
        self.assertEqual(w2c_local.load_repo_config(self.tmp).get("planning"), "cloud")

    def test_legacy_init_unchanged(self) -> None:
        skills = self._fake_skills()
        self.assertEqual(self._init(skills, planning="classic"), 0)
        inst = self.tmp / ".github" / "instructions"
        self.assertTrue((inst / "work-to-chores.instructions.md").is_file())
        self.assertTrue((inst / "do-chores.instructions.md").is_file())
        self.assertFalse((inst / "plan-work.instructions.md").exists())
        gi = (self.tmp / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            [ln for ln in gi if ln and not ln.startswith("#")],
            list(w2c_local.DEFAULT_GITIGNORE_MARKERS),
        )
        self.assertEqual(
            w2c_local.gitignore_markers(False), list(w2c_local.DEFAULT_GITIGNORE_MARKERS)
        )
        self.assertEqual(w2c_local.gitignore_markers(False, "cloud"), [".w2c/"])


if __name__ == "__main__":
    unittest.main()
