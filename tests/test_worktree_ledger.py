#!/usr/bin/env python3
"""Shared ledger, worktree layout, hooks, and the OpenSpec push check."""

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

_HOME = Path(tempfile.mkdtemp(prefix="w2c-worktree-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from w2c import cli as w2c  # noqa: E402
from w2c import local as w2c_local  # noqa: E402


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError((proc.stderr or proc.stdout or "git failed").strip())
    return proc


class WorktreeLedgerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="w2c-wt-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def run_w2c(self, root: Path, *args: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = w2c.main(["--root", str(root), *args])
        return code, out.getvalue(), err.getvalue()

    def make_repo(self, name: str = "repo") -> Path:
        repo = self.tmp / name
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "test")
        (repo / "README.md").write_text("hello\n", encoding="utf-8")
        git(repo, "add", "README.md")
        git(repo, "commit", "-qm", "init")
        return repo

    def init_ledger(self, repo: Path, *, track: bool = False, planning: str = "classic") -> None:
        args = ["init", "--git-delivery", "slice-commit-milestone-push-pr", "--planning", planning]
        if track:
            args.append("--track")
        code, _out, err = self.run_w2c(repo, *args)
        self.assertEqual(code, 0, err)

    def test_schema_stays_readable_by_current_install(self) -> None:
        self.assertEqual(w2c_local.CURRENT_SCHEMA_VERSION, 3)

    def test_untracked_ledger_moves_into_git_dir(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        link = repo / ".w2c"
        self.assertTrue(link.is_symlink())
        store = repo / ".git" / "w2c" / "ledger"
        self.assertTrue((store / "STATE.md").is_file())
        self.assertEqual(link.resolve(), store.resolve())
        status = git(repo, "status", "--porcelain").stdout
        listed = git(repo, "ls-files").stdout
        self.assertNotIn("w2c/ledger", status)
        self.assertNotIn(".w2c", status)
        self.assertNotIn("w2c/ledger", listed)
        git(repo, "add", "-f", ".git/w2c/ledger/STATE.md", check=False)
        indexed = git(repo, "ls-files").stdout
        self.assertNotIn("w2c/ledger", indexed)

    def test_track_true_keeps_a_real_directory(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo, track=True)
        self.assertFalse((repo / ".w2c").is_symlink())
        self.assertTrue((repo / ".w2c" / "config.toml").is_file())
        self.assertFalse((repo / ".git" / "w2c" / "ledger").exists())

    def test_existing_store_does_not_clobber_a_real_ledger(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        store = (repo / ".w2c").resolve()
        (repo / ".w2c").unlink()
        real = repo / ".w2c"
        real.mkdir()
        (real / "STATE.md").write_text("local-copy\n", encoding="utf-8")
        code, _out, err = self.run_w2c(repo, "ledger-bind")
        self.assertEqual(code, 0, err)
        self.assertFalse((repo / ".w2c").is_symlink())
        self.assertIn("local-copy", (repo / ".w2c" / "STATE.md").read_text(encoding="utf-8"))
        self.assertTrue(store.is_dir())
        self.assertIn("left existing .w2c", err)

    def test_repo_layout_and_exclude_choice(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        code, out, err = self.run_w2c(repo, "repo-layout")
        self.assertEqual(code, 0, err)
        self.assertIn("layout: main-checkout", out)
        self.assertIn("exclude: missing", out)
        code, _out, err = self.run_w2c(
            repo, "worktree-add", "--branch", "kept-out", "--create-from", "HEAD", "--exclude", "no"
        )
        self.assertEqual(code, 0, err)
        exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertNotIn(".worktrees/", exclude)
        code, out, err = self.run_w2c(
            repo, "worktree-add", "--branch", "kept-in", "--create-from", "HEAD"
        )
        self.assertEqual(code, 0, err)
        exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn(".worktrees/", exclude)
        self.assertTrue((repo / ".worktrees" / "kept-in" / ".w2c").is_dir())
        self.assertFalse((repo / ".worktrees" / "kept-in" / ".w2c").is_symlink())

    def test_second_add_reuses_and_rejects_unsafe_paths(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        code, first, err = self.run_w2c(
            repo, "worktree-add", "--branch", "feature/login", "--create-from", "HEAD"
        )
        self.assertEqual(code, 0, err)
        code, second, err = self.run_w2c(repo, "worktree-add", "--branch", "feature/login")
        self.assertEqual(code, 0, err)
        self.assertEqual(first.strip(), second.strip())
        self.assertTrue((repo / ".worktrees" / "feature" / "login").is_dir())
        code, _out, err = self.run_w2c(repo, "worktree-add", "--branch", "a/../../x")
        self.assertEqual(code, 1)
        self.assertIn("safe directory", err)

    def test_busy_main_checkout_stops(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        git(repo, "checkout", "-b", "busy")
        code, _out, err = self.run_w2c(repo, "worktree-add", "--branch", "busy")
        self.assertEqual(code, 1)
        self.assertIn("main checkout", err)

    def test_symlink_mode_stays_a_pointer(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        w2c_local.write_repo_config(repo, worktree_ledger="symlink")
        code, out, err = self.run_w2c(
            repo, "worktree-add", "--branch", "linked", "--create-from", "HEAD"
        )
        self.assertEqual(code, 0, err)
        projection = Path(out.strip()) / ".w2c"
        self.assertTrue(projection.is_symlink())

    def test_worktree_edits_sync_to_the_main_symlink(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        code, out, err = self.run_w2c(
            repo, "worktree-add", "--branch", "feature-a", "--create-from", "HEAD"
        )
        self.assertEqual(code, 0, err)
        worktree = Path(out.strip())
        plan = worktree / ".w2c" / "plans" / "M001-demo"
        plan.mkdir(parents=True)
        (plan / "M001-ROADMAP.md").write_text(
            "| Remote branch | feature-a |\n",
            encoding="utf-8",
        )
        (plan / "M001-CONTEXT.md").write_text("from-worktree\n", encoding="utf-8")
        (repo / ".w2c" / "STATE.md").write_text("from-main\n", encoding="utf-8")
        code, _out, err = self.run_w2c(worktree, "ledger-bind")
        self.assertEqual(code, 0, err)
        synced = repo / ".w2c" / "plans" / "M001-demo" / "M001-CONTEXT.md"
        self.assertEqual(synced.read_text(encoding="utf-8"), "from-worktree\n")
        self.assertEqual((worktree / ".w2c" / "STATE.md").read_text(encoding="utf-8"), "from-main\n")

    def test_next_stays_on_the_current_branch(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        self._write_milestone(repo, "M001", "other", "OTHER")
        self._write_milestone(repo, "M002", "here", "main")
        code, out, err = self.run_w2c(repo, "next")
        self.assertEqual(code, 0, err)
        self.assertIn("NEXT M002", out)
        self.assertNotIn("NEXT M001", out)

    def test_remove_stops_when_tracked_file_is_modified(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        code, out, err = self.run_w2c(
            repo, "worktree-add", "--branch", "feature-a", "--create-from", "HEAD"
        )
        self.assertEqual(code, 0, err)
        worktree = Path(out.strip())
        (worktree / "README.md").write_text("dirty\n", encoding="utf-8")
        code, _out, err = self.run_w2c(repo, "worktree-remove", "--branch", "feature-a", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("not clean", err)
        self.assertTrue(worktree.is_dir())
        self.assertEqual(git(repo, "show-ref", "--verify", "refs/heads/feature-a").returncode, 0)
        self.assertTrue((repo / ".git" / "w2c" / "ledger" / "STATE.md").is_file())

    def test_remove_keeps_branch_and_store(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        code, _out, err = self.run_w2c(
            repo, "worktree-add", "--branch", "feature-a", "--create-from", "HEAD"
        )
        self.assertEqual(code, 0, err)
        code, _out, err = self.run_w2c(repo, "worktree-remove", "--branch", "feature-a", "--yes")
        self.assertEqual(code, 0, err)
        self.assertFalse((repo / ".worktrees" / "feature-a").exists())
        self.assertEqual(git(repo, "show-ref", "--verify", "refs/heads/feature-a").returncode, 0)
        self.assertTrue((repo / ".git" / "w2c" / "ledger" / "STATE.md").is_file())

    def test_openspec_commit_stays_off_the_main_branch(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        change = repo / "openspec" / "changes" / "demo"
        change.mkdir(parents=True)
        (change / "proposal.md").write_text("proposal\n", encoding="utf-8")
        code, out, err = self.run_w2c(
            repo, "worktree-add", "--branch", "DEMO-1", "--create-from", "HEAD"
        )
        self.assertEqual(code, 0, err)
        worktree = Path(out.strip())
        dest = worktree / "openspec" / "changes" / "demo"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(change), str(dest))
        git(worktree, "add", "openspec/changes/demo")
        git(worktree, "commit", "-qm", "add the change")
        self.assertEqual(git(repo, "branch", "--show-current").stdout.strip(), "main")
        self.assertFalse(change.exists())
        listed = git(worktree, "ls-tree", "-r", "--name-only", "HEAD").stdout
        self.assertIn("openspec/changes/demo/proposal.md", listed)
        self.assertNotIn(".w2c", listed)

    def test_bare_container_uses_a_sibling_directory(self) -> None:
        source = self.make_repo("source")
        container = self.tmp / "container"
        container.mkdir()
        subprocess.run(
            ["git", "clone", "--bare", str(source), str(container / ".bare")],
            check=True,
            capture_output=True,
            text=True,
        )
        (container / ".git").write_text("gitdir: ./.bare\n", encoding="utf-8")
        code, out, err = self.run_w2c(container, "repo-layout")
        self.assertEqual(code, 0, err)
        self.assertIn("layout: bare-container", out)
        code, out, err = self.run_w2c(container, "worktree-add", "--branch", "main")
        self.assertEqual(code, 0, err)
        self.assertEqual(Path(out.strip()).resolve(), (container / "main").resolve())
        self.assertFalse((container / ".worktrees").exists())

    def test_hooks_and_openspec_push_check(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        hooks = repo / ".git" / "hooks"
        hooks.mkdir(exist_ok=True)
        foreign = hooks / "pre-commit"
        foreign.write_text("#!/bin/sh\necho foreign\n", encoding="utf-8")
        foreign.chmod(0o755)
        code, _out, err = self.run_w2c(repo, "hook", "add", "deny-ledger")
        self.assertEqual(code, 1)
        self.assertIn("left it unchanged", err)
        self.assertIn("foreign", foreign.read_text(encoding="utf-8"))

        previous = hooks / "pre-push"
        previous.write_text("#!/bin/sh\necho previous\n", encoding="utf-8")
        previous.chmod(0o755)
        code, out, err = self.run_w2c(repo, "hook", "add", "openspec-archive")
        self.assertEqual(code, 0, err)
        self.assertIn("wrapped", out)
        self.assertIn("previous", (hooks / "pre-push.w2c-previous").read_text(encoding="utf-8"))
        self.assertIn("# w2c-hook: openspec-archive", (hooks / "pre-push").read_text(encoding="utf-8"))

        code, _out, err = self.run_w2c(repo, "hook", "add", "not-a-hook")
        self.assertEqual(code, 1)
        self.assertIn("unknown hook", err)

        self._write_openspec_milestone(repo, archive="declined", tasks_done=True)
        sha = git(repo, "rev-parse", "HEAD").stdout.strip()
        code, _out, err = self.run_w2c(
            repo,
            "openspec-push-check",
            "--local-ref",
            "refs/heads/main",
            "--local-sha",
            sha,
        )
        self.assertEqual(code, 1)
        self.assertIn("declined", err)

        self._write_openspec_milestone(repo, archive="", tasks_done=False)
        code, _out, err = self.run_w2c(
            repo,
            "openspec-push-check",
            "--local-ref",
            "refs/heads/main",
            "--local-sha",
            sha,
        )
        self.assertEqual(code, 0, err)

        archived = repo / "openspec" / "changes" / "archive" / "2026-10-30-demo"
        archived.mkdir(parents=True)
        (archived / ".openspec.yaml").write_text("schema: spec-driven\n", encoding="utf-8")
        git(repo, "add", "openspec")
        git(repo, "commit", "-qm", "archive the change")
        sha = git(repo, "rev-parse", "HEAD").stdout.strip()
        self._write_openspec_milestone(
            repo,
            archive="openspec/changes/archive/2026-10-30-demo",
            tasks_done=True,
        )
        code, _out, err = self.run_w2c(
            repo,
            "openspec-push-check",
            "--local-ref",
            "refs/heads/main",
            "--local-sha",
            sha,
        )
        self.assertEqual(code, 0, err)

        self._write_openspec_milestone(repo, archive="openspec/changes/demo", tasks_done=True, classic=True)
        code, _out, err = self.run_w2c(
            repo,
            "openspec-push-check",
            "--local-ref",
            "refs/heads/main",
            "--local-sha",
            sha,
        )
        self.assertEqual(code, 0, err)

    def test_legacy_push_check_unchanged(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo)
        self._write_openspec_milestone(repo, archive="declined", tasks_done=True)
        sha = git(repo, "rev-parse", "HEAD").stdout.strip()
        code, _out, err = self.run_w2c(
            repo, "openspec-push-check", "--local-ref", "refs/heads/main", "--local-sha", sha
        )
        self.assertEqual(code, 1)
        self.assertEqual(
            err.splitlines(),
            ["M001: OpenSpec archive is declined; run `w2c spec-archive M001` before push"],
        )
        other = self.make_repo("other")
        sha = git(other, "rev-parse", "HEAD").stdout.strip()
        code, out, err = self.run_w2c(
            other, "openspec-push-check", "--local-ref", "refs/heads/main", "--local-sha", sha
        )
        self.assertEqual((code, out, err), (0, "", ""))

    def test_cloud_change_in_linked_worktree_needs_no_ledger_sync(self) -> None:
        repo = self.make_repo()
        bindir = self.tmp / "bin"
        bindir.mkdir()
        dest = bindir / "openspec"
        dest.write_text(
            (Path(__file__).resolve().parent / "fixtures" / "fake_openspec.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        dest.chmod(0o755)
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = str(bindir) + os.pathsep + old
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old))
        linked = self.tmp / "linked"
        git(repo, "worktree", "add", "-q", "-b", "DEMO-1", str(linked))
        change = linked / "openspec" / "changes" / "add-export"
        change.mkdir(parents=True)
        (change / ".openspec.yaml").write_text(
            "schema: spec-driven\nx-delivery-status: TODO\nx-delivery-order: 1\n", encoding="utf-8"
        )
        (change / "tasks.md").write_text("## 1. Export\n\n- [ ] 1.1 Write it\n  - Verify: true\n", encoding="utf-8")
        code, out, err = self.run_w2c(linked, "cloud", "status")
        self.assertEqual(code, 0, err)
        self.assertIn("add-export: 0/1 tasks", out)
        code, out, _err = self.run_w2c(linked, "cloud", "smoke")
        self.assertIn("openspec-cli", out)
        self.assertFalse((linked / ".w2c").exists())
        self.assertFalse((repo / ".w2c").exists())
        self.assertEqual(
            w2c.openspec_ledger.change_prefixes(linked), ["openspec/changes/add-export"]
        )

    def test_milestone_new_installs_openspec_archive_hook(self) -> None:
        repo = self.make_repo()
        self.init_ledger(repo, planning="openspec")
        bindir = self.tmp / "bin"
        bindir.mkdir()
        fixture = Path(__file__).resolve().parent / "fixtures" / "fake_openspec.py"
        dest = bindir / "openspec"
        dest.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
        dest.chmod(0o755)
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = str(bindir) + os.pathsep + old
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old))
        code, _out, err = self.run_w2c(repo, "milestone-new", "--slug", "demo")
        self.assertEqual(code, 0, err)
        hook = (repo / ".git" / "hooks" / "pre-push").read_text(encoding="utf-8")
        self.assertIn("# w2c-hook: openspec-archive", hook)

    def test_help_prints_guides_without_bare_steps_in_skills(self) -> None:
        repo = self.make_repo()
        code, out, err = self.run_w2c(repo, "help", "worktrees")
        self.assertEqual(code, 0, err)
        self.assertIn("share one ledger", out)
        code, out, err = self.run_w2c(repo, "help", "bare-container")
        self.assertEqual(code, 0, err)
        self.assertIn("W2C will not run these steps", out)
        for name in ("work-to-chores", "do-chores"):
            skill = Path(__file__).resolve().parents[1] / "skills" / name / "SKILL.md"
            self.assertNotIn("git clone --bare", skill.read_text(encoding="utf-8"))

    def test_old_plan_commit_wording_still_passes_smoke_rules(self) -> None:
        problems = w2c.validate_git_operation_plan(
            {
                "Isolation mode": "branch",
                "Local branch": "DEMO-1",
                "Remote branch": "DEMO-1",
                "Plan commit": "required-before-isolation",
            }
        )
        self.assertEqual(problems, [])
        problems = w2c.validate_git_operation_plan(
            {
                "Isolation mode": "worktree",
                "Local branch": "DEMO-1",
                "Remote branch": "DEMO-1",
                "Worktree skill": "using-git-worktrees",
                "Base dirt policy": "n/a-worktree",
            }
        )
        self.assertEqual(problems, [])

    def _write_milestone(self, repo: Path, mid: str, slug: str, remote: str) -> None:
        plan = repo / ".w2c" / "plans" / f"{mid}-{slug}"
        plan.mkdir(parents=True)
        (plan / f"{mid}-ROADMAP.md").write_text(
            f"""# {mid}: {slug}

## Slices

- [ ] **S01: Foundation** `risk:low` `depends:[]`

## Git Operation Plan
| Field | Value |
| --- | --- |
| Isolation mode | branch |
| Local branch | {remote} |
| Remote branch | {remote} |
""",
            encoding="utf-8",
        )
        (plan / f"{mid}-S01-PLAN.md").write_text(
            f"""- [ ] **T01**: Task for {remote}.
  - Verify: true
""",
            encoding="utf-8",
        )
        road = repo / ".w2c" / "ROADMAP.md"
        text = road.read_text(encoding="utf-8")
        text += f"\n- 📋 **{mid}: {slug}** (`depends:[—]`)\n"
        road.write_text(text, encoding="utf-8")

    def _write_openspec_milestone(
        self,
        repo: Path,
        *,
        archive: str,
        tasks_done: bool,
        classic: bool = False,
    ) -> None:
        plan = repo / ".w2c" / "plans" / "M001-demo"
        plan.mkdir(parents=True, exist_ok=True)
        mode = "classic" if classic else "openspec"
        mark = "x" if tasks_done else " "
        (plan / "M001-ROADMAP.md").write_text(
            f"""# M001: demo

## Slices

- [x] **S01: Foundation** `risk:low` `depends:[]`

## Delivery & Guardrails
| Field | Value |
| --- | --- |
| Planning mode | {mode} |
| OpenSpec change | demo |
| OpenSpec archive | {archive} |

## Git Operation Plan
| Field | Value |
| --- | --- |
| Isolation mode | branch |
| Local branch | main |
| Remote branch | main |
""",
            encoding="utf-8",
        )
        change = repo / "openspec" / "changes" / "demo"
        change.mkdir(parents=True, exist_ok=True)
        (change / ".openspec.yaml").write_text("schema: spec-driven\n", encoding="utf-8")
        (change / "tasks.md").write_text(
            f"- [{mark}] 1.1 Finish the task.\n",
            encoding="utf-8",
        )
        road = repo / ".w2c" / "ROADMAP.md"
        body = road.read_text(encoding="utf-8")
        line = "- 📋 **M001: demo** (`depends:[—]`)\n"
        if line not in body:
            road.write_text(body + "\n" + line, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
