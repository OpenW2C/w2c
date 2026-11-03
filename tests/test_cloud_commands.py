#!/usr/bin/env python3
"""Core cloud commands: new, next, complete, slice-complete, archive, status."""

from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-cloud-cmd-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from w2c import cli as w2c  # noqa: E402
from w2c.cloud import ledger  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "fake_openspec.py"
ORIGINAL_PATH = os.environ.get("PATH", "")
CADENCE = sorted(ledger.CADENCES)[0]
NAME = "add-export"

DESIGN = """# Design

## Delivery Plan

| Field | Value |
| --- | --- |
| Remote branch | DEMO-1 |
"""

TASKS = """# Tasks

## 1. Export

**Goal:** export

- [ ] 1.1 Write exporter
  - Verify: true
- [ ] 1.2 Wire exporter
  - Verify: true

## 2. Docs

**Goal:** docs

- [ ] 2.1 Document it
  - Verify: true
"""


def run_main(root: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = w2c.main(["--root", str(root), *argv])
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=root, check=True, capture_output=True,
    )


class CloudCommandBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        bindir = Path(self._tmp.name) / "bin"
        bindir.mkdir()
        dest = bindir / "openspec"
        shutil.copy(FIXTURE, dest)
        dest.chmod(0o755)
        os.environ["PATH"] = str(bindir) + os.pathsep + ORIGINAL_PATH
        self.addCleanup(lambda: os.environ.__setitem__("PATH", ORIGINAL_PATH))
        git(self.root, "init", "-b", "DEMO-1")
        (self.root / "README.md").write_text("x\n", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "init")

    @property
    def change(self) -> Path:
        return self.root / "openspec" / "changes" / NAME

    def meta(self, folder: Path | None = None) -> str:
        return ((folder or self.change) / ".openspec.yaml").read_text(encoding="utf-8")

    def make(self, status: str = "TODO", name: str = NAME, order: int = 1, extra: str = "") -> Path:
        folder = self.root / "openspec" / "changes" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ".openspec.yaml").write_text(
            f"schema: spec-driven\nx-delivery-status: {status}\n"
            f"x-delivery-cadence: {CADENCE}\nx-delivery-order: {order}\n{extra}",
            encoding="utf-8",
        )
        (folder / "design.md").write_text(DESIGN, encoding="utf-8")
        (folder / "tasks.md").write_text(TASKS, encoding="utf-8")
        return folder

    def report(self, name: str, text: str = "done\n", folder: Path | None = None) -> None:
        path = (folder or self.change) / ".delivery" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def ok(self, *argv: str) -> str:
        code, out, err = run_main(self.root, *argv)
        self.assertEqual(code, 0, out + err)
        return out

    def bad(self, *argv: str) -> str:
        code, out, err = run_main(self.root, *argv)
        self.assertNotEqual(code, 0, out + err)
        return out + err



