#!/usr/bin/env python3
"""Conversion planner: 2.2 OpenSpec milestones to cloud changes, read-only."""

from __future__ import annotations

import hashlib
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

_HOME = Path(tempfile.mkdtemp(prefix="w2c-cloud-convert-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from w2c import cli as w2c  # noqa: E402
from w2c import openspec as legacy_openspec  # noqa: E402
from w2c.cloud import convert, layout  # noqa: E402

TEMPLATES = ROOT / "templates"
CADENCE = "slice-commit-milestone-push-pr"
BRANCH = "DEMO-1"


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError((proc.stderr or proc.stdout).strip())
    return proc.stdout


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def fill_table(text: str, field: str, value: str) -> str:
    return re.sub(rf"(?m)^\| {re.escape(field)} \| [^|\n]*\|$", f"| {field} | {value} |", text)


def roadmap(mid: str, slug: str, *, slices: list[tuple[int, str, str]], branch: str = BRANCH,
            archive: str = "", extra: str = "") -> str:
    text = (TEMPLATES / "openspec" / "M-ROADMAP.md").read_text(encoding="utf-8")
    text = text.format(mid=mid, title=slug.replace("-", " "), slug=slug)
    lines = "\n".join(f"- [{mark}] **S{n:02d}: {title}**" for n, title, mark in slices)
    text = text.replace("**Vision:**", "**Vision:** People export their records.")
    text = text.replace("## Success Criteria\n", "## Success Criteria\n\n- A file is written." + extra + "\n")
    text = text.replace("## Boundary Map\n", f"{lines}\n\n## Boundary Map\n")
    text = text.replace("## In scope\n", "## In scope\n\n- The exporter.\n")
    for field, value in (
        ("Isolation mode", "branch"),
        ("Local branch", branch),
        ("Remote branch", branch),
        ("Worktree skill", "n/a"),
        ("Base dirt policy", "clean-at-plan"),
        ("Validation commands", "python3 -m unittest"),
        ("OpenSpec archive", archive),
    ):
        text = fill_table(text, field, value)
    text = text.replace("**Commit title:**", "**Commit title:** short imperative subject.")
    return text


def slice_plan(mid: str, sid: str, title: str, *, branch: str = BRANCH, extra_guardrail: str = "",
               conventions_extra: str = "") -> str:
    text = (TEMPLATES / "openspec" / "M-S-PLAN.md").read_text(encoding="utf-8")
    text = text.replace("MXXX", mid).replace("SXX", sid).replace("TITLE", title)
    text = text.replace("**Goal:**", "**Goal:** Export records.")
    text = text.replace("**Demo:**", "**Demo:** Run the exporter.")
    text = text.replace("## Must-Haves\n", "## Must-Haves\n\n- A CSV file.\n")
    for field, value in (
        ("Isolation mode", "branch"),
        ("Local branch", branch),
        ("Remote branch", branch),
        ("Base dirt policy", "clean-at-plan"),
    ):
        text = fill_table(text, field, value)
    text = text.replace("**Commit title:**", "**Commit title:** short imperative subject." + conventions_extra)
    if extra_guardrail:
        text = text.replace(
            "- Never force-reset, force-push, or delete worktrees/branches.\n",
            "- Never force-reset, force-push, or delete worktrees/branches.\n" + extra_guardrail + "\n",
        )
    return text


TASKS = """# Tasks

## 1. Export

- [ ] 1.1 Write the exporter
  - Verify: python3 -c 'print(1)'

## 2. Docs

- [ ] 2.1 Document the exporter
  - Verify: python3 -c 'print(2)'
"""

DECISIONS = w2c.DECISIONS_HEADER + (
    "| D001 | 2026-11-02 | M001 | How to export | CSV | Simple | Yes | human |\n"
    "| D002 | 2026-11-02 | M002 | How to import | JSON | Simple | Yes | human |\n"
    "| D003 | 2026-11-02 | project | Style | Black | Common | Yes | human |\n"
    "| D004 | 2026-11-02 | M001/S01 | Column order | Name first | Readable | Yes | human |\n"
)

CONTEXT_V10 = """---
version: 1.0
---

# Project Knowledge

## Rules

| # | Scope | Rule | Why | Added |
|---|-------|------|-----|-------|
| R1 | all | Old rule | Old | 2026 |

## Patterns

| # | Pattern | Where | Notes |
|---|---------|-------|-------|

## Lessons Learned

| # | What Happened | Root Cause | Fix | Scope |
|---|--------------|------------|-----|-------|
"""

CONTEXT_V11 = """---
version: 1.1
---

# Project Knowledge

## Rules

| # | Scope | Rule | Why | Added |
|---|-------|------|-----|-------|
| R1 | all | Use UTF-8 | Portability | 2026 |
| R2 | all | Keep tests fast | Speed | 2026 |

## Patterns

| # | Pattern | Where | Notes |
|---|---------|-------|-------|
| P1 | Small modules | src | none |

## Lessons Learned

| # | What Happened | Root Cause | Fix | Scope |
|---|--------------|------------|-----|-------|
| L1 | Slow CI | Big fixtures | Trim | tests |
"""

KNOWLEDGE = """# Project Knowledge

## Rules

| # | Scope | Rule | Why | Added |
|---|-------|------|-----|-------|
| R1 | all | Use UTF-8 | Portability | 2026 |
"""

STATUS_LINE = {status: emoji for status, emoji in w2c.STATUS_EMOJI.items()}


class Repo:
    """A git repo with a tracked `.w2c/` ledger and OpenSpec changes."""

    def __init__(self, base: Path, *, config_yaml: str = "schema: spec-driven\n") -> None:
        self.root = base / "repo"
        self.root.mkdir(parents=True)
        git(self.root, "init", "-q", "-b", BRANCH)
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "test")
        write(self.root / ".gitignore", ".w2c/\n")
        write(self.root / "openspec" / "config.yaml", config_yaml)
        write(self.root / "openspec" / "knowledge.md", KNOWLEDGE)
        self.config: dict[str, str] = {"git_delivery": CADENCE}
        self.write_config()
        write(self.w2c / "DECISIONS.md", DECISIONS)
        write(self.w2c / "contexts" / "CONTEXTv1.0.md", CONTEXT_V10)
        write(self.w2c / "contexts" / "CONTEXTv1.1.md", CONTEXT_V11)
        write(self.w2c / "STATE.md", w2c.STATE_TEMPLATE)
        write(self.w2c / "QUEUE.md", w2c.QUEUE_TEMPLATE)
        self.lines: list[str] = []
        self.write_roadmap()

    @property
    def w2c(self) -> Path:
        return self.root / ".w2c"

    def write_config(self) -> None:
        body = "schema_version = 3\ntrack = true\nplanning = \"openspec\"\n"
        for key, value in self.config.items():
            body += f'{key} = "{value}"\n'
        write(self.w2c / "config.toml", body)

    def write_roadmap(self) -> None:
        write(self.w2c / "ROADMAP.md", "# Roadmap\n\n## Milestones\n" + "".join(self.lines))

    def plan(self, mid: str, slug: str) -> Path:
        return self.w2c / "plans" / f"{mid}-{slug}"

    def change(self, slug: str) -> Path:
        return self.root / "openspec" / "changes" / slug

    def add(self, mid: str, slug: str, status: str = "INPROGRESS", *,
            slices: list[tuple[int, str, str]] | None = None, archive: str = "",
            classic: bool = False, branch: str = BRANCH, extra: str = "",
            seed_change: bool = True) -> Path:
        slices = slices if slices is not None else [(1, "Export", "x"), (2, "Docs", " ")]
        plan = self.plan(mid, slug)
        text = roadmap(mid, slug, slices=slices, branch=branch, archive=archive, extra=extra)
        if classic:
            text = text.replace("| Planning mode | openspec |\n", "")
        write(plan / f"{mid}-ROADMAP.md", text)
        write(plan / f"{mid}-CONTEXT.md", w2c.M_CONTEXT_STUB.format(mid=mid, title=slug).replace(
            "## Problem\n", "## Problem\n\nNo export today.\n"))
        for number, title, _mark in slices:
            sid = f"S{number:02d}"
            write(plan / f"{mid}-{sid}-PLAN.md", slice_plan(mid, sid, title, branch=branch))
        self.lines.append(f"- {STATUS_LINE[status]} **{mid}: {slug.replace('-', ' ')}** (`depends:[—]`)\n")
        self.write_roadmap()
        if seed_change and not classic:
            self.seed_change(slug, mid, archive=archive)
        return plan

    def seed_change(self, slug: str, mid: str, *, archive: str = "") -> Path:
        if archive and archive != "declined":
            folder = self.root / archive
        else:
            folder = self.change(slug)
        write(folder / ".openspec.yaml", f"schema: spec-driven\ncreated: 2026-10-18\nx-w2c-milestone: {mid}\n")
        write(folder / "proposal.md", "# Proposal\n\n## Why\n\nNeed export.\n")
        write(folder / "design.md", "# Design\n\n## Context\n\nSee the proposal.\n\n## Decisions\n\nUse the stdlib.\n")
        write(folder / "specs" / "export" / "spec.md", "# Spec\n\n### Requirement: Export\n")
        write(folder / "tasks.md", TASKS)
        return folder

    def commit(self) -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "seed", "--allow-empty")


