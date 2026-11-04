#!/usr/bin/env python3
"""Local-file seeding for ticket worktrees (worktree_seed)."""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-seed-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from w2c import cli as w2c  # noqa: E402
from w2c import local as w2c_local  # noqa: E402
from w2c import worktree as w2c_worktree  # noqa: E402


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError((proc.stderr or proc.stdout or "git failed").strip())
    return proc


class WorktreeSeedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="w2c-seed-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def run_w2c(self, root: Path, *args: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = w2c.main(["--root", str(root), *args])
        return code, out.getvalue(), err.getvalue()

    def make_repo(self) -> Path:
        repo = self.tmp / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "test")
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        git(repo, "add", "README.md")
        git(repo, "commit", "-qm", "init")
        return repo

    def init_ledger(self, repo: Path) -> None:
        code, _out, err = self.run_w2c(
            repo, "init", "--git-delivery", "slice-commit-milestone-push-pr", "--planning", "classic"
        )
        self.assertEqual(code, 0, err)

    def test_normalize_rejects_absolute_and_dotdot(self) -> None:
        with self.assertRaises(w2c_local.LocalError):
            w2c_local.normalize_worktree_seed(["/tmp/.env"])
        with self.assertRaises(w2c_local.LocalError):
            w2c_local.normalize_worktree_seed(["../.env"])
        with self.assertRaises(w2c_local.LocalError):
            w2c_local.normalize_worktree_seed([""])
        nested = w2c_local.normalize_worktree_seed(["apps/app-v2/.env", ".env", ".env"])
        self.assertEqual(nested, ["apps/app-v2/.env", ".env"])

    def test_config_round_trip_preserves_seed(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        self.assertEqual(w2c_local.load_repo_config(repo).get("worktree_seed"), [])
        w2c_local.write_repo_config(
            repo, worktree_seed=[".env", "apps/app-v2/.env"]
        )
        loaded = w2c_local.load_repo_config(repo)["worktree_seed"]
        self.assertEqual(loaded, [".env", "apps/app-v2/.env"])
        w2c_local.write_repo_config(repo, track=False)
        self.assertEqual(
            w2c_local.load_repo_config(repo)["worktree_seed"],
            [".env", "apps/app-v2/.env"],
        )

    def test_seed_local_files_creates_nested_symlink(self) -> None:
        source = self.tmp / "main"
        dest = self.tmp / "wt"
        source.mkdir()
        dest.mkdir()
        nested = source / "apps" / "app-v2" / ".env"
        nested.parent.mkdir(parents=True)
        nested.write_text("SECRET=1\n", encoding="utf-8")
        (source / ".env").write_text("NPM_TOKEN=x\n", encoding="utf-8")
        lines = w2c_worktree.seed_local_files(
            source, dest, [".env", "apps/app-v2/.env", "missing.env"]
        )
        self.assertIn("seed-linked .env", lines)
        self.assertIn("seed-linked apps/app-v2/.env", lines)
        self.assertIn("seed-skip missing-source missing.env", lines)
        link = dest / ".env"
        self.assertTrue(link.is_symlink())
        self.assertTrue(link.samefile(source / ".env"))
        nested_link = dest / "apps" / "app-v2" / ".env"
        self.assertTrue(nested_link.is_symlink())
        self.assertTrue(nested_link.samefile(nested))

    def test_seed_conflict_and_ok_and_empty(self) -> None:
        source = self.tmp / "main2"
        dest = self.tmp / "wt2"
        source.mkdir()
        dest.mkdir()
        (source / ".env").write_text("a\n", encoding="utf-8")
        (dest / ".env").write_text("b\n", encoding="utf-8")
        lines = w2c_worktree.seed_local_files(source, dest, [".env"])
        self.assertEqual(lines, ["seed-conflict .env"])
        self.assertFalse((dest / ".env").is_symlink())
        self.assertEqual(w2c_worktree.seed_local_files(source, dest, []), [])

        dest2 = self.tmp / "wt3"
        dest2.mkdir()
        first = w2c_worktree.seed_local_files(source, dest2, [".env"])
        self.assertEqual(first, ["seed-linked .env"])
        second = w2c_worktree.seed_local_files(source, dest2, [".env"])
        self.assertEqual(second, ["seed-ok .env"])

        wrong = self.tmp / "other.env"
        wrong.write_text("z\n", encoding="utf-8")
        (dest2 / ".env").unlink()
        (dest2 / ".env").symlink_to(wrong)
        conflict = w2c_worktree.seed_local_files(source, dest2, [".env"])
        self.assertEqual(conflict, ["seed-conflict .env"])

    def test_check_seeded_reports_missing_and_conflict(self) -> None:
        source = self.tmp / "main3"
        dest = self.tmp / "wt4"
        source.mkdir()
        dest.mkdir()
        (source / ".env").write_text("a\n", encoding="utf-8")
        (source / ".envrc.local").write_text("b\n", encoding="utf-8")
        problems = w2c_worktree.check_seeded(
            source, dest, [".env", ".envrc.local", "absent.env"]
        )
        self.assertEqual(set(problems), {"seed-missing .env", "seed-missing .envrc.local"})
        w2c_worktree.seed_local_files(source, dest, [".env", ".envrc.local"])
        self.assertEqual(
            w2c_worktree.check_seeded(source, dest, [".env", ".envrc.local"]), []
        )
        (dest / ".env").unlink()
        (dest / ".env").write_text("not-a-link\n", encoding="utf-8")
        self.assertIn(
            "seed-conflict .env",
            w2c_worktree.check_seeded(source, dest, [".env", ".envrc.local"]),
        )

    def test_add_worktree_create_and_reuse_seed(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        (repo / ".env").write_text("NPM_TOKEN=secret\n", encoding="utf-8")
        nested = repo / "apps" / "app-v2" / ".env"
        nested.parent.mkdir(parents=True)
        nested.write_text("EXPO=1\n", encoding="utf-8")
        w2c_local.write_repo_config(
            repo, worktree_seed=[".env", "apps/app-v2/.env", "nope.env"]
        )

        code, out, err = self.run_w2c(
            repo, "worktree-add", "--branch", "TICKET-1", "--create-from", "main"
        )
        self.assertEqual(code, 0, err)
        wt = Path(out.strip())
        self.assertTrue(wt.is_dir())
        self.assertIn("seed-linked .env", err)
        self.assertIn("seed-linked apps/app-v2/.env", err)
        self.assertIn("seed-skip missing-source nope.env", err)
        self.assertTrue((wt / ".env").is_symlink())
        self.assertTrue((wt / ".env").samefile(repo / ".env"))
        self.assertTrue((wt / "apps" / "app-v2" / ".env").is_symlink())

        code2, out2, err2 = self.run_w2c(repo, "worktree-add", "--branch", "TICKET-1")
        self.assertEqual(code2, 0, err2)
        self.assertEqual(Path(out2.strip()).resolve(), wt.resolve())
        self.assertIn("seed-ok .env", err2)

        code3, out3, _err3 = self.run_w2c(wt, "worktree-seed", "--check")
        self.assertEqual(code3, 0, out3)

        (wt / ".env").unlink()
        code4, out4, _ = self.run_w2c(wt, "worktree-seed", "--check")
        self.assertEqual(code4, 1)
        self.assertIn("seed-missing .env", out4)
        code5, out5, _ = self.run_w2c(wt, "worktree-seed")
        self.assertEqual(code5, 0, out5)
        self.assertIn("seed-linked .env", out5)
        self.assertEqual(self.run_w2c(wt, "worktree-seed", "--check")[0], 0)

    def test_seed_source_root_from_linked_worktree(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        (repo / ".env").write_text("x\n", encoding="utf-8")
        w2c_local.write_repo_config(repo, worktree_seed=[".env"])
        code, out, err = self.run_w2c(
            repo, "worktree-add", "--branch", "TICKET-2", "--create-from", "main"
        )
        self.assertEqual(code, 0, err)
        wt = Path(out.strip())
        self.assertEqual(
            w2c_worktree.seed_source_root(wt).resolve(), repo.resolve()
        )

    def test_suggest_and_empty_check(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        (repo / ".env").write_text("x\n", encoding="utf-8")
        (repo / ".envrc.local").write_text("y\n", encoding="utf-8")
        code, out, err = self.run_w2c(repo, "worktree-seed", "--suggest")
        self.assertEqual(code, 0, err)
        self.assertIn(".env", out.splitlines())
        self.assertIn(".envrc.local", out.splitlines())
        code2, out2, err2 = self.run_w2c(repo, "worktree-seed", "--check")
        self.assertEqual(code2, 0, err2 + out2)
        code3, out3, err3 = self.run_w2c(repo, "worktree-seed")
        self.assertEqual(code3, 0, err3)
        self.assertEqual(out3.strip(), "")


if __name__ == "__main__":
    unittest.main()