class SmokeAndPushTests(CloudCommandBase):
    def finished(self, **kw) -> Path:
        folder = self.make(extra="x-delivery-slices-done: [1, 2]\n", **kw)
        (folder / "tasks.md").write_text(TASKS.replace("- [ ]", "- [x]"), encoding="utf-8")
        return folder

    def push_check(self, sha: str | None = None) -> tuple[int, str]:
        sha = sha or subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True, check=True
        ).stdout.strip()
        code, out, err = run_main(
            self.root, "openspec-push-check", "--local-ref", "refs/heads/DEMO-1", "--local-sha", sha
        )
        return code, out + err

    def test_cloud_smoke_in_fresh_clone(self) -> None:
        self.make()
        code, out, _err = run_main(self.root, "cloud", "smoke")
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"(?m)^(PASS|FAIL) openspec-cli")
        self.assertRegex(out, r"(?m)^FAIL delivery-keys-valid|^FAIL design-sections")
        self.assertEqual(out.splitlines()[-1], "FAIL")
        self.assertFalse((self.root / ".w2c").exists())

    def test_cloud_smoke_change_filter(self) -> None:
        self.make(name="alpha-change", order=1)
        self.make(name="beta-change", order=2)
        code, out, _err = run_main(self.root, "cloud", "smoke", "--change", "alpha-change")
        self.assertEqual(code, 1, out)
        self.assertIn("alpha-change", out)
        self.assertNotIn("beta-change", out)
        code, out, _err = run_main(self.root, "cloud", "smoke")
        self.assertIn("beta-change", out)
        code, _out, err = run_main(self.root, "cloud", "smoke", "--change", "nope")
        self.assertNotEqual(code, 0)

    def test_push_check_requires_archived_cloud_change(self) -> None:
        self.finished()
        code, out = self.push_check()
        self.assertEqual(code, 1)
        self.assertIn(f"{NAME}: archive the change with w2c cloud archive {NAME} before push", out)
        shutil.rmtree(self.change)
        done = self.root / "openspec" / "changes" / "archive" / f"2026-11-02-{NAME}"
        done.mkdir(parents=True)
        (done / ".openspec.yaml").write_text(
            f"schema: spec-driven\nx-delivery-status: DONE\nx-delivery-cadence: {CADENCE}\n",
            encoding="utf-8",
        )
        (done / "design.md").write_text(DESIGN, encoding="utf-8")
        code, out = self.push_check()
        self.assertEqual(code, 1)
        self.assertIn(f"{NAME}: commit", out)
        self.assertIn("does not contain the archived change", out)
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "archive")
        code, out = self.push_check()
        self.assertEqual(code, 0, out)

    def test_push_check_fails_declined(self) -> None:
        folder = self.finished(status="DONE")
        with (folder / ".openspec.yaml").open("a", encoding="utf-8") as handle:
            handle.write("x-delivery-archive: declined\n")
        code, out = self.push_check()
        self.assertEqual(code, 1)
        self.assertIn(f"{NAME}: archive is declined; run w2c cloud archive {NAME} before push", out)

    def test_push_check_ignores_unfinished_and_other_branches(self) -> None:
        self.make()
        self.assertEqual(self.push_check()[0], 0)
        folder = self.finished(name="other")
        (folder / "design.md").write_text(DESIGN.replace("DEMO-1", "OTHER-2"), encoding="utf-8")
        self.assertEqual(self.push_check()[0], 0)

    def test_unreadable_change_blocks_only_its_own_branch(self) -> None:
        dup = self.make(name="broken", order=2, extra="x-delivery-status: DONE\n")
        (dup / "design.md").write_text(DESIGN.replace("DEMO-1", "OTHER-2"), encoding="utf-8")
        bad = self.make(name="binary", order=3)
        (bad / "design.md").write_text(DESIGN.replace("DEMO-1", "OTHER-2"), encoding="utf-8")
        (bad / ".openspec.yaml").write_bytes(b"\xff\xfe\x00bad")
        code, out = self.push_check()
        self.assertEqual((code, out), (0, ""))
        (dup / "design.md").write_text(DESIGN, encoding="utf-8")
        code, out = self.push_check()
        self.assertEqual(code, 1)
        self.assertIn("broken: cannot read .openspec.yaml:", out)
        self.assertNotIn("Traceback", out)

    def test_base_dirt_skips_unreadable_cloud_change(self) -> None:
        from w2c import openspec_ledger

        self.make()
        bad = self.make(name="broken", order=2, extra="x-delivery-status: DONE\n")
        other = self.make(name="binary", order=3)
        (other / ".openspec.yaml").write_bytes(b"\xff\xfe\x00bad")
        self.assertEqual(openspec_ledger.change_prefixes(self.root), [f"openspec/changes/{NAME}"])

    def test_cloud_moved_ignores_non_milestone_ids(self) -> None:
        plan = self.root / ".w2c" / "plans" / "M007-old"
        plan.mkdir(parents=True)
        (self.root / ".w2c" / "ROADMAP.md").write_text("# Roadmap\n", encoding="utf-8")
        (plan / "CONVERTED").write_text(f"{NAME}\n", encoding="utf-8")
        out = self.ok("next", "--milestone", "M*")
        self.assertNotIn("CLOUD_MOVED", out)

    def test_base_dirt_skips_cloud_change_folder(self) -> None:
        from w2c import base_dirt, openspec_ledger

        folder = self.make()
        (folder / "exporter.py").write_text("print(1)\n", encoding="utf-8")
        done = self.make(name="finished", status="DONE", order=2)
        (done / "kept.py").write_text("print(2)\n", encoding="utf-8")
        (self.root / "NOTES.md").write_text("local\n", encoding="utf-8")
        prefixes = openspec_ledger.change_prefixes(self.root)
        self.assertEqual(prefixes, [f"openspec/changes/{NAME}"])
        report = base_dirt.scan_base_dirt(str(self.root), extra_prefixes=prefixes)
        self.assertNotIn(f"openspec/changes/{NAME}/exporter.py", report.critical + report.other)
        self.assertIn("NOTES.md", report.other)

    def test_cloud_moved_message(self) -> None:
        w2c_dir = self.root / ".w2c"
        (w2c_dir / "plans" / "M007-old").mkdir(parents=True)
        (w2c_dir / "ROADMAP.md").write_text("# Roadmap\n", encoding="utf-8")
        (w2c_dir / "plans" / "M007-old" / "CONVERTED").write_text(f"{NAME}\n", encoding="utf-8")
        out = self.ok("next", "--milestone", "M007")
        self.assertEqual(out, f"CLOUD_MOVED M007 {NAME}\n")
        out = self.ok("next", "--milestone", "M008")
        self.assertEqual(out.splitlines()[0], "NEXT none")
        out = self.ok("next")
        self.assertEqual(out.splitlines()[0], "NEXT none")
        (w2c_dir / "ROADMAP.md").write_text("# Roadmap\n\n- \U0001F4CB **M007: old** (`depends:[\u2014]`)\n", encoding="utf-8")
        out = self.ok("next", "--milestone", "M007")
        self.assertNotIn("CLOUD_MOVED", out)

    def test_new_installs_pre_push_hook_only_in_git(self) -> None:
        self.ok("cloud", "new", "--slug", NAME, "--cadence", CADENCE)
        hook = (self.root / ".git" / "hooks" / "pre-push").read_text(encoding="utf-8")
        self.assertIn("# w2c-hook: openspec-archive", hook)
        plain = Path(self._tmp.name) / "plain"
        plain.mkdir()
        code, out, err = run_main(plain, "cloud", "new", "--slug", "other", "--cadence", CADENCE)
        self.assertEqual(code, 0, out + err)
        self.assertFalse((plain / ".git").exists())

