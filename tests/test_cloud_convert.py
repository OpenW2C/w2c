#!/usr/bin/env python3
"""Conversion planner: 2.2 OpenSpec milestones to cloud changes, read-only."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-cloud-convert-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from w2c import cli as w2c  # noqa: E402
from w2c import delivery_profile  # noqa: E402
from w2c import local as w2c_local  # noqa: E402
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
        ("Setup when", "first-do-chores"),
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
        meta = (wt / "openspec" / "changes" / "add-export" / ".openspec.yaml").resolve()
        self.assertIn(meta, {a.path.resolve() for a in kinds(plan, "write-key")})
        self.assertFalse(under(plan, repo.change("add-export")))
        self.assertEqual([a.path.resolve() for a in kinds(plan, "edit-gitattributes")], [(wt / ".gitattributes").resolve()])

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
        s01.write_text(s01.read_text(encoding="utf-8") + "\n## Rollout\n\nBehind a flag.\n", encoding="utf-8")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertTrue(any("## Release Notes" in b for b in plan.blockers), plan.blockers)
        self.assertTrue(any("## Risks" in b for b in plan.blockers), plan.blockers)
        self.assertTrue(any("notes.txt" in b for b in plan.blockers), plan.blockers)
        self.assertTrue(any("M001-S01-PLAN.md" in b and "## Rollout" in b for b in plan.blockers), plan.blockers)

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
            if not isinstance(new, convert.Drop):
                self.assertIsNone(convert.FLAG_RE.search(new))
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
        sources = {
            name: (TEMPLATES / name).read_text(encoding="utf-8")
            for name in ("openspec/M-ROADMAP.md", "openspec/M-S-PLAN.md", "M-ROADMAP.md", "M-S-PLAN.md",
                         "M-MANUAL-TEST.md", "DELIVERY-PROFILE.md")
        }
        sources["cli.M_ROADMAP_STUB"] = w2c.M_ROADMAP_STUB
        for strategy in ("trunk-direct", "feature-branch", "gitflow"):
            for ci in (True, False):
                sources[f"compose {strategy} {ci}"] = delivery_profile.compose_delivery_profile(
                    strategy=strategy, ci_pointers=ci)
        flagged = 0
        for source, text in sources.items():
            for line in text.splitlines():
                if convert.FLAG_RE.search(line):
                    flagged += 1
                    with self.subTest(source=source, line=line):
                        self.assertIn(line, convert.KNOWN_REWRITES)
        self.assertGreater(flagged, 30)
        for name in ("git_delivery", "milestone-complete", "first-do-chores", "M###-VALIDATION.md", "m012-summary.md"):
            self.assertIsNotNone(convert.FLAG_RE.search(f"x {name} y"), name)
        for old, new in convert.KNOWN_REWRITES.items():
            with self.subTest(old=old):
                self.assertIsNotNone(convert.FLAG_RE.search(old))
                if isinstance(new, convert.Drop):
                    self.assertTrue(new.reason)
                    self.assertIsNone(convert.FLAG_RE.search(new.reason))
                else:
                    self.assertIsNone(convert.FLAG_RE.search(new))
                    self.assertIn(new, neutral)
        for drop in ("| Commit cadence | (from .w2c/config.toml git_delivery) |",
                     "<!-- REQUIRED literal format -- the w2c CLI's parse_slices() only recognizes this exact"):
            self.assertIsInstance(convert.KNOWN_REWRITES[drop], convert.Drop)
        self.assertIsInstance(next(v for k, v in convert.KNOWN_REWRITES.items() if k.startswith("- **Plan commit**")),
                              convert.Drop)
        for key, lines in convert.CONVENTIONS_REPAIRS:
            for line in lines:
                self.assertIn(line, neutral, key)
        for line in layout.MANUAL_GUIDE_NOTES:
            self.assertIn(line, neutral)

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

    # ------------------------------------------------------------ fix round 1

    def test_declined_done_copies_milestone_reports_only(self) -> None:
        repo = self.repo()
        plan_dir = repo.add("M001", "add-export", "DONE", archive="declined")
        for name in ("S01-T01-SUMMARY.md", "S01-UAT.md", "M001-VALIDATION.md", "M001-SUMMARY.md"):
            write(plan_dir / name, f"# {name}\n")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertEqual(plan.blockers, [])
        delivery = repo.change("add-export") / ".delivery"
        self.assertEqual({a.path for a in kinds(plan, "copy-report")},
                         {delivery / "VALIDATION.md", delivery / "SUMMARY.md"})
        self.assertEqual(kinds(plan, "append-section"), [])

    def test_conventions_get_missing_neutral_lines_added(self) -> None:
        repo = self.repo()
        plan_dir = repo.add("M001", "add-export", "TODO")
        road = plan_dir / "M001-ROADMAP.md"
        text = road.read_text(encoding="utf-8")
        legacy_mention = next(line for line in text.splitlines() if line.startswith("Never name any `.w2c/`"))
        custom = "Never mention any `.w2c/` path or W2C artifact in commit or pull request text."
        road.write_text(text.replace(legacy_mention, custom), encoding="utf-8")
        for slice_file in plan_dir.glob("M001-S*-PLAN.md"):
            slice_file.write_text(slice_file.read_text(encoding="utf-8").replace(legacy_mention, custom),
                                  encoding="utf-8")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertEqual(plan.blockers, [])
        conv = [a for a in kinds(plan, "append-section") if heading(a) == "## Commit and PR Conventions"]
        self.assertEqual(len(conv), 2, [a.detail for a in conv])
        self.assertIn(custom, conv[0].content)
        self.assertIn("**Do not mention:**", conv[1].content)
        self.assertIn("`.delivery/`", conv[1].content)
        self.assertIn("required line added", conv[1].detail)

    def test_template_conventions_need_no_added_lines(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        conv = [a for a in kinds(plan, "append-section") if heading(a) == "## Commit and PR Conventions"]
        self.assertEqual(len(conv), 1)

    def test_unset_fields_and_groups_without_a_slice_plan(self) -> None:
        repo = self.repo()
        plan_dir = repo.add("M001", "add-export", "TODO")
        (plan_dir / "M001-S02-PLAN.md").unlink()
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertEqual(plan.blockers, [])
        groups = {a.detail.split()[1]: a for a in kinds(plan, "write-group-fields")}
        self.assertEqual(set(groups), {"1", "2"})
        self.assertIn(f"**Threat Surface:** {convert.NOT_SET}", groups["1"].content)
        self.assertIn("not set: Threat Surface", groups["1"].detail)
        self.assertIn("no slice plan", groups["2"].detail)
        for name in layout.SLICE_FIELDS:
            self.assertIn(f"**{name}:** {convert.NOT_SET}", groups["2"].content)

    def test_read_first_block_is_planned_once(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO")
        repo.add("M002", "add-import", "TODO")
        tasks = repo.change("add-import") / "tasks.md"
        block = (TEMPLATES / "cloud" / "tasks-read-first.md").read_text(encoding="utf-8")
        tasks.write_text("# Tasks\n\n" + block + "\n" + TASKS.split("\n", 2)[2], encoding="utf-8")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001", "M002"])
        read_first = kinds(plan, "write-read-first")
        self.assertEqual([a.path for a in read_first], [repo.change("add-export") / "tasks.md"])
        self.assertEqual(read_first[0].content, block)
        self.assertIn("write-read-first", convert.ACTION_KINDS)

    def test_slice_preamble_prose_goes_into_goal(self) -> None:
        repo = self.repo()
        plan_dir = repo.add("M001", "add-export", "TODO")
        s01 = plan_dir / "M001-S01-PLAN.md"
        s01.write_text(s01.read_text(encoding="utf-8").replace(
            "This slice is delivery context only.", "Milestone M001 delivery envelope.\n\nThis slice is delivery context only."),
            encoding="utf-8")
        s02 = plan_dir / "M001-S02-PLAN.md"
        s02.write_text(s02.read_text(encoding="utf-8").replace("**Goal:** Export records.", "**Goal:**").replace(
            "# S02: Docs\n", "# S02: Docs\n\n<!-- keep the docs short -->\n"), encoding="utf-8")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertEqual(plan.blockers, [])
        groups = {a.detail.split()[1]: a for a in kinds(plan, "write-group-fields")}
        self.assertIn("**Goal:** Export records.\nMilestone M001 delivery envelope.\n", groups["1"].content)
        self.assertIn("**Goal:**\n<!-- keep the docs short -->\n", groups["2"].content)
        self.assertIn("carried into Goal", groups["2"].detail)

    def test_duplicate_sections_and_fields_are_concatenated(self) -> None:
        repo = self.repo()
        plan_dir = repo.add("M001", "add-export", "TODO")
        road = plan_dir / "M001-ROADMAP.md"
        road.write_text(road.read_text(encoding="utf-8") + "\n## Commit and PR conventions\n\nSign every tag.\n",
                        encoding="utf-8")
        for number in (1, 2):
            path = plan_dir / f"M001-S0{number}-PLAN.md"
            text = path.read_text(encoding="utf-8")
            text = text.replace("**Demo:** Run the exporter.", "**Demo:** Run the exporter.\n**Goal:** Keep it small.")
            text += "\n## Must-Haves\n\n- A JSON file.\n\n## Commit and PR conventions\n\nSign every tag.\n"
            path.write_text(text, encoding="utf-8")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertEqual(plan.blockers, [])
        conv = [a for a in kinds(plan, "append-section") if heading(a) == "## Commit and PR Conventions"][0]
        self.assertIn("**Commit title:** short imperative subject.", conv.content)
        self.assertIn("Sign every tag.", conv.content)
        group = [a for a in kinds(plan, "write-group-fields") if a.detail.startswith("group 1 ")][0]
        self.assertIn("**Goal:** Export records.\nKeep it small.\n", group.content)
        must = group.content.split("**Must-Haves:**", 1)[1]
        self.assertLess(must.index("A CSV file."), must.index("A JSON file."))

    def test_bare_container_main_checkout_is_the_first_worktree(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO", branch="DEMO-7")
        repo.commit()
        bare = self.tmp / "container" / ".bare"
        git(self.tmp, "clone", "-q", "--bare", str(repo.root), str(bare))
        wt = self.tmp / "container" / "DEMO-1"
        git(bare, "worktree", "add", "-q", str(wt), BRANCH)
        shutil.copytree(repo.w2c, wt / ".w2c")
        plan = convert.plan_conversion(wt, ["M001"])
        self.assertEqual(plan.blockers, [])
        meta = wt / "openspec" / "changes" / "add-export" / ".openspec.yaml"
        self.assertIn(meta, {a.path for a in kinds(plan, "write-key")})

    def test_delivery_profile_is_copied_under_the_delivery_plan(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO")
        profile = delivery_profile.compose_delivery_profile(strategy="gitflow", ci_pointers=True)
        write(repo.w2c / "DELIVERY-PROFILE.md", profile)
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        copies = [a for a in kinds(plan, "append-section") if heading(a) == "## Delivery Plan > ### Delivery profile"]
        self.assertEqual(len(copies), 1)
        self.assertIn("#### Project Delivery Profile", copies[0].content)
        self.assertIn("##### Gitflow (release train)", copies[0].content)
        self.assertIn("back-merge", copies[0].content)
        profile_path = repo.w2c / "DELIVERY-PROFILE.md"
        flagged = {line for line in profile.splitlines() if convert.FLAG_RE.search(line)}
        known = {old for path, _n, old, _new in plan.known_rewrites if path == profile_path}
        self.assertEqual(known, flagged)
        delivery = [a for a in kinds(plan, "append-section") if heading(a) == "## Delivery Plan"][0]
        self.assertIn("| Integration strategy | gitflow |", delivery.content)

    def test_knowledge_sync_keeps_every_context_line(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO")
        ctx = repo.w2c / "contexts" / "CONTEXTv1.1.md"
        ctx.write_text(ctx.read_text(encoding="utf-8").replace(
            "## Patterns\n", "Rules above apply to every service.\n\n## Patterns\n")
            + "\n## Glossary\n\n- Export: a CSV written to disk.\n", encoding="utf-8")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        sync = kinds(plan, "sync-knowledge")[0]
        self.assertIn("Rules above apply to every service.", sync.content)
        self.assertIn("## Glossary\n- Export: a CSV written to disk.", sync.content)
        self.assertIn("Glossary: 1 (new section)", sync.detail)
        self.assertNotIn("Use UTF-8", sync.content)
        self.assertNotIn("# Project Knowledge", sync.content)

    def test_two_two_only_names_are_flagged(self) -> None:
        repo = self.repo()
        plan_dir = repo.add("M001", "add-export", "TODO", extra="\n- Run milestone-complete at the end.")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        road = plan_dir / "M001-ROADMAP.md"
        self.assertIn((road, "- Run milestone-complete at the end."),
                      {(p, line) for p, _n, line in plan.unknown_w2c_lines})
        self.assertIn("| Setup when | first-do-chores |", {old for _p, _n, old, _new in plan.known_rewrites})

    def test_all_retires_an_empty_roadmap_and_keeps_every_table_row(self) -> None:
        repo = self.repo()
        decisions = repo.w2c / "DECISIONS.md"
        decisions.write_text(decisions.read_text(encoding="utf-8")
                             + "| X1 | 2026-11-02 | project | Imported | Kept | Old tool | No | human |\n",
                             encoding="utf-8")
        repo.commit()
        plan = convert.plan_conversion(repo.root, None)
        self.assertEqual(plan.blockers, [])
        frozen = kinds(plan, "write-decisions-file")
        self.assertEqual(len(frozen), 1)
        for row in ("| D001 |", "| D002 |", "| D003 |", "| D004 |", "| X1 |"):
            self.assertIn(row, frozen[0].content)
        self.assertEqual(frozen[0].content.count("| # | When |"), 1)
        self.assertTrue(kinds(plan, "delete-ledger-file"))

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



FAKE_OPENSPEC = Path(__file__).resolve().parent / "fixtures" / "fake_openspec.py"
OPEN = [(1, "Export", " "), (2, "Docs", " ")]


def migrate(root: Path, milestones: list[str] | None = None, *, all_: bool = False, dry_run: bool = False,
            restore: bool = False, yes_config: bool = False, yes_rewrites: bool = False) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = convert.cmd_migrate(root, milestones, all_, dry_run, restore, yes_config, yes_rewrites)
    return code, out.getvalue()


def snapshot(*bases: Path) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for base in bases:
        real = base.resolve()
        for dirpath, dirs, files in os.walk(real):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in files:
                path = Path(dirpath) / name
                found[path.relative_to(real).as_posix()] = path.read_bytes()
    return found


class ApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="w2c-apply-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        bindir = self.tmp / "bin"
        bindir.mkdir()
        fake = bindir / "openspec"
        fake.write_text(FAKE_OPENSPEC.read_text(encoding="utf-8"), encoding="utf-8")
        fake.chmod(0o755)
        path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(bindir) + os.pathsep + path
        self.addCleanup(lambda: os.environ.__setitem__("PATH", path))
        data = self.tmp / "data"
        old = os.environ.get("W2C_DATA_HOME")
        os.environ["W2C_DATA_HOME"] = str(data)
        self.addCleanup(lambda: os.environ.__setitem__("W2C_DATA_HOME", old or ""))

    def repo(self, base: Path | None = None, **kwargs) -> Repo:
        return Repo(base or self.tmp, **kwargs)

    def ready(self, status: str = "INPROGRESS", **kwargs) -> Repo:
        repo = self.repo(**kwargs)
        repo.add("M001", "add-export", status, slices=OPEN)
        repo.commit()
        return repo

    # ------------------------------------------------------------ the brief's list

    def test_apply_moves_rules_with_matching_fingerprints(self) -> None:
        repo = self.ready()
        plan = convert.plan_conversion(repo.root, ["M001"])
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        design_text = (repo.change("add-export") / "design.md").read_text(encoding="utf-8")
        prints = convert.section_fingerprints(design_text)
        guard = [a for a in plan.actions if a.kind == "append-section" and a.detail.startswith("## Guardrails ")]
        body = "".join(convert._rewrite(a.content, True) for a in guard)
        import hashlib as _h
        self.assertEqual(prints["## Guardrails"], _h.sha256(" ".join(body.split()).encode()).hexdigest())
        for head in layout.DESIGN_HEADINGS:
            self.assertIn(head, prints)
        order = [design_text.index(h + "\n") for h in layout.DESIGN_HEADINGS]
        self.assertEqual(order, sorted(order), "design sections follow the config rule order")
        self.assertIn("**Verify loop**", design_text)
        self.assertIn("| Remote branch | DEMO-1 |", design_text)
        self.assertIn("People export their records.", (repo.change("add-export") / "proposal.md").read_text(encoding="utf-8"))
        self.assertIn("CONVERTED M001 -> add-export", out)
        tasks = (repo.change("add-export") / "tasks.md").read_text(encoding="utf-8")
        self.assertIn(layout.READ_FIRST_MARKER, tasks.split("## 1.")[0])
        self.assertIn("**Goal:** Export records.", tasks)

    def test_unfinished_reports_copied_to_delivery(self) -> None:
        repo = self.repo()
        plan_dir = repo.add("M001", "add-export", "INPROGRESS", slices=[(1, "Export", "x"), (2, "Docs", " ")])
        tasks = repo.change("add-export") / "tasks.md"
        tasks.write_text(TASKS.replace("- [ ] 1.1", "- [x] 1.1"), encoding="utf-8")
        for name in ("S01-T01-SUMMARY.md", "S01-UAT.md", "S01-SUMMARY.md"):
            write(plan_dir / name, f"# {name}\n\nDone.\n")
        repo.commit()
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        delivery = repo.change("add-export") / ".delivery"
        for name in ("S01-T01-SUMMARY.md", "S01-UAT.md", "S01-SUMMARY.md"):
            self.assertEqual((delivery / name).read_bytes(), (plan_dir / name).read_bytes())
        self.assertIn("x-delivery-slices-done: [1]", (repo.change("add-export") / ".openspec.yaml").read_text(encoding="utf-8"))

    def test_decision_rows_copied_and_legacy_file_unchanged(self) -> None:
        repo = self.ready()
        before = (repo.w2c / "DECISIONS.md").read_bytes()
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        self.assertEqual((repo.w2c / "DECISIONS.md").read_bytes(), before)
        design = (repo.change("add-export") / "design.md").read_text(encoding="utf-8")
        section = design.split("## Decisions\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("| D001 | 2026-11-02 | M001 | How to export | CSV | Simple | Yes | human |", section)
        self.assertIn("| # | When |", section)
        self.assertIn("Use the stdlib.", section)
        self.assertNotIn("| D002 |", section)

    def test_knowledge_sync_adds_only_missing_rows(self) -> None:
        repo = self.ready()
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        text = (repo.root / "openspec" / "knowledge.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("| R1 | all | Use UTF-8 | Portability | 2026 |"), 1)
        rules = text.split("## Rules\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("| R1 | all | Use UTF-8 | Portability | 2026 |\n| R2 | all | Keep tests fast | Speed | 2026 |", rules)
        self.assertIn("| P1 | Small modules | src | none |", text.split("## Patterns", 1)[1])
        self.assertIn("| L1 | Slow CI | Big fixtures | Trim | tests |", text.split("## Lessons Learned", 1)[1])
        self.assertNotIn("Old rule", text)
        self.assertIn("openspec/knowledge.md merge=union", (repo.root / ".gitattributes").read_text(encoding="utf-8"))

    def test_converted_marker_reserves_the_id(self) -> None:
        repo = self.ready()
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        self.assertEqual((repo.plan("M001", "add-export") / "CONVERTED").read_text(encoding="utf-8"), "add-export\n")
        self.assertNotIn("M001", (repo.w2c / "ROADMAP.md").read_text(encoding="utf-8"))
        self.assertEqual(w2c.next_milestone_id(repo.root), "M002")
        moved = io.StringIO()
        with contextlib.redirect_stdout(moved):
            self.assertEqual(w2c.cmd_next(repo.root, "M001", None, None), 0)
        self.assertIn("CLOUD_MOVED M001 add-export", moved.getvalue())
        self.assertNotIn("M001", (repo.w2c / "QUEUE.md").read_text(encoding="utf-8"))

    def test_config_edit_waits_for_flag(self) -> None:
        repo = self.ready()
        config = repo.root / "openspec" / "config.yaml"
        before = config.read_bytes()
        code, out = migrate(repo.root, ["M001"], yes_rewrites=True)
        self.assertEqual(code, 0, out)
        self.assertEqual(config.read_bytes(), before)
        self.assertIn("NEED_CONFIG_APPROVAL openspec/config.yaml", out)
        self.assertIn("+context: |", out)
        self.assertIn(layout.DESIGN_MARKER, out)
        self.assertNotIn("COMMIT " + str(repo.root) + " openspec/config.yaml", out)
        shutil.rmtree(self.tmp / "repo")
        repo = self.ready()
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        text = config.read_text(encoding="utf-8")
        for marker in convert.CONFIG_MARKERS:
            self.assertIn(marker, text)
        self.assertEqual(text, "schema: spec-driven\n\n" + layout.CONFIG_RULES_SNIPPET)
        self.assertIn("COMMIT " + str(repo.root) + " openspec/config.yaml", out)

    def test_known_rewrite_waits_for_flag(self) -> None:
        repo = self.ready()
        plan = convert.plan_conversion(repo.root, ["M001"])
        legacy = next(old for _p, _n, old, _new in plan.known_rewrites if old.startswith("- **Status writes**"))
        number = next(n for _p, n, old, _new in plan.known_rewrites if old == legacy)
        code, out = migrate(repo.root, ["M001"], yes_config=True)
        self.assertEqual(code, 0, out)
        design = (repo.change("add-export") / "design.md").read_text(encoding="utf-8")
        self.assertIn(legacy, design)
        self.assertIn(f"NEED_REWRITE_APPROVAL .w2c/plans/M001-add-export/M001-ROADMAP.md:{number} {legacy} -> "
                      f"{convert.KNOWN_REWRITES[legacy]}", out)
        self.assertIn("PENDING_EDIT neutral-artifacts", out)
        self.assertNotIn("VERIFY_FAIL", out)
        shutil.rmtree(self.tmp / "repo")
        repo = self.ready()
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        design = (repo.change("add-export") / "design.md").read_text(encoding="utf-8")
        self.assertNotIn(legacy, design)
        self.assertIn(convert.KNOWN_REWRITES[legacy], design)
        self.assertNotIn("w2c", design.lower())
        self.assertNotIn("PENDING_EDIT", out)

    def test_unknown_line_prints_manual_edit(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO", slices=OPEN, extra="\n- Run w2c smoke before each push.")
        repo.commit()
        road = repo.plan("M001", "add-export") / "M001-ROADMAP.md"
        number = road.read_text(encoding="utf-8").splitlines().index("- Run w2c smoke before each push.") + 1
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        self.assertIn(f"MANUAL_EDIT .w2c/plans/M001-add-export/M001-ROADMAP.md:{number} - Run w2c smoke before each push.", out)
        self.assertIn("- Run w2c smoke before each push.",
                      (repo.change("add-export") / "proposal.md").read_text(encoding="utf-8"))
        self.assertIn("PENDING_EDIT neutral-artifacts", out)

    def test_next_task_is_unchanged(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "INPROGRESS", slices=OPEN)
        tasks = repo.change("add-export") / "tasks.md"
        write(repo.plan("M001", "add-export") / "S01-T01-SUMMARY.md", "# T01\n\nDone.\n")
        tasks.write_text(TASKS.replace("- [ ] 1.1", "- [x] 1.1"), encoding="utf-8")
        repo.commit()
        before = w2c.next_open_task(repo.root, milestone="M001")
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        from w2c.cloud import commands
        after = commands.next_task(repo.root, "M001", None, None)
        self.assertEqual((before.sid, before.tid), ("S02", "T01"))
        self.assertEqual((after.mid, after.sid, after.tid), ("add-export", "S02", "T01"))

    def test_second_run_is_a_no_op(self) -> None:
        repo = self.ready()
        code, out = migrate(repo.root, all_=True, yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        before = snapshot(repo.root)
        for args in (["M001"], None):
            code, out = migrate(repo.root, args, all_=args is None, yes_config=True, yes_rewrites=True)
            self.assertEqual(code, 0, out)
            self.assertIn("NOTHING_TO_CONVERT", out)
            self.assertEqual(snapshot(repo.root), before)

    def test_interrupted_run_can_rerun_and_restore(self) -> None:
        repo = self.ready()
        before = snapshot(repo.root)
        with mock.patch.object(convert, "_verify", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        interrupted = snapshot(repo.root)
        self.assertNotEqual(interrupted, before)
        for dry in (False, True):
            code, out = migrate(repo.root, ["M001"], dry_run=dry, yes_config=True, yes_rewrites=True)
            self.assertEqual(code, 1, out)
            self.assertIn("run w2c cloud migrate --restore first", out)
            self.assertEqual(snapshot(repo.root), interrupted)
        code, out = migrate(repo.root, restore=True)
        self.assertEqual(code, 0, out)
        self.assertEqual(snapshot(repo.root), before)
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        self.assertIn("CONVERTED M001 -> add-export", out)

    def test_all_with_no_legacy_left_writes_decisions_file_and_deletes_ledger(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO", slices=OPEN)
        repo.add("M002", "add-import", "DONE", slices=[(1, "Export", "x"), (2, "Docs", "x")], archive="declined")
        for name in ("M002-VALIDATION.md", "M002-SUMMARY.md"):
            write(repo.plan("M002", "add-import") / name, f"# {name}\n\nDone.\n")
        repo.commit()
        code, out = migrate(repo.root, all_=True, yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        frozen = (repo.root / "openspec" / "decisions.md").read_text(encoding="utf-8")
        for did in ("D002", "D003", "D004"):
            self.assertIn(f"| {did} |", frozen)
        self.assertNotIn("| D001 |", frozen)
        for name in ("STATE.md", "QUEUE.md", "ROADMAP.md", "DECISIONS.md", "contexts"):
            self.assertFalse((repo.w2c / name).exists(), name)
        for mid, slug in (("M001", "add-export"), ("M002", "add-import")):
            self.assertTrue((repo.plan(mid, slug) / "CONVERTED").is_file())
        self.assertEqual(w2c.next_milestone_id(repo.root), "M003")
        self.assertIn(f"COMMIT {repo.root} openspec/decisions.md", out)

    def test_never_commits(self) -> None:
        repo = self.ready()
        head = git(repo.root, "rev-parse", "HEAD")
        refs = git(repo.root, "for-each-ref")
        index = (repo.root / ".git" / "index").read_bytes()
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        self.assertEqual(git(repo.root, "rev-parse", "HEAD"), head)
        self.assertEqual(git(repo.root, "for-each-ref"), refs)
        self.assertEqual((repo.root / ".git" / "index").read_bytes(), index)
        self.assertEqual(git(repo.root, "diff", "--cached", "--name-only"), "")
        changed = git(repo.root, "status", "--porcelain").splitlines()
        self.assertTrue(changed)
        for line in changed:
            path = line[3:].strip()
            self.assertTrue(path in out or path.rstrip("/") in out, (path, out))

    # ------------------------------------------------------------ controller additions

    def test_refuses_after_an_incomplete_manifest(self) -> None:
        repo = self.ready()
        with mock.patch.object(convert, "apply_conversion", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        before = snapshot(repo.root)
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 1)
        self.assertIn("run w2c cloud migrate --restore first", out)
        self.assertEqual(snapshot(repo.root), before)
        runs = sorted(w2c_local.backup_dir_for(repo.root).glob("cloud-migrate-*"))
        self.assertEqual(len(runs), 1)
        manifest = json.loads((runs[0] / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["complete"])

    def test_second_restore_has_nothing_to_restore(self) -> None:
        repo = self.ready()
        before = snapshot(repo.root, repo.w2c)
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        code, out = migrate(repo.root, restore=True)
        self.assertEqual(code, 0, out)
        self.assertIn("RESTORED", out)
        self.assertEqual(snapshot(repo.root, repo.w2c), before)
        code, out = migrate(repo.root, restore=True)
        self.assertEqual(code, 0, out)
        self.assertIn("NOTHING_TO_RESTORE", out)
        self.assertEqual(snapshot(repo.root, repo.w2c), before)

    def test_failed_verify_restores_and_exits_one(self) -> None:
        repo = self.ready()
        before = snapshot(repo.root, repo.w2c)
        os.environ["FAKE_OPENSPEC_VALIDATE"] = "fail"
        self.addCleanup(lambda: os.environ.pop("FAKE_OPENSPEC_VALIDATE", None))
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 1, out)
        self.assertIn("VERIFY_FAIL openspec-validate-strict", out)
        self.assertIn("RESTORED", out)
        self.assertEqual(snapshot(repo.root, repo.w2c), before)
        os.environ.pop("FAKE_OPENSPEC_VALIDATE")
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)

    def test_blockers_are_printed_and_nothing_written(self) -> None:
        repo = self.ready()
        write(repo.plan("M001", "add-export") / "notes.txt", "loose\n")
        before = snapshot(repo.root, repo.w2c)
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED M001: M001-add-export/notes.txt has no target", out)
        self.assertEqual(snapshot(repo.root, repo.w2c), before)
        self.assertFalse(list(w2c_local.backup_dir_for(repo.root).glob("cloud-migrate-*")))

    def test_dry_run_prints_the_plan_and_writes_nothing(self) -> None:
        repo = self.ready()
        before = snapshot(repo.root, repo.w2c)
        code, out = migrate(repo.root, ["M001"], dry_run=True)
        self.assertEqual(code, 0, out)
        for token in ("PLAN write-key openspec/changes/add-export/.openspec.yaml x-delivery-status: INPROGRESS",
                      "PLAN append-section openspec/changes/add-export/design.md ## Guardrails",
                      "NEED_REWRITE_APPROVAL .w2c/plans/M001-add-export/M001-ROADMAP.md:", "NEXT_BEFORE M001 S01 T01",
                      "NEED_CONFIG_APPROVAL openspec/config.yaml", "+context: |"):
            self.assertIn(token, out)
        self.assertNotIn("\nREWRITE ", out)
        code, out = migrate(repo.root, ["M001"], dry_run=True, yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        self.assertIn("\nREWRITE .w2c/plans/M001-add-export/M001-ROADMAP.md:", out)
        self.assertIn("CONFIG_MERGED openspec/config.yaml (dry run; would add):", out)
        self.assertNotIn("NEED_REWRITE_APPROVAL", out)
        self.assertNotIn("NEED_CONFIG_APPROVAL", out)
        self.assertEqual(snapshot(repo.root, repo.w2c), before)
        self.assertFalse(list(w2c_local.backup_dir_for(repo.root).glob("cloud-migrate-*")))
        with mock.patch.object(convert.osl, "cli_check", return_value=(("openspec-cli", "FAIL", "missing"), False)):
            code, out = migrate(repo.root, ["M001"], dry_run=True)
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED openspec is not installed", out)
        self.assertEqual(snapshot(repo.root, repo.w2c), before)

    def test_flow_style_config_prints_manual_config(self) -> None:
        repo = self.ready(config_yaml="schema: spec-driven\nrules: {tasks: [\"Keep it short.\"]}\n")
        config = repo.root / "openspec" / "config.yaml"
        before = config.read_bytes()
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        self.assertEqual(config.read_bytes(), before)
        self.assertIn("MANUAL_CONFIG openspec/config.yaml", out)
        self.assertIn(layout.CONFIG_RULES_SNIPPET.splitlines()[0], out)
        self.assertIn("CONVERTED M001 -> add-export", out)

    def test_config_merges_into_block_rules_without_duplicating_the_key(self) -> None:
        repo = self.ready(config_yaml="schema: spec-driven\n\n" + legacy_openspec.CONFIG_RULES_SNIPPET)
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        text = (repo.root / "openspec" / "config.yaml").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"(?m)^rules:", text)), 1, text)
        self.assertEqual(len(re.findall(r"(?m)^  tasks:", text)), 1, text)
        self.assertEqual(len(re.findall(r"(?m)^context:", text)), 1, text)
        self.assertEqual(len(re.findall(r"(?m)^operations:", text)), 1, text)
        self.assertIn("W2C-OPENSPEC-RULES", text)
        tasks = text.split("  tasks:\n", 1)[1]
        self.assertLess(tasks.index("W2C-OPENSPEC-RULES"), tasks.index(layout.SLICE_TASK_MARKER))
        self.assertIn("  design:\n    - \"" + layout.RULE_PREFIX, text)
        for marker in convert.CONFIG_MARKERS:
            self.assertIn(marker, text)

    def test_drop_applies_only_with_flag_and_prints_reason(self) -> None:
        dropped = "| Commit cadence | (from `.w2c/config.toml` `git_delivery`) |"
        reason = convert.KNOWN_REWRITES[dropped].reason
        for yes in (False, True):
            with self.subTest(yes_rewrites=yes):
                base = self.tmp / f"drop-{yes}"
                base.mkdir()
                repo = Repo(base)
                repo.add("M001", "add-export", "TODO", slices=OPEN)
                write(repo.w2c / "DELIVERY-PROFILE.md",
                      delivery_profile.compose_delivery_profile(strategy="gitflow", ci_pointers=True))
                repo.commit()
                code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=yes)
                self.assertEqual(code, 0, out)
                design = (repo.change("add-export") / "design.md").read_text(encoding="utf-8")
                token = "REWRITE" if yes else "NEED_REWRITE_APPROVAL"
                self.assertRegex(out, rf"(?m)^{token} \.w2c/DELIVERY-PROFILE\.md:\d+ {re.escape(dropped)} -> "
                                      rf"\(drop: {re.escape(reason)}\)$")
                if yes:
                    self.assertNotIn(dropped, design)
                else:
                    self.assertIn(dropped, design)

    def test_worktree_targeted_writes(self) -> None:
        repo = self.repo()
        git(repo.root, "checkout", "-q", "-b", "main")
        repo.add("M001", "add-export", "TODO", slices=OPEN, branch="DEMO-2")
        repo.commit()
        wt = self.tmp / "wt"
        git(repo.root, "worktree", "add", "-q", "-b", "DEMO-2", str(wt))
        main_before = snapshot(repo.change("add-export"))
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        self.assertEqual(snapshot(repo.change("add-export")), main_before)
        meta = (wt / "openspec" / "changes" / "add-export" / ".openspec.yaml").read_text(encoding="utf-8")
        self.assertIn("x-delivery-legacy-id: M001", meta)
        self.assertIn("openspec/knowledge.md merge=union", (wt / ".gitattributes").read_text(encoding="utf-8"))
        self.assertIn(f"COMMIT {wt.resolve()} openspec/changes/add-export/design.md", out)
        self.assertNotIn(f"COMMIT {repo.root.resolve()} openspec/changes", out)

    def test_cli_wires_migrate(self) -> None:
        repo = self.ready()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = w2c.main(["--root", str(repo.root), "cloud", "migrate", "--milestone", "M001", "--dry-run"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("NEXT_BEFORE M001 S01 T01", out.getvalue())
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = w2c.main(["--root", str(repo.root), "cloud", "migrate", "--dry-run"])
        self.assertEqual(code, 1)
        self.assertIn("--milestone or --all", err.getvalue())


    def test_merge_config_forms(self) -> None:
        merged = convert.merge_config("context: |\n    Old line.\nrules:\n  tasks:\n  - \"keep\"\n"
                                      "operations:\n  archive:\n    guidance:\n      - a\n")
        self.assertTrue(merged.startswith("context: |\n    Old line.\n    Project knowledge"), merged)
        self.assertIn("  - \"keep\"\n  - \"" + layout.RULE_PREFIX + " " + layout.SLICE_TASK_MARKER, merged)
        self.assertIn("operations:\n  archive:\n    guidance:\n      - a\n  apply:\n    guidance:\n      - \"", merged)
        for key in ("context", "rules", "operations"):
            self.assertEqual(len(re.findall(rf"(?m)^{key}:", merged)), 1, key)
        self.assertEqual(convert.merge_config(merged), merged)
        for unsafe in ("rules:\n  design: [a]\n", "context: hello\n", "rules: &base\n  tasks:\n  - a\n",
                       "rules:\n\ttasks:\n", "operations: {apply: {}}\n"):
            with self.subTest(text=unsafe):
                with self.assertRaises(convert._Unsafe):
                    convert.merge_config(unsafe)


    def test_milestone_with_legacy_id_is_skipped(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "TODO", slices=OPEN)
        meta = repo.change("add-export") / ".openspec.yaml"
        meta.write_text(meta.read_text(encoding="utf-8").replace("x-w2c-milestone:", "x-delivery-legacy-id:"),
                        encoding="utf-8")
        repo.commit()
        plan = convert.plan_conversion(repo.root, ["M001"])
        self.assertEqual((plan.skipped, plan.actions, plan.blockers), (["M001"], [], []))
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        self.assertIn("SKIPPED M001", out)
        self.assertIn("NOTHING_TO_CONVERT", out)


    # ------------------------------------------------------------ fix round 1

    def test_restore_of_a_complete_run_refuses_after_later_edits(self) -> None:
        repo = self.ready()
        before = snapshot(repo.root, repo.w2c)
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        design = repo.change("add-export") / "design.md"
        road = repo.w2c / "ROADMAP.md"
        kept_design, kept_road = design.read_bytes(), road.read_bytes()
        design.write_bytes(kept_design + b"\nA later note.\n")
        road.write_bytes(kept_road + b"- later line\n")
        edited = snapshot(repo.root, repo.w2c)
        code, out = migrate(repo.root, restore=True)
        self.assertEqual(code, 1, out)
        self.assertIn(f"CHANGED_SINCE_RUN {design}", out)
        self.assertIn(f"CHANGED_SINCE_RUN {road.resolve()}", out)
        self.assertIn("RESTORE_REFUSED 2 file(s)", out)
        self.assertEqual(snapshot(repo.root, repo.w2c), edited)
        design.write_bytes(kept_design)
        road.write_bytes(kept_road)
        write(repo.w2c / "runtime" / "later.txt", "kept\n")
        code, out = migrate(repo.root, restore=True)
        self.assertEqual(code, 0, out)
        after = snapshot(repo.root, repo.w2c)
        self.assertEqual(after.pop("runtime/later.txt"), b"kept\n")
        self.assertEqual(after.pop(".w2c/runtime/later.txt"), b"kept\n")
        self.assertEqual(after, before)

    def test_linked_change_folder_outside_the_checkout_is_refused(self) -> None:
        repo = self.repo()
        repo.add("M001", "add-export", "INPROGRESS", slices=OPEN)
        outside = self.tmp / "outside"
        folder = repo.change("add-export")
        shutil.move(str(folder), str(outside))
        folder.symlink_to(outside, target_is_directory=True)
        repo.commit()
        before_outside = snapshot(outside)
        before = snapshot(repo.root, repo.w2c)
        with self.assertRaises(w2c.W2CError) as caught:
            migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertIn("not inside a checkout", str(caught.exception))
        self.assertEqual(snapshot(outside), before_outside)
        self.assertEqual(snapshot(repo.root, repo.w2c), before)
        self.assertEqual(convert._runs(repo.root), [], "refused before any backup was made")

    def test_restore_refuses_a_manifest_that_points_outside(self) -> None:
        repo = self.ready()
        code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
        self.assertEqual(code, 0, out)
        victim = self.tmp / "outside" / "keep.txt"
        write(victim, "keep")
        run = convert._runs(repo.root)[-1]
        manifest = convert._read_manifest(run)
        manifest["files"].append({"path": str(victim), "checkout": str(repo.root), "state": "absent",
                                  "created_dirs": []})
        convert._write_manifest(run, manifest)
        after_run = snapshot(repo.root, repo.w2c)
        with self.assertRaises(w2c.W2CError) as caught:
            migrate(repo.root, restore=True)
        self.assertIn("refusing to restore", str(caught.exception))
        self.assertIn(str(victim), str(caught.exception))
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep\n")
        self.assertEqual(snapshot(repo.root, repo.w2c), after_run)

    def test_tracked_ledger_paths_are_listed_to_commit(self) -> None:
        for track in (True, False):
            with self.subTest(track=track):
                base = self.tmp / f"track-{track}"
                base.mkdir()
                repo = Repo(base)
                config = repo.w2c / "config.toml"
                config.write_text(config.read_text(encoding="utf-8").replace(
                    "track = true", f"track = {'true' if track else 'false'}"), encoding="utf-8")
                if track:
                    write(repo.root / ".gitignore", "")
                repo.add("M001", "add-export", "TODO", slices=OPEN)
                repo.commit()
                code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
                self.assertEqual(code, 0, out)
                ledger_lines = [line for line in out.splitlines() if line.startswith(f"COMMIT {repo.root} .w2c/")]
                if not track:
                    self.assertEqual(ledger_lines, [])
                    continue
                for rel in ("ROADMAP.md", "STATE.md", "plans/M001-add-export/CONVERTED"):
                    self.assertIn(f"COMMIT {repo.root} .w2c/{rel}", ledger_lines)
                status = {line[3:].strip() for line in git(repo.root, "status", "--porcelain",
                                                            "--untracked-files=all", "--", ".w2c").splitlines()}
                self.assertEqual(status, {line.split(" ", 2)[2] for line in ledger_lines})

    def test_verify_catches_changes_outside_the_placed_text(self) -> None:
        real_append, real_fields, real_merge = (convert._append_to_section, convert._insert_group_fields,
                                                convert.merge_config)
        breakers = {
            "untouched section": ("_append_to_section",
                                  lambda *a, **k: real_append(*a, **k).replace("Need export.", "Need nothing.")),
            "task line": ("_insert_group_fields",
                          lambda *a, **k: real_fields(*a, **k).replace("Write the exporter", "Write it")),
            "config item twice": ("merge_config", lambda text, *a: real_merge(text, *a) + "\n".join(
                real_merge(text, *a).splitlines()[-2:]) + "\n"),
        }
        expected = {"untouched section": "VERIFY_FAIL section-fingerprint openspec/changes/add-export/proposal.md ## Why",
                    "task line": "VERIFY_FAIL section-fingerprint openspec/changes/add-export/tasks.md ## 1. Export",
                    "config item twice": "VERIFY_FAIL config openspec/config.yaml"}
        for name, (attr, broken) in breakers.items():
            with self.subTest(case=name):
                base = self.tmp / name.replace(" ", "-")
                base.mkdir()
                repo = Repo(base)
                repo.add("M001", "add-export", "INPROGRESS", slices=OPEN)
                repo.commit()
                before = snapshot(repo.root, repo.w2c)
                with mock.patch.object(convert, attr, side_effect=broken):
                    code, out = migrate(repo.root, ["M001"], yes_config=True, yes_rewrites=True)
                self.assertEqual(code, 1, out)
                self.assertIn(expected[name], out)
                self.assertIn("RESTORED", out)
                self.assertEqual(snapshot(repo.root, repo.w2c), before)

    def test_merge_checks_presence_inside_the_key_block_only(self) -> None:
        item = next(line.strip() for line in layout.CONFIG_RULES_SNIPPET.splitlines() if layout.READ_FIRST_MARKER in line)
        text = f"schema: x\noperations:\n  archive:\n    guidance:\n      {item}\n"
        merged = convert.merge_config(text)
        self.assertEqual(convert.config_problems(merged), [])
        self.assertEqual(merged.count(item), 2, merged)
        self.assertIn(f"  apply:\n    guidance:\n      {item}\n", merged)
        self.assertEqual(convert.merge_config(merged), merged)


if __name__ == "__main__":
    unittest.main()