def kinds(plan: convert.ConversionPlan, kind: str) -> list[convert.Action]:
    return [a for a in plan.actions if a.kind == kind]


def under(plan: convert.ConversionPlan, folder: Path) -> list[convert.Action]:
    out = []
    for action in plan.actions:
        try:
            action.path.relative_to(folder)
        except ValueError:
            continue
        out.append(action)
    return out


def heading(action: convert.Action) -> str:
    return action.detail.split(" (")[0]


def tree_hash(*bases: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for base in bases:
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                path = Path(dirpath) / name
                found[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


class ConvertTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="w2c-convert-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def repo(self, **kwargs) -> Repo:
        return Repo(self.tmp, **kwargs)

    # ------------------------------------------------------------ keys

    def test_each_status_maps_to_delivery_status(self) -> None:
        for status in ("PLANNING", "TODO", "INPROGRESS", "PAUSED", "STOP", "ERROR"):
            with self.subTest(status=status):
                base = self.tmp / status
                base.mkdir()
                repo = Repo(base)
                repo.add("M001", "add-export", status)
                repo.commit()
                plan = convert.plan_conversion(repo.root, ["M001"])
                self.assertEqual(plan.blockers, [])
                meta = repo.change("add-export") / ".openspec.yaml"
                details = {a.detail for a in kinds(plan, "write-key") if a.path == meta}
                self.assertIn(f"x-delivery-status: {status}", details)
                self.assertIn("x-delivery-order: 1", details)
                self.assertIn(f"x-delivery-cadence: {CADENCE}", details)
                self.assertIn("x-delivery-slices-done: [1]", details)
                renames = kinds(plan, "rename-key")
                self.assertEqual([(a.path, a.detail) for a in renames],
                                 [(meta, "x-w2c-milestone -> x-delivery-legacy-id: M001")])
                self.assertTrue(kinds(plan, "append-section"))

    def test_order_follows_roadmap_line_and_write_key_without_link(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO")
        repo.add("M002", "add-import", "TODO")
        meta = repo.change("add-import") / ".openspec.yaml"
        meta.write_text("schema: spec-driven\n", encoding="utf-8")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M002"])
        self.assertEqual(plan.blockers, [])
        details = {a.detail for a in kinds(plan, "write-key") if a.path == meta}
        self.assertIn("x-delivery-order: 2", details)
        self.assertIn("x-delivery-legacy-id: M002", details)
        self.assertEqual(kinds(plan, "rename-key"), [])

    def test_archived_done_gets_keys_only(self) -> None:
        repo = self.repo()
        archived = "openspec/changes/archive/2026-10-20-add-export"
        repo.add("M001", "add-export", "DONE", slices=[(1, "Export", "x"), (2, "Docs", "x")], archive=archived)
        write(repo.plan("M001", "add-export") / "M001-SUMMARY.md", "# M001\n")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertEqual(plan.blockers, [])
        folder = repo.root / archived
        mine = under(plan, folder)
        self.assertTrue(mine)
        self.assertEqual({a.kind for a in mine}, {"write-key", "rename-key"})
        for kind in ("append-section", "write-group-fields", "copy-report", "copy-decisions"):
            self.assertEqual(kinds(plan, kind), [], kind)
        details = {a.detail for a in kinds(plan, "write-key")}
        self.assertIn("x-delivery-status: DONE", details)
        self.assertIn("x-delivery-slices-done: [1, 2]", details)
        self.assertNotIn("x-delivery-archive: declined", details)
        self.assertEqual(len(kinds(plan, "mark-converted")), 1)
        self.assertEqual(len(kinds(plan, "roadmap-remove")), 1)

    def test_declined_done_gets_keys_only_with_archive_declined(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "DONE", archive="declined")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertEqual(plan.blockers, [])
        meta = repo.change("add-export") / ".openspec.yaml"
        details = {a.detail for a in kinds(plan, "write-key") if a.path == meta}
        self.assertIn("x-delivery-status: DONE", details)
        self.assertIn("x-delivery-archive: declined", details)
        self.assertEqual({a.kind for a in under(plan, repo.change("add-export"))}, {"write-key", "rename-key"})

    def test_done_without_archive_or_decline_is_a_blocker(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "DONE")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertTrue(any("M001" in b and "archive" in b for b in plan.blockers), plan.blockers)

    def test_amendment_lock_copies_three_keys(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "PAUSED")
        write(repo.plan("M001", "add-export") / "M001-AMENDMENTS.md",
              "# Amendments\n\nThe w2c command is the only writer of this file.\n\n"
              "## A001 drop-task M001/S02/T01\n\n- decision: D001\n- reason: not needed\n"
              "- follow-up: \n- ticket: \n")
        repo.config.update(amend_lock="M001", amend_prior_status="INPROGRESS", amend_decision="D001")
        repo.write_config()
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertEqual(plan.blockers, [])
        details = {a.detail for a in kinds(plan, "write-key")}
        self.assertIn("x-delivery-amend-lock: D001", details)
        self.assertIn("x-delivery-amend-prior-status: INPROGRESS", details)
        self.assertIn("x-delivery-amend-decision: D001", details)
        self.assertIn("x-delivery-status: PAUSED", details)
        amend = [a for a in kinds(plan, "append-section") if "## Amendments" in a.detail]
        self.assertEqual(len(amend), 1)
        self.assertIn("### A001 drop-task add-export/S02/T01", amend[0].content)
        self.assertNotIn("w2c", amend[0].content.lower())
        self.assertIsNone(plan.next_before["M001"])

    def test_no_amend_keys_for_another_milestone(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO")
        repo.config.update(amend_lock="M009", amend_prior_status="TODO", amend_decision="D001")
        repo.write_config()
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertFalse([a for a in kinds(plan, "write-key") if "amend" in a.detail])

    # ------------------------------------------------------------ content

    def test_unfinished_sections_reports_and_decisions(self) -> None:
        repo = self.repo()
        plan_dir = repo.add("M001", "add-export", "INPROGRESS")
        for name in ("S01-T01-SUMMARY.md", "S01-UAT.md", "S01-SUMMARY.md", "M001-VALIDATION.md", "M001-SUMMARY.md"):
            write(plan_dir / name, f"# {name}\n")
        write(plan_dir / "M001-MANUAL-TEST.md", "# M001: manual\n\n## Steps\n\n1. **Action:** run\n")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertEqual(plan.blockers, [])
        change = repo.change("add-export")
        targets = {(a.path.name, heading(a).split(" > ")[0]) for a in kinds(plan, "append-section")}
        for name, title in (
            ("proposal.md", "## Vision"), ("proposal.md", "## Success Criteria"),
            ("proposal.md", "## In scope"), ("proposal.md", "## Problem"),
            ("design.md", "## Delivery Plan"), ("design.md", "## Guardrails"),
            ("design.md", "## Commit and PR Conventions"), ("design.md", "## Decisions"),
            ("design.md", "## Manual Test Guide"),
        ):
            self.assertIn((name, title), targets)
        delivery = [a for a in kinds(plan, "append-section") if heading(a) == "## Delivery Plan"][0]
        self.assertIn("| Remote branch | DEMO-1 |", delivery.content)
        self.assertIn("| Isolation mode | branch |", delivery.content)
        self.assertNotIn("| Planning mode |", delivery.content)
        self.assertNotIn("| Plan commit |", delivery.content)
        self.assertIn("dropped", delivery.detail)
        guard = [a for a in kinds(plan, "append-section") if heading(a) == "## Guardrails"][0]
        self.assertNotIn("**Plan commit**", guard.content)
        self.assertNotIn("**Spec commit**", guard.content)
        self.assertIn("**Verify loop**", guard.content)
        decisions = [a for a in kinds(plan, "append-section") if a.detail.startswith("## Decisions")]
        self.assertTrue(all("append-to-existing" in a.detail for a in decisions), [a.detail for a in decisions])
        vision = [a for a in kinds(plan, "append-section") if a.detail.startswith("## Vision")][0]
        self.assertIn("new", vision.detail)
        self.assertIn("People export their records.", vision.content)
        groups = kinds(plan, "write-group-fields")
        self.assertEqual(sorted(a.detail.split()[1] for a in groups), ["1", "2"])
        self.assertTrue(all(a.path == change / "tasks.md" for a in groups))
        self.assertIn("**Goal:** Export records.", groups[0].content)
        self.assertIn("**Must-Haves:**\n- A CSV file.", groups[0].content)
        reports = {a.path.name for a in kinds(plan, "copy-report")}
        self.assertEqual(reports, {"S01-T01-SUMMARY.md", "S01-UAT.md", "S01-SUMMARY.md", "VALIDATION.md", "SUMMARY.md"})
        self.assertTrue(all(a.path.parent == change / ".delivery" for a in kinds(plan, "copy-report")))
        copy = kinds(plan, "copy-decisions")
        self.assertEqual(len(copy), 1)
        self.assertIn("D001", copy[0].detail)
        self.assertNotIn("D002", copy[0].detail)
        self.assertNotIn("D004", copy[0].detail)
        self.assertEqual(plan.next_before, {"M001": ("M001", "S01", "T01")})

    def test_project_level_actions(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        sync = kinds(plan, "sync-knowledge")
        self.assertEqual(len(sync), 1)
        self.assertIn("| R2 | all | Keep tests fast | Speed | 2026 |", sync[0].content)
        self.assertIn("| P1 | Small modules | src | none |", sync[0].content)
        self.assertIn("| L1 | Slow CI | Big fixtures | Trim | tests |", sync[0].content)
        self.assertNotIn("Use UTF-8", sync[0].content)
        self.assertNotIn("Old rule", sync[0].content)
        self.assertEqual([a.path for a in kinds(plan, "edit-gitattributes")], [repo.root / ".gitattributes"])
        config = kinds(plan, "edit-config")
        self.assertEqual(len(config), 1)
        self.assertIn("append", config[0].detail)
        self.assertEqual(config[0].content, layout.CONFIG_RULES_SNIPPET)
        marks = kinds(plan, "mark-converted")
        self.assertEqual([(a.path, a.content) for a in marks],
                         [(repo.plan("M001", "add-export") / "CONVERTED", "add-export")])
        self.assertEqual([a.path for a in kinds(plan, "roadmap-remove")], [repo.w2c / "ROADMAP.md"])

    def test_edit_config_merges_into_existing_rules_key(self) -> None:
        repo = self.repo(config_yaml="schema: spec-driven\n\n" + legacy_openspec.CONFIG_RULES_SNIPPET)
        repo.add("M001", "add-export", "TODO")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        config = kinds(plan, "edit-config")
        self.assertEqual(len(config), 1)
        self.assertIn("merge", config[0].detail)
        self.assertIn("rules", config[0].detail)
        self.assertNotIn("context", config[0].detail.split("merge", 1)[1])

    def test_no_config_or_attributes_edit_when_present(self) -> None:
        repo = self.repo(config_yaml="schema: spec-driven\n" + layout.CONFIG_RULES_SNIPPET)
        write(repo.root / ".gitattributes", "openspec/knowledge.md merge=union\n")
        repo.add("M001", "add-export", "TODO")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertEqual(kinds(plan, "edit-config"), [])
        self.assertEqual(kinds(plan, "edit-gitattributes"), [])

    # ------------------------------------------------------------ checkouts

    def test_worktree_held_branch_is_the_target(self) -> None:
        repo = self.repo()
        git(repo.root, "checkout", "-q", "-b", "main")
        repo.add("M001", "add-export", "TODO", branch="DEMO-2")
        repo.commit()
        wt = self.tmp / "wt"
        git(repo.root, "worktree", "add", "-q", "-b", "DEMO-2", str(wt))
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertEqual(plan.blockers, [])
        meta = wt / "openspec" / "changes" / "add-export" / ".openspec.yaml"
        self.assertIn(meta, {a.path for a in kinds(plan, "write-key")})
        self.assertFalse(under(plan, repo.change("add-export")))
        self.assertEqual([a.path for a in kinds(plan, "edit-gitattributes")], [wt / ".gitattributes"])

    def test_branch_checked_out_nowhere_is_a_blocker(self) -> None:
        repo = self.repo()
        git(repo.root, "checkout", "-q", "-b", "main")
        repo.commit()
        git(repo.root, "checkout", "-q", "-b", "DEMO-9")
        repo.add("M001", "add-export", "TODO", branch="DEMO-9")
        repo.commit()
        git(repo.root, "checkout", "-q", "main")
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertTrue(any("DEMO-9" in b for b in plan.blockers), plan.blockers)

    def test_uncommitted_change_folder_is_a_blocker(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO")
        repo.commit()
        write(repo.change("add-export") / "proposal.md", "# Proposal\n\nedited\n")
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertTrue(any("uncommitted" in b and "proposal.md" in b for b in plan.blockers), plan.blockers)

    # ------------------------------------------------------------ refusals

    def test_classic_milestone_named_is_refused(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-subtract", "TODO", classic=True)
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertTrue(any("M001" in b and "work to chores cloud" in b for b in plan.blockers), plan.blockers)

    def test_unknown_heading_is_a_blocker(self) -> None:
        repo = self.repo()
        plan_dir = repo.add("M001", "add-export", "TODO")
        road = plan_dir / "M001-ROADMAP.md"
        road.write_text(road.read_text(encoding="utf-8") + "\n## Release Notes\n\nShip on Friday.\n", encoding="utf-8")
        ctx = plan_dir / "M001-CONTEXT.md"
        ctx.write_text(ctx.read_text(encoding="utf-8") + "\n## Risks\n\nNone.\n", encoding="utf-8")
        write(plan_dir / "notes.txt", "loose notes\n")
        s01 = plan_dir / "M001-S01-PLAN.md"
        s01.write_text(s01.read_text(encoding="utf-8").replace(
            "# S01: Export\n", "# S01: Export\n\n<!-- keep the CSV header stable -->\n"), encoding="utf-8")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertTrue(any("## Release Notes" in b for b in plan.blockers), plan.blockers)
        self.assertTrue(any("## Risks" in b for b in plan.blockers), plan.blockers)
        self.assertTrue(any("notes.txt" in b for b in plan.blockers), plan.blockers)
        self.assertTrue(any("M001-S01-PLAN.md" in b and "before the first heading" in b for b in plan.blockers),
                        plan.blockers)

    def test_slice_disagreement_is_a_blocker(self) -> None:
        cases = {
            "branch": lambda m, s, t: slice_plan(m, s, t, branch="OTHER-1"),
            "guardrail": lambda m, s, t: slice_plan(m, s, t, extra_guardrail="- Only touch the exporter."),
            "conventions": lambda m, s, t: slice_plan(m, s, t, conventions_extra=" Use emoji."),
        }
        for name, make in cases.items():
            with self.subTest(case=name):
                base = self.tmp / name
                base.mkdir()
                repo = Repo(base)
                plan_dir = repo.add("M001", "add-export", "TODO")
                write(plan_dir / "M001-S02-PLAN.md", make("M001", "S02", "Docs"))
                repo.commit()
                plan = convert.plan_conversion(repo.root, ["M001"])
                self.assertTrue(any("S02" in b for b in plan.blockers), plan.blockers)

    def test_conflicting_delivery_values_are_a_blocker(self) -> None:
        repo = self.repo()
        plan_dir = repo.add("M001", "add-export", "TODO")
        road = plan_dir / "M001-ROADMAP.md"
        text = road.read_text(encoding="utf-8")
        text = text.replace("| Isolation mode | branch |", "| Isolation mode | worktree |", 1)
        road.write_text(text, encoding="utf-8")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertTrue(any("Isolation mode" in b for b in plan.blockers), plan.blockers)

    # ------------------------------------------------------------ rewrites

    def test_known_versus_unknown_w2c_lines(self) -> None:
        repo = self.repo()
        plan_dir = repo.add("M001", "add-export", "TODO", extra="\n- Run w2c smoke before each push.")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertEqual(plan.blockers, [])
        road = plan_dir / "M001-ROADMAP.md"
        known = {(p, old) for p, _n, old, _new in plan.known_rewrites}
        guard = next(line for line in road.read_text(encoding="utf-8").splitlines()
                     if line.startswith("- **Status writes**"))
        self.assertIn((road, guard), known)
        for _path, number, old, new in plan.known_rewrites:
            self.assertEqual(convert.KNOWN_REWRITES[old], new)
            self.assertNotIn("w2c", new.lower())
            self.assertGreater(number, 0)
        unknown = [(p, line) for p, _n, line in plan.unknown_w2c_lines]
        self.assertIn((road, "- Run w2c smoke before each push."), unknown)
        self.assertFalse(any(line in convert.KNOWN_REWRITES for _p, line in unknown))
        lineno = [n for p, n, line in plan.unknown_w2c_lines if line == "- Run w2c smoke before each push."][0]
        self.assertEqual(road.read_text(encoding="utf-8").splitlines()[lineno - 1], "- Run w2c smoke before each push.")

    def test_known_rewrites_cover_every_legacy_template_line(self) -> None:
        neutral = set()
        for name in ("design-delivery.md", "slice-group.md"):
            neutral |= set((TEMPLATES / "cloud" / name).read_text(encoding="utf-8").splitlines())
        sources = [
            TEMPLATES / "openspec" / "M-ROADMAP.md",
            TEMPLATES / "openspec" / "M-S-PLAN.md",
            TEMPLATES / "M-ROADMAP.md",
            TEMPLATES / "M-S-PLAN.md",
        ]
        for source in sources:
            for line in source.read_text(encoding="utf-8").splitlines():
                if "w2c" in line.lower():
                    with self.subTest(source=source.name, line=line):
                        self.assertIn(line, convert.KNOWN_REWRITES)
        for old, new in convert.KNOWN_REWRITES.items():
            with self.subTest(old=old):
                self.assertIn("w2c", old.lower())
                self.assertNotIn("w2c", new.lower())
                self.assertIn(new, neutral)

    def test_slice_template_lines_match_the_templates(self) -> None:
        for name in ("openspec/M-S-PLAN.md", "M-S-PLAN.md"):
            text = (TEMPLATES / name).read_text(encoding="utf-8")
            guard = text.split("### Guardrails\n", 1)[1].split("\n## ", 1)[0]
            for line in guard.splitlines():
                if line.strip():
                    with self.subTest(template=name, line=line):
                        self.assertIn(line, convert.SLICE_TEMPLATE_GUARDRAILS)
            self.assertTrue(any(p in text for p in convert.SLICE_TEMPLATE_PROSE if p.startswith("Must match")), name)
        self.assertIn(next(p for p in convert.SLICE_TEMPLATE_PROSE if p.startswith("This slice")),
                      (TEMPLATES / "openspec" / "M-S-PLAN.md").read_text(encoding="utf-8"))

    def test_section_map_entries(self) -> None:
        expected = {
            ("roadmap", "**Vision:**"): ("proposal.md", "## Vision"),
            ("roadmap", "## Success Criteria"): ("proposal.md", "## Success Criteria"),
            ("roadmap", "## Boundary Map"): ("proposal.md", "## Boundary Map"),
            ("roadmap", "## In scope"): ("proposal.md", "## In scope"),
            ("roadmap", "## Out of scope"): ("proposal.md", "## Out of scope"),
            ("roadmap", "## Soft dependency"): ("proposal.md", "## Soft dependency"),
            ("roadmap", "## Delivery & Guardrails"): ("design.md", "## Delivery Plan"),
            ("roadmap", "## Git Operation Plan"): ("design.md", "## Delivery Plan"),
            ("roadmap", "### Guardrails"): ("design.md", "## Guardrails"),
            ("roadmap", "## Commit and PR conventions"): ("design.md", "## Commit and PR Conventions"),
            ("context", "## Problem"): ("proposal.md", "## Problem"),
            ("context", "## Solution"): ("proposal.md", "## Solution"),
            ("context", "## Out of Scope"): ("proposal.md", "## Out of Scope"),
            ("context", "## Key Decisions"): ("design.md", "## Decisions"),
            ("context", "## Decision Rationale"): ("design.md", "## Decisions"),
            ("context", "## Validation"): ("design.md", "## Guardrails"),
            ("context", "## Completion Criteria"): ("design.md", "## Guardrails"),
            ("manual-test", "MANUAL-TEST.md"): ("design.md", "## Manual Test Guide"),
            ("amendments", "AMENDMENTS.md"): ("design.md", "## Amendments"),
        }
        for key, value in expected.items():
            self.assertEqual(convert.SECTION_MAP.get(key), value, key)
        self.assertEqual(convert.SECTION_MAP[("roadmap", "## Slices")][1], "x-delivery-slices-done")
        for field in layout.SLICE_FIELDS:
            self.assertIn(("tasks.md", f"**{field}:**"), set(convert.SECTION_MAP.values()))

    # ------------------------------------------------------------ selection

    def test_named_milestone_leaves_the_others_out(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO")
        repo.add("M002", "add-import", "TODO")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertEqual(plan.blockers, [])
        self.assertFalse(under(plan, repo.change("add-import")))
        self.assertEqual(set(plan.next_before), {"M001"})
        self.assertEqual(len(kinds(plan, "mark-converted")), 1)
        self.assertEqual(kinds(plan, "write-decisions-file"), [])
        self.assertEqual(kinds(plan, "delete-ledger-file"), [])

    def test_all_with_classic_left_plans_no_ledger_deletion(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO")
        repo.add("M002", "add-subtract", "TODO", classic=True)
        repo.commit()
        plan = convert.plan_conversion(repo.root, None)
        self.assertEqual(plan.blockers, [])
        self.assertEqual(set(plan.next_before), {"M001"})
        self.assertEqual(kinds(plan, "write-decisions-file"), [])
        self.assertEqual(kinds(plan, "delete-ledger-file"), [])

    def test_all_with_nothing_left_writes_decisions_and_deletes_ledger(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO")
        repo.add("M002", "add-import", "DONE", archive="declined")
        repo.commit()
        plan = convert.plan_conversion(repo.root, None)
        self.assertEqual(plan.blockers, [])
        decisions = kinds(plan, "write-decisions-file")
        self.assertEqual([a.path for a in decisions], [repo.root / "openspec" / "decisions.md"])
        for did in ("D002", "D003", "D004"):
            self.assertIn(f"| {did} |", decisions[0].content)
        self.assertNotIn("| D001 |", decisions[0].content)
        deleted = {a.path for a in kinds(plan, "delete-ledger-file")}
        self.assertEqual(deleted, {repo.w2c / n for n in ("STATE.md", "QUEUE.md", "ROADMAP.md", "DECISIONS.md", "contexts")})

    def test_plan_conversion_changes_no_file(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "INPROGRESS")
        repo.add("M002", "add-import", "DONE", archive="declined")
        repo.add("M003", "add-subtract", "TODO", classic=True)
        write(repo.plan("M001", "add-export") / "S01-T01-SUMMARY.md", "# T01\n")
        repo.commit()
        store = repo.root / ".git" / "w2c" / "ledger"
        write(store / "STATE.md", "# State\n")
        write(repo.change("add-export") / "untracked.md", "dirty\n")
        before = tree_hash(repo.root, store)
        convert.plan_conversion(repo.root, None)
        convert.plan_conversion(repo.root, ["M001", "M003"])
        self.assertEqual(tree_hash(repo.root, store), before)


if __name__ == "__main__":
    unittest.main()