class NewTests(CloudCommandBase):
    def test_new_writes_keys_and_no_ledger_files(self) -> None:
        self.make(name="older", order=4)
        out = self.ok("cloud", "new", "--slug", NAME, "--cadence", CADENCE)
        self.assertIn(f"created openspec/changes/{NAME} ({NAME})", out)
        meta = self.meta()
        self.assertIn("x-delivery-status: PLANNING", meta)
        self.assertIn("x-delivery-order: 5", meta)
        self.assertIn(f"x-delivery-cadence: {CADENCE}", meta)
        self.assertFalse((self.root / ".w2c").exists())

    def test_new_without_cadence_prints_need_cadence(self) -> None:
        code, out, _err = run_main(self.root, "cloud", "new", "--slug", NAME)
        self.assertEqual(code, 1)
        self.assertIn("NEED_CADENCE", out)
        self.assertFalse(self.change.exists())

    def test_new_takes_cadence_from_local_config(self) -> None:
        (self.root / ".w2c").mkdir()
        (self.root / ".w2c" / "config.toml").write_text(
            f'git_delivery = "{CADENCE}"\n', encoding="utf-8"
        )
        self.ok("cloud", "new", "--slug", NAME)
        self.assertIn(f"x-delivery-cadence: {CADENCE}", self.meta())

    def test_new_rejects_bad_cadence_in_local_config(self) -> None:
        (self.root / ".w2c").mkdir()
        (self.root / ".w2c" / "config.toml").write_text('git_delivery = "hourly"\n', encoding="utf-8")
        code, out, _err = run_main(self.root, "cloud", "new", "--slug", NAME)
        self.assertNotEqual(code, 0)
        self.assertFalse(self.change.exists())

    def test_new_resolves_relative_metadata_path_against_root(self) -> None:
        script = Path(self._tmp.name) / "bin" / "openspec"
        script.write_text(
            "#!/usr/bin/env python3\nimport json, sys\nfrom pathlib import Path\n"
            "name = sys.argv[3]\nd = Path('openspec/changes') / name\nd.mkdir(parents=True)\n"
            "(d / '.openspec.yaml').write_text('schema: spec-driven\\n')\n"
            "print(json.dumps({'change': {'metadataPath': str(d / '.openspec.yaml')}}))\n",
            encoding="utf-8",
        )
        elsewhere = Path(self._tmp.name) / "elsewhere"
        elsewhere.mkdir()
        old = os.getcwd()
        os.chdir(elsewhere)
        self.addCleanup(lambda: os.chdir(old))
        self.ok("cloud", "new", "--slug", NAME, "--cadence", CADENCE)
        self.assertIn("x-delivery-status: PLANNING", self.meta())
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_new_rejects_unknown_cadence(self) -> None:
        self.bad("cloud", "new", "--slug", NAME, "--cadence", "hourly")
        self.assertFalse(self.change.exists())

    def test_new_creates_knowledge_once(self) -> None:
        self.ok("cloud", "new", "--slug", NAME, "--cadence", CADENCE)
        knowledge = self.root / "openspec" / "knowledge.md"
        text = knowledge.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Project Knowledge"))
        for heading in ("## Rules", "## Patterns", "## Lessons Learned"):
            self.assertIn(heading, text)
        self.assertNotIn("w2c", text.lower())
        attrs = (self.root / ".gitattributes").read_text(encoding="utf-8")
        self.assertEqual(attrs.count("openspec/knowledge.md merge=union"), 1)
        knowledge.write_text("custom\n", encoding="utf-8")
        self.ok("cloud", "new", "--slug", "second", "--cadence", CADENCE)
        self.assertEqual(knowledge.read_text(encoding="utf-8"), "custom\n")
        attrs = (self.root / ".gitattributes").read_text(encoding="utf-8")
        self.assertEqual(attrs.count("openspec/knowledge.md merge=union"), 1)
        self.assertIn("x-delivery-order: 2", self.meta(self.root / "openspec/changes/second"))


