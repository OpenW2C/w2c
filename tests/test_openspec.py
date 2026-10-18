#!/usr/bin/env python3
"""OpenSpec planning mode: fake CLI plus one real-CLI integration test."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-openspec-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from w2c import cli as w2c  # noqa: E402
from w2c import local as w2c_local  # noqa: E402
from w2c import openspec as osp  # noqa: E402
from w2c import base_dirt  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fake_openspec.py"
REAL_OPENSPEC = shutil.which("openspec")
ORIGINAL_PATH = os.environ.get("PATH", "")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


GIT_PLAN = """
## Git Operation Plan
| Field | Value |
| --- | --- |
| Isolation mode | branch |
| Local branch | DEMO-1 |
| Remote branch | DEMO-1 |
| Isolation scope | ticket |
| Setup when | first-do-chores |
| Plan commit | required-before-isolation |
| Reuse policy | reuse-if-same-ticket-else-stop |
| Worktree skill | n/a |
| Push rule | from config + explicit approval; push ref must equal Remote branch |
| Base dirt policy | clean-at-plan |
"""

CONVENTIONS = """
## Commit and PR conventions

**Commit title:** short imperative subject.

**Commit body:** optional body after a blank line.

**Pull request:** follow this repo's pull request template.

**Do not stage / commit:**
Never stage `.w2c/runtime/`, `.w2c/` when track is false, or `.env*`. Product commits must never stage these.

`openspec/` is product content and is never deny-listed. Product commits stage only this change's folder plus the archive result.

**Do not mention:**
Never mention any `.w2c/` path or W2C artifact in commit or pull request text.

**AI attribution — forbidden:**
Do not add `Co-authored-by:` trailers or similar AI co-author lines.
"""


def filled_roadmap(mid: str, slug: str) -> str:
    return (
        f"# {mid}: {slug}\n\n"
        "## Slices\n\n"
        "- [ ] **S01: Export**\n\n"
        "## Delivery & Guardrails\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        "| Planning mode | openspec |\n"
        f"| OpenSpec change | {slug} |\n"
        "| OpenSpec archive | |\n"
        "| Manual test guide | no |\n"
        + GIT_PLAN
        + CONVENTIONS
    )


def filled_slice(mid: str) -> str:
    return f"# S01: Export\n\nMilestone {mid} delivery envelope. No task lines.\n" + GIT_PLAN + CONVENTIONS


TASKS = """# Tasks

## 1. Export

- [ ] 1.1 Write the exporter
  - Verify: python3 -c 'print(1)'
