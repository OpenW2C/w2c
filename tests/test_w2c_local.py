#!/usr/bin/env python3
"""Tests for local-first W2C config, gitignore, migrate, and registry."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-local-test-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config" / ".w2c" / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "share" / "w2c")

from w2c import cli as w2c  # noqa: E402
from w2c import local as w2c_local  # noqa: E402


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


class W2CLocalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="w2c-repo-"))
        _git(self.tmp, "init", "-q")
        _git(self.tmp, "config", "user.email", "test@example.com")
        _git(self.tmp, "config", "user.name", "test")

    def test_init_writes_repo_config_and_registers(self) -> None:
        self.assertEqual(w2c.cmd_init(self.tmp), 0)
        cfg = self.tmp / ".w2c" / "config.toml"
        self.assertTrue(cfg.is_file())
        self.assertFalse(w2c_local.is_track_enabled(self.tmp))
        projects = w2c_local.load_global_config()["projects"]
        self.assertIn(str(self.tmp.resolve()), projects)

    def test_init_writes_copilot_instructions(self) -> None:
        self.assertEqual(w2c.cmd_init(self.tmp), 0)
        self.assertTrue((self.tmp / ".github/instructions/work-to-chores.instructions.md").is_file())
        self.assertTrue((self.tmp / ".github/instructions/do-chores.instructions.md").is_file())

    def test_gitignore_default_ignores_ledger_and_copilot(self) -> None:
        w2c.cmd_init(self.tmp)
        inst = self.tmp / ".github" / "instructions" / "work-to-chores.instructions.md"
        gi = (self.tmp / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".w2c/", gi)
        self.assertIn("work-to-chores.instructions.md", gi)
        proc = subprocess.run(["git", "-C", str(self.tmp), "check-ignore", "-q", ".w2c/STATE.md"])
        self.assertEqual(proc.returncode, 0)
        proc2 = subprocess.run(["git", "-C", str(self.tmp), "check-ignore", "-q", str(inst)])
        self.assertEqual(proc2.returncode, 0)

    def test_track_keeps_runtime_ignored_only(self) -> None:
        w2c.cmd_init(self.tmp, track=True)
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
        w2c.cmd_init(self.tmp, track=True)
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
        w2c.cmd_init(self.tmp)
        w2c_local.ensure_gitignore(self.tmp, track=False)
        w2c_local.backup_w2c_assets(self.tmp)
        import shutil
        shutil.rmtree(self.tmp / ".w2c")
        restored = w2c_local.migrate_adopt(self.tmp)
        self.assertTrue((self.tmp / ".w2c" / "STATE.md").is_file())
        self.assertIn(".w2c/", restored)

    def test_register_unregister_roundtrip(self) -> None:
        w2c.cmd_init(self.tmp)
        self.assertEqual(w2c.cmd_unregister(self.tmp), 0)
        self.assertNotIn(str(self.tmp.resolve()), w2c_local.load_global_config()["projects"])
        self.assertEqual(w2c.cmd_register(self.tmp), 0)
        self.assertIn(str(self.tmp.resolve()), w2c_local.load_global_config()["projects"])


if __name__ == "__main__":
    unittest.main()