class NextCompleteTests(CloudCommandBase):
    def test_next_and_complete_in_fresh_clone(self) -> None:
        self.make()
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "plan")
        clone = Path(self._tmp.name) / "clone"
        subprocess.run(["git", "clone", "-q", str(self.root), str(clone)], check=True)
        out = run_main(clone, "cloud", "next")[1]
        self.assertIn(f"NEXT {NAME} S01 T01", out)
        self.assertIn("Write exporter", out)
        self.assertIn('"milestone_id"', out)
        refused = run_main(clone, "cloud", "complete", "--change", NAME, "--slice", "S01", "--task", "T01")
        self.assertNotEqual(refused[0], 0)
        self.assertIn("missing report S01-T01-SUMMARY.md", refused[2])
        self.report("S01-T01-SUMMARY.md", folder=clone / "openspec/changes" / NAME)
        code, out, err = run_main(clone, "cloud", "complete", "--change", NAME, "--slice", "S01", "--task", "T01")
        self.assertEqual(code, 0, err)
        self.assertIn(f"complete {NAME} S01 T01", out)
        self.assertIn("OPEN_IN_SLICE 1", out)
        self.assertIn("- [x] 1.1", (clone / "openspec/changes" / NAME / "tasks.md").read_text(encoding="utf-8"))
        self.assertIn("x-delivery-status: INPROGRESS", self.meta(clone / "openspec/changes" / NAME))
        self.assertIn(f"NEXT {NAME} S01 T02", run_main(clone, "cloud", "next")[1])
        self.assertFalse((clone / ".w2c").exists())
        self.assertFalse((self.root / ".w2c").exists())

    def test_complete_twice_and_dropped_refuse(self) -> None:
        self.make()
        text = (self.change / "tasks.md").read_text(encoding="utf-8").replace("[ ] 1.2", "[d] 1.2")
        (self.change / "tasks.md").write_text(text, encoding="utf-8")
        self.report("S01-T01-SUMMARY.md")
        self.report("S01-T02-SUMMARY.md")
        self.ok("cloud", "complete", "--change", NAME, "--slice", "S01", "--task", "T01")
        self.assertIn("already complete", self.bad("cloud", "complete", "--change", NAME, "--slice", "S01", "--task", "T01"))
        self.assertIn("is dropped", self.bad("cloud", "complete", "--change", NAME, "--slice", "S01", "--task", "T02"))

    def test_next_prefers_inprogress_and_skips_done_and_locked(self) -> None:
        self.make(status="TODO", name="alpha", order=1)
        self.make(status="INPROGRESS", name="beta", order=2)
        self.make(status="PAUSED", name="gamma", order=3)
        for name in ("alpha", "beta", "gamma"):
            (self.root / "openspec/changes" / name / "design.md").write_text(DESIGN, encoding="utf-8")
        self.assertIn("NEXT beta S01 T01", self.ok("cloud", "next"))
        self.assertIn("NEXT alpha S01 T01", self.ok("cloud", "next", "--change", "alpha"))
        meta = self.root / "openspec/changes/beta/.openspec.yaml"
        ledger.write_key(meta, "x-delivery-amend-lock", "set")
        self.assertIn("NEXT alpha S01 T01", self.ok("cloud", "next"))
        code, out, _ = run_main(self.root, "cloud", "next", "--change", "beta")
        self.assertEqual(code, 1)
        self.assertIn("AMEND_LOCK beta", out)

    def test_next_stays_on_the_current_branch(self) -> None:
        self.make(name="mine", order=2)
        self.make(name="other", order=1)
        (self.root / "openspec/changes/other/design.md").write_text(
            DESIGN.replace("DEMO-1", "OTHER-9"), encoding="utf-8"
        )
        self.assertIn("NEXT mine S01 T01", self.ok("cloud", "next"))
        self.assertIn("NEXT other S01 T01", self.ok("cloud", "next", "--change", "other"))

    def test_next_none_when_everything_is_ticked(self) -> None:
        self.make()
        text = (self.change / "tasks.md").read_text(encoding="utf-8").replace("[ ]", "[x]")
        (self.change / "tasks.md").write_text(text, encoding="utf-8")
        self.assertIn("NEXT none", self.ok("cloud", "next"))


class SliceCompleteTests(CloudCommandBase):
    def finish_slice_one(self) -> None:
        for tid in ("T01", "T02"):
            self.report(f"S01-{tid}-SUMMARY.md")
            self.ok("cloud", "complete", "--change", NAME, "--slice", "S01", "--task", tid)

    def test_slice_complete_records_slices_done_and_tokens(self) -> None:
        self.make()
        self.finish_slice_one()
        self.assertIn("missing report S01-UAT.md", self.bad("cloud", "slice-complete", "--change", NAME, "--slice", "S01"))
        self.report("S01-UAT.md")
        self.report("S01-SUMMARY.md")
        out = self.ok("cloud", "slice-complete", "--change", NAME, "--slice", "S01")
        self.assertIn(f"slice-complete {NAME} S01", out)
        self.assertIn("OPEN_SLICES 1", out)
        self.assertIn("x-delivery-slices-done: [1]", self.meta())
        self.report("S02-T01-SUMMARY.md")
        self.ok("cloud", "complete", "--change", NAME, "--slice", "S02", "--task", "T01")
        self.report("S02-UAT.md")
        self.report("S02-SUMMARY.md")
        out = self.ok("cloud", "slice-complete", "--change", NAME, "--slice", "S02")
        self.assertIn(f"NEED_MILESTONE_REPORTS {NAME}", out)
        self.assertIn("x-delivery-slices-done: [1, 2]", self.meta())
        self.report("VALIDATION.md")
        self.report("SUMMARY.md")
        self.ok("cloud", "slice-complete", "--change", NAME, "--slice", "S02")
        self.assertIn("x-delivery-slices-done: [1, 2]", self.meta())

    def test_slice_complete_refuses_open_tasks(self) -> None:
        self.make()
        self.assertIn("open tasks remain", self.bad("cloud", "slice-complete", "--change", NAME, "--slice", "S01"))