"""


def seed_artifacts(root: Path, slug: str) -> None:
    change = root / "openspec" / "changes" / slug
    write(change / "proposal.md", "# Proposal\n\n## Why\n\nNeed export.\n")
    write(change / "design.md", "# Design\n\n## Context\n\nSee the proposal.\n")
    write(
        change / "specs" / "export" / "spec.md",
        "# Spec Delta\n\n## Purpose\n\nLets a user export their records.\n\n"
        "## ADDED Requirements\n\n### Requirement: Export\n"
        "The system SHALL export records.\n\n#### Scenario: User exports\n"
        "- **WHEN** the user asks\n- **THEN** a file is written\n",
    )
    write(change / "tasks.md", TASKS)


class OpenSpecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="w2c-os-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        bindir = self.tmp / "bin"
        bindir.mkdir()
        dest = bindir / "openspec"
        dest.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
        dest.chmod(0o755)
        os.environ["PATH"] = str(bindir) + os.pathsep + ORIGINAL_PATH
        self.addCleanup(lambda: os.environ.__setitem__("PATH", ORIGINAL_PATH))
        self.assertEqual(
            w2c.cmd_init(
                self.tmp,
                git_delivery="slice-commit-milestone-push-pr",
                planning="openspec",
            ),
            0,
        )

    def test_init_default_planning_and_legacy_alias(self) -> None:
        cfg = w2c_local.load_repo_config(self.tmp)
        self.assertEqual(cfg["planning"], "openspec")
        self.assertEqual(cfg["schema_version"], 2)
        other = self.tmp / "other"
        other.mkdir()
        self.assertEqual(
            w2c.cmd_init(other, git_delivery="slice-commit-milestone-push-pr", planning="legacy"),
            0,
        )
        self.assertEqual(w2c_local.load_repo_config(other)["planning"], "classic")
        bare = self.tmp / ".w2c" / "config.toml"
        text = bare.read_text(encoding="utf-8")
        bare.write_text(
            "\n".join(line for line in text.splitlines() if not line.startswith("planning ")) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(w2c_local.load_repo_config(self.tmp)["planning"], "classic")

    def test_openspec_check_needs_init_until_root_exists(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(w2c.cmd_openspec_check(self.tmp), 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["cli_found"])
        self.assertTrue(payload["version_ok"])
        self.assertFalse(payload["root_present"])
        self.assertIn("NEED_OPENSPEC_INIT", payload["needs"])

    def test_old_openspec_is_not_ok(self) -> None:
        os.environ["FAKE_OPENSPEC_VERSION"] = "1.0.0"
        self.addCleanup(lambda: os.environ.pop("FAKE_OPENSPEC_VERSION", None))
        payload = osp.check(self.tmp)
        self.assertFalse(payload["version_ok"])
        self.assertIn("NEED_OPENSPEC_INSTALL", payload["needs"])

    def test_milestone_links_change_and_complete_ticks_tasks(self) -> None:
        self.assertEqual(w2c.cmd_milestone_new(self.tmp, "add-export", planning="openspec"), 0)
        meta = (self.tmp / "openspec/changes/add-export/.openspec.yaml").read_text(encoding="utf-8")
        self.assertIn("x-w2c-milestone: M001", meta)
        plan = self.tmp / ".w2c/plans/M001-add-export"
        write(plan / "M001-ROADMAP.md", filled_roadmap("M001", "add-export"))
        write(plan / "M001-S01-PLAN.md", filled_slice("M001"))
        seed_artifacts(self.tmp, "add-export")
        task = w2c.next_open_task(self.tmp)
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual((task.mid, task.sid, task.tid, task.openspec_id), ("M001", "S01", "T01", "1.1"))
        write(plan / "S01-T01-SUMMARY.md", "# T01\n\n## What Happened\n\ndone\n")
        self.assertEqual(w2c.cmd_complete(self.tmp, "M001", "S01", "1.1"), 0)
        tasks = (self.tmp / "openspec/changes/add-export/tasks.md").read_text(encoding="utf-8")
        self.assertIn("- [x] 1.1 Write the exporter", tasks)
        report = w2c.run_smoke(self.tmp)
        names = {check.name: check for check in report.checks}
        self.assertEqual(names["openspec-cli"].status, "PASS")
        self.assertEqual(names["openspec-change-link"].status, "PASS")
        self.assertEqual(names["openspec-tasks-have-verify"].status, "PASS")
        self.assertEqual(names["openspec-progress-agrees"].status, "PASS")
        self.assertEqual(names["openspec-artifacts-complete"].status, "PASS")
        self.assertEqual(names["openspec-validate-strict"].status, "PASS")
        self.assertEqual(names["openspec-no-slice-tasks"].status, "PASS")
        self.assertEqual(names["openspec-conventions"].status, "PASS")
        self.assertFalse(report.failed(), [c for c in report.checks if c.status == "FAIL"])

    def test_smoke_fails_missing_verify_and_strict_validate(self) -> None:
        w2c.cmd_milestone_new(self.tmp, "add-export", planning="openspec")
        plan = self.tmp / ".w2c/plans/M001-add-export"
        write(plan / "M001-ROADMAP.md", filled_roadmap("M001", "add-export"))
        write(plan / "M001-S01-PLAN.md", filled_slice("M001"))
        seed_artifacts(self.tmp, "add-export")
        write(
            self.tmp / "openspec/changes/add-export/tasks.md",
            "# Tasks\n\n## 1. Export\n\n- [ ] 1.1 Write the exporter\n",
        )
        os.environ["FAKE_OPENSPEC_VALIDATE"] = "fail"
        self.addCleanup(lambda: os.environ.pop("FAKE_OPENSPEC_VALIDATE", None))
        report = w2c.run_smoke(self.tmp)
        names = {check.name: check for check in report.checks}
        self.assertEqual(names["openspec-tasks-have-verify"].status, "FAIL")
        self.assertEqual(names["openspec-validate-strict"].status, "FAIL")
        self.assertTrue(report.failed())

    def test_progress_disagrees_when_apply_marks_done(self) -> None:
        w2c.cmd_milestone_new(self.tmp, "add-export", planning="openspec")
        plan = self.tmp / ".w2c/plans/M001-add-export"
        write(plan / "M001-ROADMAP.md", filled_roadmap("M001", "add-export"))
        write(plan / "M001-S01-PLAN.md", filled_slice("M001"))
        seed_artifacts(self.tmp, "add-export")
        os.environ["FAKE_OPENSPEC_APPLY_DONE"] = "1"
        self.addCleanup(lambda: os.environ.pop("FAKE_OPENSPEC_APPLY_DONE", None))
        report = w2c.run_smoke(self.tmp)
        names = {check.name: check for check in report.checks}
        self.assertEqual(names["openspec-progress-agrees"].status, "FAIL")

    def test_progress_compares_dotted_ids_from_apply_descriptions(self) -> None:
        w2c.cmd_milestone_new(self.tmp, "add-export", planning="openspec")
        plan = self.tmp / ".w2c/plans/M001-add-export"
        write(plan / "M001-ROADMAP.md", filled_roadmap("M001", "add-export"))
        write(plan / "M001-S01-PLAN.md", filled_slice("M001"))
        seed_artifacts(self.tmp, "add-export")
        write(
            self.tmp / "openspec/changes/add-export/tasks.md",
            "# Tasks\n\n## 1. Export\n\n"
            "- [ ] 1.1 Add a failing unit test for the exporter\n"
            "  - Verify: python3 -c 'print(1)'\n"
            "- [ ] 1.2 Implement the exporter\n"
            "  - Verify: python3 -c 'print(2)'\n",
        )
        open_tasks = [
            {
                "id": "1",
                "description": "1.1 Add a failing unit test for the exporter",
                "done": False,
            },
            {
                "id": "2",
                "description": "1.2 Implement the exporter",
                "done": False,
            },
        ]
        flipped = [dict(open_tasks[0]), {**open_tasks[1], "done": True}]
        cases = (
            ("all open", open_tasks, "PASS"),
            ("one done flipped", flipped, "FAIL"),
            ("missing dotted id", [dict(open_tasks[0])], "FAIL"),
            (
                "extra dotted id",
                [
                    *open_tasks,
                    {"id": "3", "description": "1.3 Leave a note", "done": False},
                ],
                "FAIL",
            ),
            (
                "description without dotted id",
                [
                    {
                        "id": "1",
                        "description": "Add a failing unit test for the exporter",
                        "done": False,
                    },
                    dict(open_tasks[1]),
                ],
                "FAIL",
            ),
        )
        for label, tasks, expected in cases:
            with self.subTest(label=label):
                with patch(
                    "w2c.openspec_ledger.osp.apply_info",
                    return_value={"tasks": tasks},
                ):
                    report = w2c.run_smoke(self.tmp)
                names = {check.name: check for check in report.checks}
                self.assertEqual(names["openspec-progress-agrees"].status, expected)

    def test_spec_archive_records_path_and_decline_is_explicit(self) -> None:
        w2c.cmd_milestone_new(self.tmp, "add-export", planning="openspec")
        plan = self.tmp / ".w2c/plans/M001-add-export"
        write(plan / "M001-ROADMAP.md", filled_roadmap("M001", "add-export"))
        road = plan / "M001-ROADMAP.md"
        road.write_text(
            road.read_text(encoding="utf-8").replace("- [ ] **S01: Export**", "- [x] **S01: Export**"),
            encoding="utf-8",
        )
        write(plan / "M001-VALIDATION.md", "# Milestone Validation: M001\n\nverdict: pass\n")
        write(plan / "M001-SUMMARY.md", "# M001\n\n## What Happened\n\nok\n")
        with self.assertRaises(w2c.W2CError):
            w2c.cmd_milestone_status(self.tmp, "M001", "DONE")
        self.assertEqual(w2c.cmd_spec_archive(self.tmp, "M001"), 0)
        self.assertTrue(
            (self.tmp / "openspec/changes/archive/2026-10-18-add-export/.openspec.yaml").is_file()
        )
        recorded = road.read_text(encoding="utf-8")
        self.assertIn("openspec/changes/archive/2026-10-18-add-export", recorded)
        self.assertEqual(w2c.cmd_milestone_status(self.tmp, "M001", "DONE"), 0)

    def test_archive_declined_prints_follow_up(self) -> None:
        w2c.cmd_milestone_new(self.tmp, "add-export", planning="openspec")
        plan = self.tmp / ".w2c/plans/M001-add-export"
        body = filled_roadmap("M001", "add-export").replace(
            "- [ ] **S01: Export**", "- [x] **S01: Export**"
        )
        write(plan / "M001-ROADMAP.md", body)
        write(plan / "M001-VALIDATION.md", "# Milestone Validation: M001\n\nverdict: pass\n")
        write(plan / "M001-SUMMARY.md", "# M001\n\n## What Happened\n\nok\n")
        self.assertEqual(
            w2c.cmd_milestone_status(self.tmp, "M001", "DONE", archive_declined=True),
            0,
        )
        self.assertIn(
            "| OpenSpec archive | declined |",
            (plan / "M001-ROADMAP.md").read_text(encoding="utf-8"),
        )

    def test_base_dirt_skips_active_change_folder(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.tmp, check=True)
        w2c.cmd_milestone_new(self.tmp, "add-export", planning="openspec")
        plan = self.tmp / ".w2c/plans/M001-add-export"
        write(plan / "M001-ROADMAP.md", filled_roadmap("M001", "add-export"))
        write(self.tmp / "openspec/changes/add-export/exporter.py", "print(1)\n")
        write(self.tmp / "NOTES.md", "local\n")
        report = base_dirt.scan_base_dirt(
            str(self.tmp), extra_prefixes=w2c.openspec_ledger.change_prefixes(self.tmp)
        )
        self.assertNotIn("openspec/changes/add-export/exporter.py", report.critical)
        self.assertNotIn("openspec/changes/add-export/exporter.py", report.other)
        self.assertIn("NOTES.md", report.other)

    def test_rules_marker_is_seen_in_instructions(self) -> None:
        w2c.cmd_milestone_new(self.tmp, "add-export", planning="openspec")
        write(
            self.tmp / "openspec/config.yaml",
            "schema: spec-driven\n" + osp.CONFIG_RULES_SNIPPET,
        )
        payload = osp.check(self.tmp)
        self.assertTrue(payload["rules_present"])
        self.assertEqual(payload["rules_checked_via"], "instructions")


    def test_slice_plan_must_not_hold_task_checkboxes(self) -> None:
        w2c.cmd_milestone_new(self.tmp, "add-export", planning="openspec")
        plan = self.tmp / ".w2c/plans/M001-add-export"
        write(plan / "M001-ROADMAP.md", filled_roadmap("M001", "add-export"))
        write(
            plan / "M001-S01-PLAN.md",
            filled_slice("M001") + "\n- [ ] 1.1 This checkbox belongs in tasks.md\n",
        )
        seed_artifacts(self.tmp, "add-export")
        report = w2c.run_smoke(self.tmp)
        names = {check.name: check for check in report.checks}
        self.assertEqual(names["openspec-no-slice-tasks"].status, "FAIL")


@unittest.skipUnless(REAL_OPENSPEC, "openspec is not installed")
class RealOpenSpecTests(unittest.TestCase):
    def test_strict_validate_and_archive(self) -> None:
        os.environ["PATH"] = ORIGINAL_PATH
        version = subprocess.check_output([REAL_OPENSPEC, "--version"], text=True)
        if not osp.version_ok(version):
            self.skipTest(f"openspec {version.strip()} is older than the supported floor")
        tmp = Path(tempfile.mkdtemp(prefix="w2c-real-os-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        created = osp.new_change(tmp, "add-export", goal="Export records")
        meta = Path(created["change"]["metadataPath"])
        osp.link_milestone(meta, "M001")
        purpose = "Lets a person download the records they stored in the product."
        self.assertGreaterEqual(len(purpose), 50)
        write(
            tmp / "openspec/changes/add-export/proposal.md",
            "# Proposal\n\n## Why\n\nExport.\n\n## What Changes\n\n- Add export.\n\n"
            "## Capabilities\n\n### New Capabilities\n\n- `export`: download stored records\n\n"
            "### Modified Capabilities\n\n## Impact\n\n- exporter\n",
        )
        write(
            tmp / "openspec/changes/add-export/design.md",
            "# Design\n\n## Context\n\nSee proposal.md.\n\n## Goals / Non-Goals\n\n"
            "**Goals:**\n\n- Export records.\n\n**Non-Goals:**\n\n- Import.\n\n"
            "## Decisions\n\n- Write a file. A network call was rejected because the host is offline.\n\n"
            "## Risks / Trade-offs\n\n- [Large file] -> stream the write\n",
        )
        write(
            tmp / "openspec/changes/add-export/specs/export/spec.md",
            "# Spec Delta\n\n## Purpose\n\n"
            + purpose
            + "\n\n## ADDED Requirements\n\n### Requirement: User can export\n"
            "The system SHALL write the stored records to a file the user can download.\n\n"
            "#### Scenario: Successful export\n"
            "- **WHEN** the user asks for an export\n"
            "- **THEN** the system writes a file of their records\n",
        )
        write(
            tmp / "openspec/changes/add-export/tasks.md",
            "# Tasks\n\n## 1. Export\n\n- [x] 1.1 Write the exporter and verify the export test passes\n",
        )
        validated = osp.validate(tmp, "add-export", strict=True)
        self.assertTrue(validated.ok, validated.stderr or validated.stdout)
        archived = osp.archive(tmp, "add-export")
        self.assertIn("archive", archived)
        self.assertTrue(Path(archived["archive"]["path"]).is_dir())


if __name__ == "__main__":
    unittest.main()