class CloseoutTests(CloudCommandBase):
    def finish_all(self) -> None:
        for sid, tids in (("S01", ("T01", "T02")), ("S02", ("T01",))):
            for tid in tids:
                self.report(f"{sid}-{tid}-SUMMARY.md")
                self.ok("cloud", "complete", "--change", NAME, "--slice", sid, "--task", tid)
            self.report(f"{sid}-UAT.md")
            self.report(f"{sid}-SUMMARY.md")
            self.ok("cloud", "slice-complete", "--change", NAME, "--slice", sid)

    def test_archive_gates_then_deletes_delivery_and_marks_done(self) -> None:
        self.make()
        self.assertIn("open", self.bad("cloud", "archive", NAME).lower())
        self.finish_all()
        self.assertIn("VALIDATION.md", self.bad("cloud", "archive", NAME))
        self.report("VALIDATION.md")
        self.assertIn("SUMMARY.md", self.bad("cloud", "archive", NAME))
        self.report("SUMMARY.md")
        out = self.ok("cloud", "archive", NAME)
        self.assertIn(f"archived {NAME} as 2026-10-18-{NAME}", out)
        archived = self.root / "openspec/changes/archive" / f"2026-10-18-{NAME}"
        self.assertFalse((archived / ".delivery").exists())
        self.assertIn("x-delivery-status: DONE", self.meta(archived))
        self.assertNotIn("archive:", self.meta(archived))
        self.assertIn("already", self.bad("cloud", "archive", NAME))
        self.assertIn(f"{NAME} -> DONE", self.ok("cloud", "milestone-complete", NAME))
        self.assertFalse((self.root / ".w2c").exists())

    def test_archive_refuses_unlisted_group(self) -> None:
        self.make()
        self.finish_all()
        self.report("VALIDATION.md")
        self.report("SUMMARY.md")
        ledger.write_key(self.change / ".openspec.yaml", "x-delivery-slices-done", "[1]")
        self.assertIn("S02", self.bad("cloud", "archive", NAME))
        self.assertTrue((self.change / ".delivery").is_dir())

    def test_milestone_complete_declined_keeps_reports(self) -> None:
        self.make()
        self.finish_all()
        self.assertIn(f"run w2c cloud archive {NAME} or pass --archive-declined",
                      self.bad("cloud", "milestone-complete", NAME))
        self.assertIn("VALIDATION.md", self.bad("cloud", "milestone-complete", NAME, "--archive-declined"))
        self.report("VALIDATION.md")
        self.report("SUMMARY.md")
        out = self.ok("cloud", "milestone-complete", NAME, "--archive-declined")
        self.assertIn(
            f"OPENSPEC_ARCHIVE_DECLINED {NAME} follow-up: archive the change with w2c cloud archive {NAME}", out
        )
        meta = self.meta()
        self.assertIn("x-delivery-status: DONE", meta)
        self.assertIn("x-delivery-archive: declined", meta)
        self.assertTrue((self.change / ".delivery" / "SUMMARY.md").is_file())

    def test_archive_accepts_declined_done_and_clears_marker(self) -> None:
        self.make()
        self.finish_all()
        self.report("VALIDATION.md")
        self.report("SUMMARY.md")
        self.ok("cloud", "milestone-complete", NAME, "--archive-declined")
        self.ok("cloud", "archive", NAME)
        archived = self.root / "openspec/changes/archive" / f"2026-10-18-{NAME}"
        self.assertNotIn("x-delivery-archive", self.meta(archived))
        self.assertIn("x-delivery-status: DONE", self.meta(archived))
        self.assertFalse((archived / ".delivery").exists())

    def test_archive_refuses_plain_done(self) -> None:
        self.make(status="DONE")
        self.assertIn("already DONE", self.bad("cloud", "archive", NAME))

    def test_archive_refuses_open_task_in_listed_group(self) -> None:
        self.make()
        self.finish_all()
        self.report("VALIDATION.md")
        self.report("SUMMARY.md")
        tasks = self.change / "tasks.md"
        tasks.write_text(
            tasks.read_text(encoding="utf-8").replace(
                "## 2. Docs", "- [ ] 1.3 Late task\n\n## 2. Docs"
            ),
            encoding="utf-8",
        )
        self.assertIn("S01", self.bad("cloud", "archive", NAME))
        self.assertTrue((self.change / ".delivery" / "SUMMARY.md").is_file())

    def test_archive_accepts_all_dropped_group_without_listing(self) -> None:
        self.make()
        for tid in ("T01", "T02"):
            self.report(f"S01-{tid}-SUMMARY.md")
            self.ok("cloud", "complete", "--change", NAME, "--slice", "S01", "--task", tid)
        self.report("S01-UAT.md")
        self.report("S01-SUMMARY.md")
        self.ok("cloud", "slice-complete", "--change", NAME, "--slice", "S01")
        tasks = self.change / "tasks.md"
        tasks.write_text(tasks.read_text(encoding="utf-8").replace("[ ] 2.1", "[d] 2.1"), encoding="utf-8")
        self.report("VALIDATION.md")
        self.report("SUMMARY.md")
        self.ok("cloud", "archive", NAME)
        self.assertTrue((self.root / "openspec/changes/archive" / f"2026-10-18-{NAME}").is_dir())

    def test_unlisted_finished_group_blocks_archive(self) -> None:
        self.make()
        self.finish_all()
        self.report("VALIDATION.md")
        self.report("SUMMARY.md")
        ledger.write_key(self.change / ".openspec.yaml", "x-delivery-slices-done", "[]")
        self.bad("cloud", "archive", NAME)

    def test_failed_archive_restores_reports_and_status(self) -> None:
        self.make()
        self.finish_all()
        self.report("VALIDATION.md")
        self.report("SUMMARY.md")
        before = sorted(p.name for p in (self.change / ".delivery").iterdir())
        os.environ["FAKE_OPENSPEC_ARCHIVE"] = "fail"
        self.addCleanup(lambda: os.environ.pop("FAKE_OPENSPEC_ARCHIVE", None))
        message = self.bad("cloud", "archive", NAME)
        self.assertIn("archive blew up", message)
        self.assertEqual(sorted(p.name for p in (self.change / ".delivery").iterdir()), before)
        self.assertIn("x-delivery-status: INPROGRESS", self.meta())

    def test_archive_failing_after_the_move_keeps_the_backup(self) -> None:
        self.make()
        self.finish_all()
        self.report("VALIDATION.md")
        self.report("SUMMARY.md")
        os.environ["FAKE_OPENSPEC_ARCHIVE"] = "move-then-fail"
        self.addCleanup(lambda: os.environ.pop("FAKE_OPENSPEC_ARCHIVE", None))
        message = self.bad("cloud", "archive", NAME)
        self.assertFalse(self.change.exists())
        self.assertIn("moved into the archive", message)
        match = re.search(r"kept in (\S+)", message)
        self.assertIsNotNone(match, message)
        backup = Path(match.group(1))
        self.addCleanup(lambda: shutil.rmtree(backup, ignore_errors=True))
        self.assertTrue((backup / ".delivery" / "SUMMARY.md").is_file())

    def test_failed_archive_keeps_declined_marker(self) -> None:
        self.make()
        self.finish_all()
        self.report("VALIDATION.md")
        self.report("SUMMARY.md")
        self.ok("cloud", "milestone-complete", NAME, "--archive-declined")
        os.environ["FAKE_OPENSPEC_ARCHIVE"] = "fail"
        self.addCleanup(lambda: os.environ.pop("FAKE_OPENSPEC_ARCHIVE", None))
        self.bad("cloud", "archive", NAME)
        self.assertIn("x-delivery-archive: declined", self.meta())
        self.assertIn("x-delivery-status: DONE", self.meta())
        self.assertTrue((self.change / ".delivery" / "SUMMARY.md").is_file())

    def test_complete_and_slice_complete_refuse_done(self) -> None:
        self.make(status="DONE", extra="x-delivery-archive: declined\n")
        self.report("S01-T01-SUMMARY.md")
        self.assertIn("already DONE", self.bad("cloud", "complete", "--change", NAME, "--slice", "S01", "--task", "T01"))
        self.assertIn("already DONE", self.bad("cloud", "slice-complete", "--change", NAME, "--slice", "S01"))
        self.assertIn("- [ ] 1.1", (self.change / "tasks.md").read_text(encoding="utf-8"))

    def test_status_set(self) -> None:
        self.make()
        self.ok("cloud", "status-set", NAME, "paused")
        self.assertIn("x-delivery-status: PAUSED", self.meta())
        self.assertIn("DONE", self.bad("cloud", "status-set", NAME, "DONE"))
        self.bad("cloud", "status-set", NAME, "BOGUS")


class StatusTests(CloudCommandBase):
    def test_status_lines_and_next(self) -> None:
        self.make()
        out = self.ok("cloud", "status")
        self.assertIn(f"{w2c.STATUS_EMOJI['TODO']} {NAME}: 0/3 tasks", out)
        self.assertIn(f"Next: {NAME} S01 T01: Write exporter", out)
        text = (self.change / "tasks.md").read_text(encoding="utf-8").replace("[ ]", "[x]")
        (self.change / "tasks.md").write_text(text, encoding="utf-8")
        out = self.ok("cloud", "status")
        self.assertIn(f"{NAME}: 3/3 tasks", out)
        self.assertIn("Next: none", out)
        self.assertFalse((self.root / ".w2c").exists())

    def test_status_all_prints_cloud_view_then_local_state(self) -> None:
        self.make()
        (self.root / ".w2c").mkdir()
        (self.root / ".w2c" / "STATE.md").write_text("# State\n\nActive milestone: M002\n", encoding="utf-8")
        plain = self.ok("cloud", "status")
        self.assertNotIn("Active milestone: M002", plain)
        out = self.ok("cloud", "status", "--all")
        cloud_line = f"{NAME}: 0/3 tasks"
        self.assertIn(cloud_line, out)
        self.assertIn("Active milestone: M002", out)
        self.assertLess(out.index(cloud_line), out.index("# State"))


class RulesTests(unittest.TestCase):
    def test_rules_prints_the_config_snippet(self) -> None:
        from w2c.cloud import layout

        code, out, err = run_main(Path(tempfile.gettempdir()), "cloud", "rules")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, layout.CONFIG_RULES_SNIPPET)
        for marker in (layout.DESIGN_MARKER, layout.SLICE_TASK_MARKER, layout.READ_FIRST_MARKER):
            self.assertIn(marker, out)


class LegacyIsolationTests(CloudCommandBase):
    def test_legacy_commands_ignore_cloud_changes(self) -> None:
        self.make()
        (self.root / ".w2c").mkdir()
        (self.root / ".w2c" / "ROADMAP.md").write_text("# Roadmap\n\n## Milestones\n", encoding="utf-8")
        out = self.ok("next")
        self.assertIn("NEXT none", out)


HEADER = "| # | When | Scope | Decision | Choice | Rationale | Revisable? | Made By |"
DESIGN_DECISIONS = DESIGN + "\n## Decisions\n\n## Manual Test Guide\n\nkeep\n"


class DecisionTests(CloudCommandBase):
    def args(self, scope: str, *extra: str) -> list[str]:
        return ["cloud", "decide", "--scope", scope, "--decision", "d", "--choice", "c",
                "--rationale", "why", *extra]

    def test_decide_before_design_is_pending_then_flushed_in_order(self) -> None:
        folder = self.make()
        (folder / "design.md").unlink()
        self.assertEqual(self.ok(*self.args("one")).strip(), "PENDING")
        self.assertEqual(self.ok(*self.args("two a|b", "--change", NAME)).strip(), "PENDING")
        pending = self.root / ".w2c" / "runtime" / "pending-decisions.jsonl"
        self.assertEqual(len(pending.read_text(encoding="utf-8").splitlines()), 2)
        self.bad("cloud", "decisions-flush", "--change", NAME)
        self.assertEqual(len(pending.read_text(encoding="utf-8").splitlines()), 2)
        (folder / "design.md").write_text(DESIGN_DECISIONS, encoding="utf-8")
        self.assertIn("2 flushed", self.ok("cloud", "decisions-flush", "--change", NAME))
        text = (folder / "design.md").read_text(encoding="utf-8")
        self.assertIn(HEADER, text)
        self.assertLess(text.index("| D1 |"), text.index("| D2 |"))
        self.assertIn("two a\\|b", text)
        self.assertLess(text.index("| D2 |"), text.index("## Manual Test Guide"))
        self.assertFalse(pending.exists())
        self.assertIn("0 flushed", self.ok("cloud", "decisions-flush", "--change", NAME))

    def test_decide_with_design_appends_next_id(self) -> None:
        folder = self.make()
        (folder / "design.md").write_text(DESIGN_DECISIONS, encoding="utf-8")
        self.assertEqual(self.ok(*self.args("a", "--change", NAME)).strip(), "D1")
        self.assertEqual(self.ok(*self.args("b\nline", "--change", NAME)).strip(), "D2")
        text = (folder / "design.md").read_text(encoding="utf-8")
        self.assertEqual(text.count(HEADER), 1)
        self.assertIn("b line", text)
        self.assertLess(text.index("| D2 |"), text.index("## Manual Test Guide"))
        self.assertTrue(text.endswith("keep\n"))
        self.assertFalse((self.root / ".w2c").exists())

    def test_flush_refuses_without_decisions_section(self) -> None:
        self.make()
        self.ok(*self.args("x"))
        before = (self.change / "design.md").read_text(encoding="utf-8")
        self.bad("cloud", "decisions-flush", "--change", NAME)
        self.assertEqual((self.change / "design.md").read_text(encoding="utf-8"), before)
        pending = self.root / ".w2c" / "runtime" / "pending-decisions.jsonl"
        self.assertEqual(len(pending.read_text(encoding="utf-8").splitlines()), 1)

    def pending(self) -> Path:
        return self.root / ".w2c" / "runtime" / "pending-decisions.jsonl"

    def test_interrupted_flush_leftover_refuses_and_decide_still_pends(self) -> None:
        folder = self.make()
        (folder / "design.md").write_text(DESIGN_DECISIONS, encoding="utf-8")
        self.ok(*self.args("one"))
        left = self.pending().with_name("pending-decisions.flushing.jsonl")
        left.write_text('{"scope": "old"}\n', encoding="utf-8")
        err = self.bad("cloud", "decisions-flush", "--change", NAME)
        self.assertIn("pending-decisions.flushing.jsonl", err)
        self.assertIn("interrupted", err)
        self.assertEqual((folder / "design.md").read_text(encoding="utf-8"), DESIGN_DECISIONS)
        self.ok(*self.args("two"))
        self.assertEqual(len(self.pending().read_text(encoding="utf-8").splitlines()), 2)
        left.unlink()
        self.assertIn("2 flushed", self.ok("cloud", "decisions-flush", "--change", NAME))

    def test_malformed_pending_line_names_line_and_keeps_rows(self) -> None:
        folder = self.make()
        (folder / "design.md").write_text(DESIGN_DECISIONS, encoding="utf-8")
        self.ok(*self.args("one"))
        with open(self.pending(), "a", encoding="utf-8") as handle:
            handle.write("not json\n")
        before = self.pending().read_text(encoding="utf-8")
        err = self.bad("cloud", "decisions-flush", "--change", NAME)
        self.assertIn("line 2", err)
        self.assertEqual(self.pending().read_text(encoding="utf-8"), before)
        self.assertFalse(self.pending().with_name("pending-decisions.flushing.jsonl").exists())
        self.assertEqual((folder / "design.md").read_text(encoding="utf-8"), DESIGN_DECISIONS)
        self.pending().write_text('{"scope": "a"}\n[1]\n', encoding="utf-8")
        self.assertIn("line 2", self.bad("cloud", "decisions-flush", "--change", NAME))

    def test_pending_without_trailing_newline(self) -> None:
        folder = self.make()
        (folder / "design.md").write_text(DESIGN_DECISIONS, encoding="utf-8")
        self.pending().parent.mkdir(parents=True)
        self.pending().write_text('{"scope": "a"}', encoding="utf-8")
        self.ok(*self.args("b"))
        self.assertIn("2 flushed", self.ok("cloud", "decisions-flush", "--change", NAME))

    def test_decisions_section_last_with_subheadings_and_prose(self) -> None:
        folder = self.make()
        design = DESIGN + "\n## Decisions\n\nIntro prose.\n\n### Notes\n\nMore prose.\n"
        (folder / "design.md").write_text(design, encoding="utf-8")
        self.assertEqual(self.ok(*self.args("a", "--change", NAME)).strip(), "D1")
        text = (folder / "design.md").read_text(encoding="utf-8")
        self.assertTrue(text.rstrip().endswith("|"))
        self.assertIn("More prose.", text)
        self.assertEqual(self.ok(*self.args("b", "--change", NAME)).strip(), "D2")
        self.assertEqual((folder / "design.md").read_text(encoding="utf-8").count(HEADER), 1)

    def test_existing_table_followed_by_prose(self) -> None:
        folder = self.make()
        table = HEADER + "\n|---|\n| D1 | w | s | d | c | r | Yes | me |\n"
        design = DESIGN + "\n## Decisions\n\n" + table + "\nAfter prose.\n\n## Other\n"
        (folder / "design.md").write_text(design, encoding="utf-8")
        self.assertEqual(self.ok(*self.args("a", "--change", NAME)).strip(), "D2")
        text = (folder / "design.md").read_text(encoding="utf-8")
        self.assertLess(text.index("| D2 |"), text.index("After prose."))
        self.assertLess(text.index("| D1 |"), text.index("| D2 |"))


class ReorderTests(CloudCommandBase):
    def order_of(self, name: str) -> str:
        return re.search(r"x-delivery-order: (\d+)", self.meta(self.root / "openspec" / "changes" / name)).group(1)

    def test_reorder_rewrites_order_keys_and_refuses_inprogress(self) -> None:
        self.make(name="a", order=3)
        self.make(name="b", order=7)
        self.make(name="c", order=9)
        self.ok("cloud", "order", "c", "a", "b")
        self.assertEqual([self.order_of(n) for n in "abc"], ["2", "3", "1"])
        self.ok("cloud", "swap", "a", "b")
        self.assertEqual([self.order_of(n) for n in "abc"], ["3", "2", "1"])
        self.ok("cloud", "move", "a", "--before", "c")
        self.assertEqual([self.order_of(n) for n in "abc"], ["1", "3", "2"])
        self.ok("cloud", "move", "a", "--after", "b")
        self.assertEqual([self.order_of(n) for n in "abc"], ["3", "2", "1"])
        self.assertFalse((self.root / ".w2c").exists())
        self.make(name="run", status="INPROGRESS", order=0)
        before = self.meta(self.root / "openspec" / "changes" / "a")
        self.bad("cloud", "swap", "run", "a")
        self.bad("cloud", "order", "a", "run", "b", "c")
        self.bad("cloud", "swap", "a", "nope")
        self.assertEqual(self.meta(self.root / "openspec" / "changes" / "a"), before)

    def test_locked_change_leaves_every_order_key_untouched(self) -> None:
        self.make(name="a", order=1)
        self.make(name="b", order=2)
        self.make(name="c", order=3, extra="x-delivery-amend-lock: held\n")
        before = [self.order_of(n) for n in "abc"]
        self.bad("cloud", "order", "c", "b", "a")
        self.assertEqual([self.order_of(n) for n in "abc"], before)


if __name__ == "__main__":
    unittest.main()
