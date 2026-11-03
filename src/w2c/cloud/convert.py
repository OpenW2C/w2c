"""Convert 2.2 OpenSpec milestones to cloud changes (`w2c cloud migrate`).

`plan_conversion` reads the 2.2 ledger, the plan folders, and the target
changes, and returns every action and every blocker. It writes nothing. Every
source section maps to a target, is consumed into a key, is a documented drop
(`layout.LEGACY_DROPPED_FIELDS`, `layout.LEGACY_DROPPED_GUARDRAILS`), or is a
blocker.

`cmd_migrate` applies a plan: it refuses on blockers, backs up `.w2c/` and every
target file under a per-run manifest, applies the actions, verifies them, and
restores exactly when verification fails. It never runs a mutating git command.
The CLI package is imported lazily.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from w2c import ledger_store
from w2c import local as w2c_local
from w2c import openspec_ledger as osl
from w2c.cloud import checks, commands, layout, ledger

ACTION_KINDS: tuple[str, ...] = (
    "write-key",
    "rename-key",
    "append-section",
    "write-group-fields",
    "write-read-first",
    "copy-report",
    "copy-decisions",
    "sync-knowledge",
    "edit-config",
    "edit-gitattributes",
    "mark-converted",
    "roadmap-remove",
    "write-decisions-file",
    "delete-ledger-file",
)

APPEND_NEW = "new"
NOT_SET = "(not set in the 2.2 plan)"
APPEND_EXISTING = "append-to-existing"
CLASSIC_HINT = "re-plan it with work to chores cloud"
LEGACY_LINK_KEY = "x-w2c-milestone"
LEDGER_FILES: tuple[str, ...] = ("STATE.md", "QUEUE.md", "ROADMAP.md", "DECISIONS.md", "contexts")
DECISIONS_FILE = "openspec/decisions.md"
KNOWLEDGE_SECTIONS: tuple[str, ...] = ("Rules", "Patterns", "Lessons Learned")
CONFIG_KEYS: tuple[str, ...] = ("context", "rules", "operations")
CONFIG_MARKERS: tuple[str, ...] = (layout.DESIGN_MARKER, layout.SLICE_TASK_MARKER, layout.READ_FIRST_MARKER)

_PROPOSAL_FROM_ROADMAP = ("Success Criteria", "Boundary Map", "In scope", "Out of scope", "Soft dependency")
_SLICE_SECTION_FIELDS = tuple(f for f in layout.SLICE_FIELDS if f not in ("Goal", "Demo"))

SECTION_MAP: dict[tuple[str, str], tuple[str, str]] = {
    ("roadmap", "**Vision:**"): ("proposal.md", "## Vision"),
    **{("roadmap", f"## {h}"): ("proposal.md", f"## {h}") for h in _PROPOSAL_FROM_ROADMAP},
    ("roadmap", "## Delivery & Guardrails"): ("design.md", "## Delivery Plan"),
    ("roadmap", "## Git Operation Plan"): ("design.md", "## Delivery Plan"),
    ("roadmap", "### Base dirt paths"): ("design.md", "## Delivery Plan"),
    ("roadmap", "### Guardrails"): ("design.md", "## Guardrails"),
    ("roadmap", "## Commit and PR conventions"): ("design.md", "## Commit and PR Conventions"),
    ("roadmap", "## Slices"): (".openspec.yaml", "x-delivery-slices-done"),
    ("context", "## Problem"): ("proposal.md", "## Problem"),
    ("context", "## Solution"): ("proposal.md", "## Solution"),
    ("context", "## Out of Scope"): ("proposal.md", "## Out of Scope"),
    ("context", "## Key Decisions"): ("design.md", "## Decisions"),
    ("context", "## Decision Rationale"): ("design.md", "## Decisions"),
    ("context", "## Validation"): ("design.md", "## Guardrails"),
    ("context", "## Completion Criteria"): ("design.md", "## Guardrails"),
    ("slice", "**Goal:**"): ("tasks.md", "**Goal:**"),
    ("slice", "text before the first heading"): ("tasks.md", "**Goal:**"),
    ("slice", "**Demo:**"): ("tasks.md", "**Demo:**"),
    **{("slice", f"## {f}"): ("tasks.md", f"**{f}:**") for f in _SLICE_SECTION_FIELDS},
    ("slice", "## Git Operation Plan"): ("design.md", "## Delivery Plan"),
    ("slice", "### Guardrails"): ("design.md", "## Guardrails"),
    ("slice", "## Commit and PR conventions"): ("design.md", "## Commit and PR Conventions"),
    ("manual-test", "MANUAL-TEST.md"): ("design.md", "## Manual Test Guide"),
    ("amendments", "AMENDMENTS.md"): ("design.md", "## Amendments"),
    ("profile", "DELIVERY-PROFILE.md"): ("design.md", "## Delivery Plan"),
    ("knowledge", "CONTEXTvX.Y.md"): ("openspec/knowledge.md", "the same heading"),
}

# Context sections land inside a design section as `###` subsections.
SUBSECTIONS: dict[tuple[str, str], str] = {
    ("context", "## Key Decisions"): "### Key Decisions",
    ("context", "## Decision Rationale"): "### Decision Rationale",
    ("context", "## Validation"): "### Validation",
    ("context", "## Completion Criteria"): "### Completion Criteria",
    ("profile", "DELIVERY-PROFILE.md"): "### Delivery profile",
}

_NEUTRAL_CADENCE = (
    "- **Commit cadence** — commit, push and pull-request timing follows the change's "
    "`x-delivery-cadence` key in `.openspec.yaml`. Every commit, push and pull request still needs "
    "explicit user approval. Never commit, push, or open a PR without explicit user approval for that action."
)
_NEUTRAL_STATUS = (
    "- **Status writes** — tick task boxes only through the task-tracking command, never by hand. "
    "Never hand-edit status fields in the change metadata."
)
_NEUTRAL_COMMIT_PR = (
    "- **Commit and PR** — honor `## Commit and PR Conventions`. Never add `Co-authored-by:` or similar "
    "AI co-author trailers. Never stage deny-listed paths on product commits. Never mention any "
    "`.delivery/` path or local planner file in commit or PR text."
)
_NEUTRAL_INSPECT = (
    "Planner: inspect this repo (`CONTRIBUTING*`, `.github/*PULL_REQUEST_TEMPLATE*`, recent `git log` "
    "title and body, `.gitignore`) and fill this section. Do not leave TBD."
)
_NEUTRAL_DENY = (
    "Planner: fill a deny-list of any local planner files and notable paths from the client `.gitignore` "
    "(e.g. `.env*`, credentials, local IDE junk), plus any `### Base dirt paths` listed in the Delivery "
    "Plan. Product commits must never stage these paths. The change's `.delivery/` reports are not "
    "deny-listed: they are committed with the slice and milestone commits of the product work."
)
_NEUTRAL_MENTION = (
    "Never name any `.delivery/` path, local planner files, or closeout reports (`*-SUMMARY.md` / "
    "`*-UAT.md` / `VALIDATION.md`) in the commit title/body or PR title/body/description. Say "
    '"planning artifacts" with no paths.'
)
_LEGACY_DENY = (
    "Planner: fill a deny-list. Always include `.w2c/runtime/`. When `track = false`, include all of "
    "`.w2c/` and Copilot W2C instruction files. Add notable paths from client `.gitignore` (e.g. `.env*`, "
    "credentials, local IDE junk). Product commits must never stage these paths. Plan-commit (only when "
    "`track = true`) may stage ledger/plan files under `.w2c/` except `runtime/`."
)
_LEGACY_MENTION = (
    "Never name any `.w2c/` path, ledger file, closeout report (`*-SUMMARY.md` / `*-UAT.md` / "
    "`*-VALIDATION.md` under `.w2c/`), or other W2C artifact in the commit title/body or PR "
    "title/body/description. Prefer “W2C ledger” / “planning artifacts” with no paths."
)
_LEGACY_INSPECT = (
    "Planner: inspect this repo (`CONTRIBUTING*`, `.github/*PULL_REQUEST_TEMPLATE*`, recent `git log` "
    "title/body, `.gitignore`, `.w2c/config.toml` `track`) and fill this section. Do not leave TBD."
)
_LEGACY_COMMIT_PR = (
    "- **Commit and PR** — honor `## Commit and PR conventions`. Never add `Co-authored-by:` or similar "
    "AI co-author trailers. Never stage deny-listed paths on product commits. Never mention any `.w2c/` "
    "path or artifact in commit or PR text."
)
_LEGACY_SLICE_COMMIT_PR = (
    "- Honor `## Commit and PR conventions` (copy the filled rules from the milestone {who}; do not say "
    "“see parent”). Never add `Co-authored-by:` or similar AI co-author trailers. Never stage "
    "deny-listed paths on product commits. Never mention any `.w2c/` path or artifact in commit or PR text."
)
_LEGACY_SLICE_CADENCE = (
    "- Honor this slice Git Operation Plan, the milestone Git Operation Plan, and `git_delivery` from "
    "`.w2c/config.toml`. Never commit, push, or open a PR without explicit user approval for that action."
)
_LEGACY_SLICE_STATUS = "- Do not mark tasks complete by editing checkboxes. Use `w2c complete`."

_NEUTRAL_CLOSEOUT = (
    "- **Closeout reports** — write `S##-T##-SUMMARY.md` before completing a task; `S##-UAT.md` and "
    "`S##-SUMMARY.md` before completing a slice; `VALIDATION.md` and `SUMMARY.md` before the change is "
    "done. All live under `.delivery/`."
)
_NEUTRAL_SLICE_ORDER = (
    "- **Slice closeout order** — after a group's last task, re-run every Verify in that group, then write "
    "the slice UAT and slice summary, then complete the slice. After the last group, write `VALIDATION.md` "
    "and `SUMMARY.md`, then archive the change, then complete it."
)
_NEUTRAL_AI = (
    'Do not add `Co-authored-by:` trailers or similar AI co-author / "assisted by" lines naming any AI tool.'
)
_NEUTRAL_PRODUCT = (
    "`openspec/` is product content and is never deny-listed. Product commits stage only this change's "
    "folder plus the archive result."
)
_NEUTRAL_PROFILE_READ = "Record active delivery settings here. Agents read this after the Delivery Plan rows above."
_NEUTRAL_PROFILE_SCOPE = (
    "Scope, slices, and tasks live in this change's proposal.md and tasks.md — not in this subsection."
)
_NEUTRAL_PROFILE_CADENCE = (
    "Commit, push and pull-request cadence is the change's `x-delivery-cadence` key only — never duplicate "
    "that value in this subsection."
)
_NEUTRAL_PROFILE_HANDOFF = (
    "- Task Handoff Gate still applies between tasks even when commits land at slice boundaries "
    "(`x-delivery-cadence`)."
)
_NEUTRAL_PROFILE_MERGE = (
    "- Honor this profile for merge targets (`develop` vs `main`); honor `x-delivery-cadence` for when to "
    "ask commit/push/PR."
)
_LEGACY_CLOSEOUT = (
    "- **Closeout reports** — write `S##-T##-SUMMARY.md` before `complete`; `S##-UAT.md` + `S##-SUMMARY.md` "
    "before `slice-complete`; `M###-VALIDATION.md` + `M###-SUMMARY.md` before milestone DONE."
)


@dataclass(frozen=True)
class Drop:
    """A legacy line whose rule has no place in a cloud change: dropped, with a reason, on approval."""

    reason: str

    def __str__(self) -> str:
        return f"DROP ({self.reason})"


# 2.2-only names that mark a copied line for a rewrite or a manual edit.
FLAG_RE = re.compile(
    r"w2c|git_delivery|milestone-complete|first-do-chores|M(?:\d+|#+)-(?:VALIDATION|SUMMARY)\.md", re.I
)

# Every 2.x template line that holds a flagged name, mapped to the neutral line in
# templates/cloud/ that carries the same rule, or to a Drop when the rule has no
# place in a cloud change. Applied only with approval.
KNOWN_REWRITES: dict[str, str | Drop] = {
    "| Integration strategy | (from .w2c/DELIVERY-PROFILE.md) |":
        "| Integration strategy | (from the project's delivery profile) |",
    "| Commit cadence | (from .w2c/config.toml git_delivery) |":
        Drop(layout.LEGACY_DROPPED_FIELDS["Commit cadence"]),
    "| Setup when | first-do-chores |": "| Setup when | first-task |",
    "| Completion condition | All slices verified; honor git_delivery + explicit approval gates |":
        "| Completion condition | All slices verified; honor x-delivery-cadence and explicit approval gates |",
    "- **Commit cadence** — read `git_delivery` from `.w2c/config.toml`. Never commit, push, or open a "
    "PR without explicit user approval for that action.": _NEUTRAL_CADENCE,
    "- **Plan commit** — when `track` is false, write `ledger-bind` and do not commit `.w2c/`. The `w2c` "
    "command shares one ledger across worktrees. When `track` is true, a separate plan commit may include "
    "`.w2c/` plan files except `runtime/`. No push without approval.":
        Drop(layout.LEGACY_DROPPED_GUARDRAILS["Plan commit"]),
    "- **Status writes** — never hand-edit STATE.md, QUEUE.md, ROADMAP status emojis, or task checkboxes. "
    "Use `w2c` on PATH. `w2c complete` is the only writer of checkboxes in `tasks.md`.": _NEUTRAL_STATUS,
    "- **Status writes** — never hand-edit STATE.md, QUEUE.md, ROADMAP status emojis, or task checkboxes. "
    "Use `w2c` on PATH.": _NEUTRAL_STATUS,
    "- **Status writes** — never hand-edit STATE.md, QUEUE.md, ROADMAP status emojis, or task checkboxes. "
    "Use `.w2c/scripts/w2c.sh`.": _NEUTRAL_STATUS,
    _LEGACY_CLOSEOUT: _NEUTRAL_CLOSEOUT,
    _LEGACY_CLOSEOUT + " Manual test steps in `M###-MANUAL-TEST.md` (if opted in) are for the human after "
    "DONE — they do not gate completeness.": _NEUTRAL_CLOSEOUT,
    _LEGACY_COMMIT_PR: _NEUTRAL_COMMIT_PR,
    _LEGACY_INSPECT: _NEUTRAL_INSPECT,
    _LEGACY_DENY: _NEUTRAL_DENY,
    _LEGACY_MENTION: _NEUTRAL_MENTION,
    _LEGACY_SLICE_STATUS: _NEUTRAL_STATUS,
    _LEGACY_SLICE_CADENCE: _NEUTRAL_CADENCE,
    _LEGACY_SLICE_COMMIT_PR.format(who="roadmap"): _NEUTRAL_COMMIT_PR,
    _LEGACY_SLICE_COMMIT_PR.format(who="ROADMAP"): _NEUTRAL_COMMIT_PR,
    "- After the last slice: write `M###-VALIDATION.md` + `M###-SUMMARY.md`, then archive, then "
    "`milestone-complete`.": _NEUTRAL_SLICE_ORDER,
    "- After the last slice: write `M###-VALIDATION.md` + `M###-SUMMARY.md`, then `milestone-complete`.":
        _NEUTRAL_SLICE_ORDER,
    "<!-- REQUIRED literal format -- the w2c CLI's parse_slices() only recognizes this exact":
        Drop("2.2 slice-line format note; in a cloud change a slice is a ## N. task group"),
    "     checkbox line shape. A markdown table (or any other shape) here means w2c will see":
        Drop("2.2 slice-line format note; in a cloud change a slice is a ## N. task group"),
    "     ZERO slices, and slice-complete / milestone-complete will fail with":
        Drop("2.2 slice-line format note; in a cloud change a slice is a ## N. task group"),
    # templates/M-MANUAL-TEST.md
    "This file is an **optional human guide**. It is **not** a completeness gate: `w2c milestone-complete` "
    "does not require these steps to have been run.": layout.MANUAL_GUIDE_NOTES[0],
    "When to stop and call the milestone’s behavior good enough. This is not a `w2c` status bit.":
        layout.MANUAL_GUIDE_NOTES[1],
    # templates/DELIVERY-PROFILE.md and the profile w2c composes
    "Record active delivery settings here. Agents read this **after** the abstract workflow files in "
    "`.w2c/`.": _NEUTRAL_PROFILE_READ,
    "Per-milestone scope, slices, and tasks live in **`.w2c/plans/`** — not in this file.": _NEUTRAL_PROFILE_SCOPE,
    "`w2c init` does **not** create this file. Configure-client or agents write it after interviewing "
    "Integration strategy and (separately) CI/CD pointers. Commit/push/PR **cadence** stays in "
    "`.w2c/config.toml` `git_delivery` — never duplicate that enum here.": _NEUTRAL_PROFILE_CADENCE,
    "Commit/push/PR **cadence** is `.w2c/config.toml` `git_delivery` only — do not duplicate that enum in "
    "this file.": _NEUTRAL_PROFILE_CADENCE,
    "| Commit cadence | (from `.w2c/config.toml` `git_delivery`) |":
        Drop(layout.LEGACY_DROPPED_FIELDS["Commit cadence"]),
    "- Task Handoff Gate still applies between tasks even when commits land at slice boundaries "
    "(`git_delivery`).": _NEUTRAL_PROFILE_HANDOFF,
    "- Honor this profile for merge targets (`develop` vs `main`); honor `git_delivery` for when to ask "
    "commit/push/PR.": _NEUTRAL_PROFILE_MERGE,
}

# Required neutral Conventions lines, by the validate_conventions problem they answer.
CONVENTIONS_REPAIRS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Co-authored-by", ("**AI attribution — forbidden:**", _NEUTRAL_AI)),
    ("staging deny-listed", ("**Do not stage / commit:**", _NEUTRAL_DENY)),
    (".delivery/", ("**Do not mention:**", _NEUTRAL_MENTION)),
    ("product content", (_NEUTRAL_PRODUCT,)),
)

# Slice-plan template lines whose rule the change carries once for every group.
SLICE_TEMPLATE_GUARDRAILS: frozenset[str] = frozenset({
    _LEGACY_SLICE_STATUS,
    "- A task is not done until Verify passes, requesting-code-review is clean, and `S##-T##-SUMMARY.md` is written.",
    "- After the last task in this slice: re-run Verify, write `S##-UAT.md` + `S##-SUMMARY.md`, then `slice-complete`.",
    "- After the last slice: write `M###-VALIDATION.md` + `M###-SUMMARY.md`, then archive, then `milestone-complete`.",
    "- After the last slice: write `M###-VALIDATION.md` + `M###-SUMMARY.md`, then `milestone-complete`.",
    _LEGACY_SLICE_CADENCE,
    _LEGACY_SLICE_COMMIT_PR.format(who="roadmap"),
    _LEGACY_SLICE_COMMIT_PR.format(who="ROADMAP"),
    "- Never force-reset, force-push, or delete worktrees/branches.",
})
# Slice-plan template prose that only points at the milestone; consumed.
SLICE_TEMPLATE_PROSE: frozenset[str] = frozenset({
    "This slice is delivery context only. Task checkboxes live in the OpenSpec change `tasks.md` under the "
    "matching `## N.` group. Do not add task lines here.",
    "Must match the parent milestone Git Operation Plan (same Isolation mode, Local branch, Remote branch, "
    "and Base dirt policy). When the milestone policy is `leave-untouched`, copy its `### Base dirt paths` "
    "subsection here.",
    "Must match the parent `M###-ROADMAP.md` Git Operation Plan (same Isolation mode, Local branch, Remote "
    "branch, and Base dirt policy). When the milestone policy is `leave-untouched`, copy its `### Base dirt "
    "paths` subsection here.",
})
# Instruction lines that differ between the roadmap and slice conventions templates.
_CONVENTIONS_INSTRUCTIONS = (
    "Planner: inspect this repo",
    "Copy the filled rules from the parent",
)
_SLICE_ONLY_PLAN_FIELDS = frozenset({"Follow"})
_PROFILE_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Integration strategy", ("Integration strategy",)),
    ("Integration branch", ("Integration branch (day-to-day)", "Integration branch")),
    ("Production branch", ("Production branch",)),
)

HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*$")
SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|\s*$")
BULLET_LABEL_RE = re.compile(r"^- \*\*(.+?)\*\*")
BOLD_FIELD_RE = re.compile(r"^\*\*([^*\n]+?):\*\*[ \t]*(.*)$")
SLICE_BOX_RE = re.compile(r"^- \[[ xXdD]\] \*\*S\d+:")
DECISION_LINE_RE = re.compile(r"^\|\s*(D\d+)\s*\|")
DECISION_HEADER_RE = re.compile(r"^\|\s*#\s*\|\s*When\s*\|")
CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
AMEND_HEAD_RE = re.compile(r"^## (A\d+) (\S+) (\S+)[ \t]*$")
TASK_REPORT_RE = re.compile(r"^S\d+-T\d+-SUMMARY\.md$")
SLICE_REPORT_RE = re.compile(r"^S\d+-(UAT|SUMMARY)\.md$")

Record = tuple[Path, int | None, str]


def _cli():
    from w2c import cli as w2c_cli

    return w2c_cli


def checkouts(root: Path) -> list[tuple[Path, str]]:
    """(path, branch) of every non-bare worktree; the first is the main checkout."""
    if not ledger_store.is_git(root):
        return [(root, "")]
    proc = ledger_store.git(root, "worktree", "list", "--porcelain", check=False)
    found: list[tuple[Path, str]] = []
    for block in re.split(r"\n\s*\n", proc.stdout.strip()) if proc.returncode == 0 else []:
        lines = block.splitlines()
        if not lines or not lines[0].startswith("worktree ") or "bare" in lines:
            continue
        path = Path(lines[0].split(" ", 1)[1])
        if not path.is_dir():
            continue
        if path.resolve() == root.resolve():
            path = root
        found.append((path, ledger_store.current_branch(path)))
    return found or [(root, ledger_store.current_branch(root))]


@dataclass
class Action:
    kind: str
    path: Path
    detail: str
    # The exact text to place (before approved rewrites), when the kind places text.
    content: str = ""


@dataclass
class ConversionPlan:
    actions: list[Action] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    known_rewrites: list[tuple[Path, int, str, str | Drop]] = field(default_factory=list)
    unknown_w2c_lines: list[tuple[Path, int, str]] = field(default_factory=list)
    next_before: dict[str, tuple[str, str, str] | None] = field(default_factory=dict)
    # Milestones whose change already carries x-delivery-legacy-id: nothing to do.
    skipped: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ parsing


@dataclass
class _Section:
    level: int
    title: str
    heading: Record | None
    body: list[Record]


def _records(path: Path) -> list[Record]:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return [(path, number, line) for number, line in enumerate(text.splitlines(), start=1)]


def _split(lines: list[Record], level: int) -> tuple[list[Record], list[_Section]]:
    """Preamble and the sections at `level` (`##` = 2). Fenced code is body."""
    preamble: list[Record] = []
    sections: list[_Section] = []
    fenced = False
    for record in lines:
        text = record[2]
        if FENCE_RE.match(text):
            fenced = not fenced
        match = None if fenced else HEADING_RE.match(text)
        if match and len(match.group(1)) == level:
            sections.append(_Section(level, match.group(2), record, []))
            continue
        if sections:
            sections[-1].body.append(record)
        else:
            preamble.append(record)
    return preamble, sections


def _heading(record: Record) -> tuple[int, str] | None:
    match = HEADING_RE.match(record[2])
    return (len(match.group(1)), match.group(2)) if match else None


def _strip_frontmatter(lines: list[Record]) -> list[Record]:
    if lines and lines[0][2].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index][2].strip() == "---":
                return lines[index + 1 :]
    return lines


def _trim(lines: list[Record]) -> list[Record]:
    start, end = 0, len(lines)
    while start < end and not lines[start][2].strip():
        start += 1
    while end > start and not lines[end - 1][2].strip():
        end -= 1
    return lines[start:end]


def _text(lines: list[Record]) -> str:
    return "".join(line[2] + "\n" for line in lines)


def _gen(text: str) -> Record:
    return (Path(), None, text)


def _comment_free(lines: list[Record]) -> list[Record]:
    """Lines outside HTML comments."""
    out: list[Record] = []
    inside = False
    for record in lines:
        text = record[2]
        if inside:
            if "-->" in text:
                inside = False
            continue
        if text.lstrip().startswith("<!--"):
            inside = "-->" not in text
            continue
        out.append(record)
    return out


def _subsections(body: list[Record]) -> tuple[list[Record], list[_Section]]:
    return _split(body, 3)


def _table(lines: list[Record]) -> tuple[list[tuple[str, str, Record]], list[Record]]:
    """(field, value, record) rows of `| Field | Value |` tables, and the other lines."""
    rows: list[tuple[str, str, Record]] = []
    other: list[Record] = []
    for record in lines:
        text = record[2]
        if text.lstrip().startswith("|"):
            if SEPARATOR_RE.match(text.strip()):
                continue
            match = ROW_RE.match(text.strip())
            if match:
                key, value = match.group(1).strip(), match.group(2).strip()
                if key.lower() == "field":
                    continue
                rows.append((key, value, record))
                continue
        other.append(record)
    return rows, other


def _has_heading(text: str, heading: str) -> bool:
    return re.search(rf"^{re.escape(heading)}[ \t]*$", text, re.M) is not None


def _norm(lines: list[Record], skip_prefixes: tuple[str, ...] = ()) -> list[str]:
    out = []
    for record in lines:
        text = record[2].strip()
        if not text or any(text.startswith(prefix) for prefix in skip_prefixes):
            continue
        out.append(text)
    return out


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in CELL_SPLIT_RE.split(line.strip())[1:-1]]


# ------------------------------------------------------------------ planner


class _Planner:
    def __init__(self, root: Path) -> None:
        self.cli = _cli()
        self.root = root
        self.wdir = root / ".w2c"
        self.plan = ConversionPlan()
        self.config = w2c_local.load_repo_config(root)
        self.checkouts = self._checkouts()
        self.touched: dict[Path, list[str]] = {}
        self.copied_scopes: set[str] = set()
        self._created: set[tuple[Path, str]] = set()
        self._scanned: set[tuple[Path, int | None, str]] = set()

    # ---------------------------------------------------------- helpers

    def block(self, message: str) -> None:
        if message not in self.plan.blockers:
            self.plan.blockers.append(message)

    def act(self, kind: str, path: Path, detail: str, content: str = "") -> None:
        self.plan.actions.append(Action(kind, path, detail, content))

    def scan(self, lines: list[Record]) -> None:
        """Sort copied lines that hold a 2.2-only name into known rewrites and manual edits."""
        for path, number, text in lines:
            if not FLAG_RE.search(text):
                continue
            key = (path, number, text)
            if key in self._scanned:
                continue
            self._scanned.add(key)
            if text in KNOWN_REWRITES:
                self.plan.known_rewrites.append((path, number or 0, text, KNOWN_REWRITES[text]))
            else:
                self.plan.unknown_w2c_lines.append((path, number or 0, text))

    def _checkouts(self) -> list[tuple[Path, str]]:
        return checkouts(self.root)

    def touch(self, checkout: Path, path: Path) -> None:
        try:
            rel = path.relative_to(checkout).as_posix()
        except ValueError:
            return
        items = self.touched.setdefault(checkout, [])
        if rel not in items:
            items.append(rel)

    def mode(self, path: Path, text: str, heading: str) -> str:
        key = (path, heading)
        if key in self._created or _has_heading(text, heading):
            return APPEND_EXISTING
        self._created.add(key)
        return APPEND_NEW

    def append(self, path: Path, text: str, heading: str, lines: list[Record], source: str,
               *, sub: str = "", note: str = "") -> None:
        mode = self.mode(path, text, heading)
        label = f"{heading} > {sub}" if sub else heading
        detail = f"{label} ({mode}) <- {source}"
        if note:
            detail += f"; {note}"
        body = ([_gen(sub)] if sub else []) + lines
        self.scan(lines)
        self.act("append-section", path, detail, _text(body))

    # ---------------------------------------------------------- selection

    def run(self, milestones: list[str] | None) -> ConversionPlan:
        road_path = self.wdir / "ROADMAP.md"
        road_lines = self.cli.read_text(road_path).splitlines()
        rows: list[tuple[int, str, object]] = []
        for line in road_lines:
            parsed = self.cli.parse_milestones(line)
            if parsed:
                rows.append((len(rows) + 1, line, parsed[0]))
        by_id = {row[2].mid: row for row in rows}
        selected: list[str] = []
        if milestones is None:
            for _order, _line, mil in rows:
                if self._planning(mil.mid) == w2c_local.PLANNING_OPENSPEC:
                    selected.append(mil.mid)
        else:
            for raw in milestones:
                mid = self.cli.canonical_mid(raw)
                if mid in selected:
                    continue
                if mid not in by_id:
                    if not self._converted(mid):
                        self.block(f"{mid}: not in ROADMAP.md")
                    continue
                if self._planning(mid) != w2c_local.PLANNING_OPENSPEC:
                    self.block(f"{mid}: a classic milestone cannot be converted; {CLASSIC_HINT}")
                    continue
                selected.append(mid)
        for mid in selected:
            order, line, mil = by_id[mid]
            self._milestone(mil, order, line, road_path)
        for checkout in list(self.touched):
            self._project(checkout)
        selected = [mid for mid in selected if mid not in self.plan.skipped]
        remaining = [mid for mid in by_id if mid not in selected]
        if milestones is None and not remaining and (
            selected or any((self.wdir / item).exists() for item in LEDGER_FILES)
        ):
            self._retire_ledger()
        self._dirty()
        for mid in selected:
            task = self.cli.next_open_task(self.root, milestone=mid)
            self.plan.next_before[mid] = (task.mid, task.sid, task.tid) if task else None
        return self.plan

    def _planning(self, mid: str) -> str:
        plan_dir = self.cli.plan_dir_for(self.root, mid)
        road = plan_dir / f"{mid}-ROADMAP.md" if plan_dir else None
        if road is None or not road.is_file():
            return w2c_local.PLANNING_CLASSIC
        return osl.planning_mode(road.read_text(encoding="utf-8"))

    def _converted(self, mid: str) -> bool:
        plans = self.wdir / "plans"
        return plans.is_dir() and any(plans.glob(f"{mid}-*/CONVERTED"))

    # ---------------------------------------------------------- one milestone

    def _target(self, mid: str, remote: str, name: str, archive: str) -> Path | None:
        for path, branch in self.checkouts:
            if remote and branch == remote:
                return path
        main = self.checkouts[0][0]
        folder = osl.change_dir(main, name, archive)
        if folder is not None and (folder / ".openspec.yaml").is_file():
            return main
        self.block(f"{mid}: branch {remote or '(no Remote branch)'} is checked out nowhere, "
                   f"and the main checkout has no change folder {name}")
        return None

    def _milestone(self, mil, order: int, line: str, road_path: Path) -> None:
        cli = self.cli
        mid = mil.mid
        plan_dir = cli.plan_dir_for(self.root, mid)
        assert plan_dir is not None  # _planning found the roadmap
        road = plan_dir / f"{mid}-ROADMAP.md"
        text = road.read_text(encoding="utf-8")
        name = osl.change_name(text)
        archive = osl.archive_value(text)
        if not name:
            self.block(f"{mid}: {road.name} has no OpenSpec change")
            return
        gop = cli.parse_git_operation_fields(text)
        checkout = self._target(mid, gop.get("Remote branch", "").strip(), name, archive)
        if checkout is None:
            return
        folder = osl.change_dir(checkout, name, archive)
        if folder is None or not (folder / ".openspec.yaml").is_file():
            self.block(f"{mid}: change folder {name} not found in {checkout}")
            return
        if ledger.read_keys(folder / ".openspec.yaml").get(ledger.PREFIX + "legacy-id"):
            # Already converted (ruling 8): the change carries its legacy id.
            self.plan.skipped.append(mid)
            return
        self.touch(checkout, folder)
        done = mil.status == "DONE"
        declined = archive == "declined"
        archived = osl.is_archived(text)
        if done and not (declined or archived):
            self.block(f"{mid}: DONE but its OpenSpec archive is neither recorded nor declined")
        self._keys(mid, mil.status, order, text, folder, done=done, archived=archived, declined=declined)
        if not done:
            self._content(mid, plan_dir, text, folder, name)
        elif declined and not archived:
            self._reports(mid, plan_dir, folder, milestone_only=True)
        self.act("mark-converted", plan_dir / "CONVERTED", f"{mid} -> {name}", name)
        self.act("roadmap-remove", road_path, line.strip(), line)

    def _keys(self, mid: str, status: str, order: int, text: str, folder: Path, *,
              done: bool, archived: bool, declined: bool) -> None:
        meta = folder / ".openspec.yaml"
        keys: list[tuple[str, str]] = [("status", status), ("order", str(order))]
        cadence = str(self.config.get("git_delivery") or "")
        if cadence:
            keys.append(("cadence", cadence))
        elif not (done and archived):
            self.block(f"{mid}: no git_delivery in .w2c/config.toml for x-delivery-cadence")
        slices = [int(item.sid[1:]) for item in self.cli.parse_slices(text) if item.done]
        keys.append(("slices-done", "[" + ", ".join(str(n) for n in slices) + "]"))
        if declined:
            keys.append(("archive", "declined"))
        if str(self.config.get("amend_lock") or "") == mid:
            decision = str(self.config.get("amend_decision") or "")
            keys += [
                ("amend-lock", decision),
                ("amend-prior-status", str(self.config.get("amend_prior_status") or "")),
                ("amend-decision", decision),
            ]
        link = osl.linked_milestone(meta)
        if link is not None and link != mid:
            self.block(f"{mid}: {meta} links {LEGACY_LINK_KEY} {link}, not {mid}")
        for key, value in keys:
            self.act("write-key", meta, f"x-delivery-{key}: {value}", value)
        if link is None:
            self.act("write-key", meta, f"x-delivery-legacy-id: {mid}", mid)
        else:
            self.act("rename-key", meta, f"{LEGACY_LINK_KEY} -> x-delivery-legacy-id: {mid}", mid)

    # ---------------------------------------------------------- unfinished content

    def _content(self, mid: str, plan_dir: Path, text: str, folder: Path, name: str) -> None:
        proposal = folder / "proposal.md"
        design = folder / "design.md"
        tasks = folder / "tasks.md"
        proposal_text = self.cli.read_text(proposal)
        design_text = self.cli.read_text(design)
        self._check_files(mid, plan_dir)
        road = plan_dir / f"{mid}-ROADMAP.md"
        milestone = self._roadmap(mid, road, proposal, proposal_text)
        self._context(mid, plan_dir / f"{mid}-CONTEXT.md", proposal, proposal_text, milestone)
        slice_guardrails = self._slices(mid, plan_dir, tasks, milestone)
        self._design(mid, plan_dir, design, design_text, milestone, slice_guardrails, name)
        self._read_first(mid, tasks)
        self._reports(mid, plan_dir, folder)
        self._decisions(mid, design, design_text)

    def _check_files(self, mid: str, plan_dir: Path) -> None:
        fixed = {f"{mid}-{n}.md" for n in ("ROADMAP", "CONTEXT", "MANUAL-TEST", "AMENDMENTS", "VALIDATION", "SUMMARY")}
        plan_re = re.compile(rf"^{re.escape(mid)}-S\d+-PLAN\.md$")
        for path in sorted(plan_dir.iterdir()):
            item = path.name
            if path.is_file() and (
                item in fixed or item == "CONVERTED" or plan_re.match(item)
                or TASK_REPORT_RE.match(item) or SLICE_REPORT_RE.match(item)
            ):
                continue
            self.block(f"{mid}: {plan_dir.name}/{item} has no target")

    def _roadmap(self, mid: str, road: Path, proposal: Path, proposal_text: str) -> dict:
        lines = _records(road)
        preamble, sections = _split(lines, 2)
        found: dict = {"rows": [], "extras": [], "guardrails": [], "conventions": None,
                       "base_dirt": None, "sources": [], "guard_source": ""}
        vision: list[Record] | None = None
        for record in preamble:
            text = record[2]
            heading = _heading(record)
            if vision is None and heading and heading[0] == 1:
                continue
            if vision is None and text.startswith("**Vision:**"):
                rest = text[len("**Vision:**"):].strip()
                vision = [(record[0], record[1], rest)] if rest else []
                continue
            if vision is not None:
                vision.append(record)
            elif text.strip():
                self.block(f"{mid}: {road.name}:{record[1]} text before the first heading has no target")
        if vision is not None and _trim(vision):
            self.append(proposal, proposal_text, "## Vision", _trim(vision), f"{road.name} **Vision:**")
        for section in sections:
            title = section.title
            source = f"{road.name} ## {title}"
            if title in _PROPOSAL_FROM_ROADMAP:
                body = _trim(section.body)
                if body:
                    self.append(proposal, proposal_text, f"## {title}", body, source)
            elif title == "Slices":
                for record in _comment_free(section.body):
                    if record[2].strip() and not SLICE_BOX_RE.match(record[2]):
                        self.block(f"{mid}: {road.name}:{record[1]} text in ## Slices has no target")
            elif title in ("Delivery & Guardrails", "Git Operation Plan"):
                found["sources"].append(source)
                own, subs = _subsections(section.body)
                rows, other = _table(own)
                found["rows"] += rows
                found["extras"] += other
                for sub in subs:
                    if sub.title == "Guardrails":
                        found["guardrails"] += sub.body
                        found["guard_source"] = f"{road.name} ### Guardrails"
                    else:
                        found["extras"] += [sub.heading] + sub.body
                        if sub.title == "Base dirt paths":
                            found["base_dirt"] = sub.body
            elif title == "Commit and PR conventions":
                found["conventions"] = (found["conventions"] or []) + section.body
                found["conventions_source"] = source
            else:
                self.block(f"{mid}: {road.name}:{section.heading[1]} ## {title} has no target")
        return found

    def _context(self, mid: str, path: Path, proposal: Path, proposal_text: str, milestone: dict) -> None:
        milestone["context"] = []
        if not path.is_file():
            return
        preamble, sections = _split(_strip_frontmatter(_records(path)), 2)
        for record in preamble:
            heading = _heading(record)
            if heading and heading[0] == 1:
                continue
            if record[2].strip():
                self.block(f"{mid}: {path.name}:{record[1]} text before the first heading has no target")
        for section in sections:
            key = ("context", f"## {section.title}")
            target = SECTION_MAP.get(key)
            if target is None:
                self.block(f"{mid}: {path.name}:{section.heading[1]} ## {section.title} has no target")
                continue
            body = _trim(section.body)
            if not body:
                continue
            source = f"{path.name} ## {section.title}"
            if target[0] == "proposal.md":
                self.append(proposal, proposal_text, target[1], body, source)
            else:
                milestone["context"].append((target[1], SUBSECTIONS[key], body, source))

    # ---------------------------------------------------------- slices

    def _slices(self, mid: str, plan_dir: Path, tasks: Path, milestone: dict) -> list[Record]:
        plan_re = re.compile(rf"^{re.escape(mid)}-S(\d+)-PLAN\.md$")
        tasks_text = self.cli.read_text(tasks)
        groups = osl.group_numbers(tasks) if tasks.is_file() else []
        existing = checks.slice_fields(tasks_text)
        merged = {key: value for key, value, _r in milestone["rows"]}
        guard_lines = {r[2].strip() for r in milestone["guardrails"] if r[2].strip()}
        extras_text = {r[2].strip() for r in milestone["extras"] if r[2].strip()}
        conv = _norm(milestone["conventions"] or [], _CONVENTIONS_INSTRUCTIONS)
        base_dirt = _norm(milestone["base_dirt"] or [])
        carried: list[Record] = []
        seen: set[str] = set()
        done_groups: set[int] = set()
        for path in sorted(plan_dir.iterdir()):
            match = plan_re.match(path.name)
            if not match or not path.is_file():
                continue
            number = int(match.group(1))
            sid = f"S{number:02d}"
            where = path.name
            fields, guards, prose = self._slice_plan(mid, path, merged, extras_text, conv, base_dirt)
            for record in guards:
                text = record[2].strip()
                if not text or text in guard_lines:
                    continue
                if text in SLICE_TEMPLATE_GUARDRAILS:
                    if text not in seen:
                        seen.add(text)
                        carried.append(record)
                    continue
                self.block(f"{mid}: {where}:{record[1]} {sid} guardrail is not in the milestone's Guardrails: {text}")
            if not tasks.is_file():
                self.block(f"{mid}: {sid} has a slice plan but {tasks} is missing")
                continue
            if number not in groups:
                self.block(f"{mid}: {sid} has a slice plan but tasks.md has no ## {number}. group")
                continue
            done_groups.add(number)
            have = existing.get(number, {})
            lines: list[Record] = []
            empty: list[str] = []
            appended: list[str] = []
            for name in layout.SLICE_FIELDS:
                value = fields.get(name)
                if value is None or not _trim(value):
                    if name in have:
                        continue
                    empty.append(name)
                    lines.append(_gen(f"**{name}:** {NOT_SET}"))
                    continue
                if name in have:
                    appended.append(name)
                body = _trim(value)
                first = body[0]
                if name in ("Goal", "Demo") and first[1] is not None and first[2].startswith(f"**{name}:**"):
                    lines.append(first)
                    lines += body[1:]
                else:
                    lines.append(_gen(f"**{name}:**"))
                    lines += body
            self.scan(lines)
            detail = f"group {number} ({sid}) <- {where}"
            if appended:
                detail += f"; {APPEND_EXISTING}: {', '.join(appended)}"
            if prose:
                detail += f"; text before the first heading carried into Goal: {prose} lines"
            if empty:
                detail += f"; not set: {', '.join(empty)}"
            self.act("write-group-fields", tasks, detail, _text(lines))
        for number in groups:
            if number in done_groups:
                continue
            have = existing.get(number, {})
            missing = [name for name in layout.SLICE_FIELDS if name not in have]
            if not missing:
                continue
            lines = [_gen(f"**{name}:** {NOT_SET}") for name in missing]
            self.act("write-group-fields", tasks,
                     f"group {number} (S{number:02d}) <- no slice plan; not set: {', '.join(missing)}", _text(lines))
        return carried

    def _slice_plan(self, mid: str, path: Path, merged: dict[str, str], extras_text: set[str],
                    conv: list[str], base_dirt: list[str]) -> tuple[dict[str, list[Record]], list[Record], int]:
        where = path.name
        lines = _strip_frontmatter(_records(path))
        preamble, sections = _split(lines, 2)
        fields: dict[str, list[Record]] = {}
        guards: list[Record] = []
        prose: list[Record] = []
        conventions: list[Record] | None = None
        conventions_at: int | None = None
        current: str | None = None
        for record in preamble:
            text = record[2]
            heading = _heading(record)
            if heading and heading[0] == 1:
                current = None
                continue
            bold = BOLD_FIELD_RE.match(text)
            if bold and bold.group(1).strip() in ("Goal", "Demo"):
                current = bold.group(1).strip()
                value = bold.group(2).strip()
                if current not in fields:
                    fields[current] = [record] if value else []
                elif value:
                    # A repeated field: its value joins the first, in source order.
                    fields[current].append((record[0], record[1], value))
                continue
            if not text.strip():
                current = None
                continue
            if current is not None:
                fields[current].append(record)
            elif text.strip() not in SLICE_TEMPLATE_PROSE:
                prose.append(record)
        if prose:
            fields["Goal"] = fields.get("Goal", []) + prose
        for section in sections:
            title = section.title
            if title in _SLICE_SECTION_FIELDS:
                fields[title] = fields.get(title, []) + section.body
            elif title == "Git Operation Plan":
                own, subs = _subsections(section.body)
                rows, other = _table(own)
                for key, value, record in rows:
                    if key in _SLICE_ONLY_PLAN_FIELDS:
                        continue
                    if value != merged.get(key, "").strip():
                        self.block(f"{mid}: {where}:{record[1]} Git Operation Plan {key} {value!r} "
                                   f"differs from the milestone's {merged.get(key, '')!r}")
                for record in other:
                    text = record[2].strip()
                    if text and text not in SLICE_TEMPLATE_PROSE and text not in extras_text:
                        self.block(f"{mid}: {where}:{record[1]} Git Operation Plan text is not in the milestone's: {text}")
                for sub in subs:
                    if sub.title == "Guardrails":
                        guards += sub.body
                    elif sub.title == "Base dirt paths":
                        if _norm(sub.body) != base_dirt:
                            self.block(f"{mid}: {where}:{sub.heading[1]} ### Base dirt paths differs from the milestone's")
                    else:
                        self.block(f"{mid}: {where}:{sub.heading[1]} ### {sub.title} has no target")
            elif title == "Commit and PR conventions":
                conventions = (conventions or []) + section.body
                conventions_at = conventions_at or section.heading[1]
            else:
                self.block(f"{mid}: {where}:{section.heading[1]} ## {title} has no target")
        if conventions is not None and _norm(conventions, _CONVENTIONS_INSTRUCTIONS) != conv:
            self.block(f"{mid}: {where}:{conventions_at} Commit and PR conventions differ from the milestone's")
        return fields, guards, len(prose)

    # ---------------------------------------------------------- design

    def _design(self, mid: str, plan_dir: Path, design: Path, design_text: str, milestone: dict,
                slice_guardrails: list[Record], name: str) -> None:
        road_name = f"{mid}-ROADMAP.md"
        self._delivery_plan(mid, design, design_text, milestone)
        profile = self.wdir / "DELIVERY-PROFILE.md"
        if profile.is_file():
            body = _trim(self._demote(_records(profile), top=4))
            if body:
                self.append(design, design_text, "## Delivery Plan", body, profile.name,
                            sub=SUBSECTIONS[("profile", "DELIVERY-PROFILE.md")],
                            note="copied whole; headings demoted under ####")
        guard_body, dropped = self._guardrail_body(milestone["guardrails"])
        guard_body = _trim(guard_body)
        if slice_guardrails:
            guard_body = guard_body + slice_guardrails
        if guard_body:
            note = ""
            if dropped:
                note = "dropped: " + "; ".join(f"{label} ({layout.LEGACY_DROPPED_GUARDRAILS[label]})" for label in dropped)
            if slice_guardrails:
                note = (note + "; " if note else "") + f"slice-plan lines carried: {len(slice_guardrails)}"
            self.append(design, design_text, "## Guardrails", guard_body,
                        milestone["guard_source"] or f"{road_name} ### Guardrails", note=note)
        for target, sub, body, source in milestone["context"]:
            if target == "## Guardrails":
                self.append(design, design_text, target, body, source, sub=sub)
        conventions = _trim(milestone["conventions"] or [])
        if conventions:
            self.append(design, design_text, "## Commit and PR Conventions", conventions,
                        milestone.get("conventions_source", f"{road_name} ## Commit and PR conventions"))
        self._repair_conventions(design, design_text, conventions)
        for target, sub, body, source in milestone["context"]:
            if target == "## Decisions":
                self.append(design, design_text, target, body, source, sub=sub)
        manual = plan_dir / f"{mid}-MANUAL-TEST.md"
        if manual.is_file():
            body = _trim(self._demote(_records(manual)))
            if body:
                self.append(design, design_text, "## Manual Test Guide", body, manual.name,
                            note="headings demoted under ###")
        amendments = plan_dir / f"{mid}-AMENDMENTS.md"
        if amendments.is_file():
            body = _trim(self._amendment_body(_records(amendments), mid, name))
            if body:
                self.append(design, design_text, "## Amendments", body, amendments.name,
                            note=f"record headings moved to ###, targets {mid}/ renamed {name}/")
        for heading in layout.DESIGN_HEADINGS:
            if (design, heading) not in self._created and not _has_heading(design_text, heading):
                self._created.add((design, heading))
                self.act("append-section", design, f"{heading} ({APPEND_NEW}) <- no source section; empty heading")

    def _delivery_plan(self, mid: str, design: Path, design_text: str, milestone: dict) -> None:
        values: dict[str, tuple[str, Record]] = {}
        dropped: list[str] = []
        for key, value, record in milestone["rows"]:
            if key in values:
                prior = values[key][0]
                if prior and value and prior != value:
                    self.block(f"{mid}: conflicting Delivery Plan values for {key}: {prior!r} and {value!r}")
                if prior or not value:
                    continue
            values[key] = (value, record)
        local = values.get("Local branch", ("", None))[0]
        cadence = str(self.config.get("git_delivery") or "")
        for key, (value, record) in values.items():
            if key in layout.DELIVERY_PLAN_FIELDS:
                continue
            if key not in layout.LEGACY_DROPPED_FIELDS:
                self.block(f"{mid}: {record[0].name}:{record[1]} row {key} has no target")
                continue
            if key == "Commit cadence" and value and not value.startswith("(") and value != cadence:
                self.block(f"{mid}: conflicting Delivery Plan values for Commit cadence: "
                           f"{value!r} and git_delivery {cadence!r}")
            if key == "Branch name" and value and value != local:
                self.block(f"{mid}: conflicting Delivery Plan values for Branch name {value!r} "
                           f"and Local branch {local!r}")
            dropped.append(f"{key}={value or '(empty)'} ({layout.LEGACY_DROPPED_FIELDS[key]})")
        profile = self.cli.parse_table_under_heading(
            self.cli.read_text(self.wdir / "DELIVERY-PROFILE.md"), "Active profile"
        )
        filled: list[str] = []
        rows: list[Record] = [_gen("| Field | Value |"), _gen("| --- | --- |")]
        for key in layout.DELIVERY_PLAN_FIELDS:
            value, record = values.get(key, ("", None))
            if not value or value.startswith("(from"):
                source = next((s for k, sources in _PROFILE_FIELDS if k == key for s in sources if profile.get(s)), None)
                if source:
                    filled.append(key)
                    rows.append(_gen(f"| {key} | {profile[source].strip().strip('`')} |"))
                    continue
            rows.append(record if record is not None else _gen(f"| {key} | |"))
        extras = _trim(milestone["extras"])
        body = rows + ([_gen("")] + extras if extras else [])
        note = "merged rows"
        if dropped:
            note += "; dropped: " + "; ".join(dropped)
        if filled:
            note += "; filled from DELIVERY-PROFILE.md: " + ", ".join(filled)
        self.append(design, design_text, "## Delivery Plan", body,
                    " + ".join(milestone["sources"]) or f"{mid}-ROADMAP.md", note=note)

    @staticmethod
    def _guardrail_body(lines: list[Record]) -> tuple[list[Record], list[str]]:
        out: list[Record] = []
        dropped: list[str] = []
        skipping = False
        for record in lines:
            text = record[2]
            if text.startswith("- "):
                label = BULLET_LABEL_RE.match(text)
                skipping = bool(label and label.group(1) in layout.LEGACY_DROPPED_GUARDRAILS)
                if skipping:
                    dropped.append(label.group(1))
                    continue
            elif skipping and text.strip() and text[:1].isspace():
                continue
            else:
                skipping = False
            out.append(record)
        return out, dropped

    def _repair_conventions(self, design: Path, design_text: str, lines: list[Record]) -> None:
        """Add the required neutral lines the converted Conventions would still lack."""
        rewritten: list[str] = []
        for record in lines:
            new = KNOWN_REWRITES.get(record[2])
            if isinstance(new, Drop):
                continue
            rewritten.append(new if new is not None else record[2])
        existing = self.cli.section_under_heading(design_text, checks.CONVENTIONS_HEADING) or ""
        body = existing.rstrip("\n") + "\n" + "".join(line + "\n" for line in rewritten)
        problems = checks.validate_conventions(f"## {checks.CONVENTIONS_HEADING}\n{body}")
        if any(problem.startswith("missing or empty") for problem in problems):
            problems = [key for key, _lines in CONVENTIONS_REPAIRS]
        for key, add in CONVENTIONS_REPAIRS:
            found = next((problem for problem in problems if key in problem), None)
            if found is None:
                continue
            self.append(design, design_text, "## Commit and PR Conventions", [_gen(line) for line in add],
                        "templates/cloud/design-delivery.md",
                        note=f"required line added; legacy text kept ({found})")

    def _read_first(self, mid: str, tasks: Path) -> None:
        if not tasks.is_file():
            return
        head = re.split(r"(?m)^## ", self.cli.read_text(tasks), maxsplit=1)[0]
        if layout.READ_FIRST_MARKER in head:
            return
        try:
            block = self.cli.load_checkout_template("cloud/tasks-read-first.md")
        except self.cli.W2CError as exc:
            self.block(f"{mid}: {exc}")
            return
        self.act("write-read-first", tasks, "insert the read-first block at the top of tasks.md", block)

    @staticmethod
    def _demote(lines: list[Record], top: int = 3) -> list[Record]:
        levels = [len(m.group(1)) for r in lines if (m := HEADING_RE.match(r[2]))]
        if not levels:
            return lines
        shift = top - min(levels)
        out: list[Record] = []
        for path, number, text in lines:
            match = HEADING_RE.match(text)
            if match and shift > 0:
                level = min(6, len(match.group(1)) + shift)
                text = "#" * level + " " + match.group(2)
            out.append((path, number, text))
        return out

    @staticmethod
    def _amendment_body(lines: list[Record], mid: str, name: str) -> list[Record]:
        header = {line.strip() for line in _cli_amend_header().splitlines() if line.strip()}
        out: list[Record] = []
        for path, number, text in lines:
            if text.strip() in header and not out:
                continue
            match = AMEND_HEAD_RE.match(text)
            if match:
                target = match.group(3)
                if target == mid or target.startswith(mid + "/"):
                    target = name + target[len(mid):]
                text = f"### {match.group(1)} {match.group(2)} {target}"
            if not out and not text.strip():
                continue
            out.append((path, number, text))
        return out

    # ---------------------------------------------------------- reports, decisions

    def _reports(self, mid: str, plan_dir: Path, folder: Path, *, milestone_only: bool = False) -> None:
        dest = folder / layout.REPORT_DIR
        for path in sorted(plan_dir.iterdir()):
            item = path.name
            if not milestone_only and (TASK_REPORT_RE.match(item) or SLICE_REPORT_RE.match(item)):
                target = item
            elif item == f"{mid}-VALIDATION.md":
                target = layout.REPORT_FILES["validation"]
            elif item == f"{mid}-SUMMARY.md":
                target = layout.REPORT_FILES["summary"]
            else:
                continue
            self.scan(_records(path))
            self.act("copy-report", dest / target, f"<- {path}")

    def _decisions(self, mid: str, design: Path, design_text: str) -> None:
        source = self.wdir / "DECISIONS.md"
        rows = [r for r in _records(source) if DECISION_LINE_RE.match(r[2])
                and len(_cells(r[2])) > 2 and _cells(r[2])[2] == mid]
        if not rows:
            return
        self.copied_scopes.add(mid)
        ids = [DECISION_LINE_RE.match(r[2]).group(1) for r in rows]
        mode = self.mode(design, design_text, "## Decisions")
        span = commands._decisions_span(design_text)
        header = bool(span and re.search(r"^\| # \| When \|", design_text[span[0]:span[1]], re.M))
        self.scan(rows)
        detail = (f"## Decisions ({mode}) <- DECISIONS.md rows {', '.join(ids)}; "
                  f"table header {'present' if header else 'missing'}")
        self.act("copy-decisions", design, detail, _text(rows))

    # ---------------------------------------------------------- project level

    def _project(self, checkout: Path) -> None:
        self._knowledge(checkout)
        attrs = checkout / ".gitattributes"
        if commands.ATTRIBUTES_LINE not in self.cli.read_text(attrs).splitlines():
            self.touch(checkout, attrs)
            self.act("edit-gitattributes", attrs, f"add {commands.ATTRIBUTES_LINE}", commands.ATTRIBUTES_LINE + "\n")
        config = checkout / "openspec" / "config.yaml"
        if not config.is_file() and (checkout / "openspec" / "config.yml").is_file():
            config = checkout / "openspec" / "config.yml"
        text = self.cli.read_text(config)
        if all(marker in text for marker in CONFIG_MARKERS):
            return
        present = [key for key in CONFIG_KEYS if re.search(rf"^{key}[ \t]*:", text, re.M)]
        if not config.is_file():
            detail = "create with the cloud rules"
        elif present:
            detail = (f"merge into existing top-level {', '.join(present)} "
                      "(YAML forbids duplicate keys); append the snippet's other keys")
        else:
            detail = "append the cloud rules (no top-level context, rules or operations key yet)"
        self.touch(checkout, config)
        self.act("edit-config", config, detail, layout.CONFIG_RULES_SNIPPET)

    def _knowledge(self, checkout: Path) -> None:
        """Every line of the latest CONTEXT that knowledge.md lacks, compared by line text."""
        latest = self.cli.latest_context(self.root)
        if latest is None:
            return
        source = latest[2]
        target = checkout / commands.KNOWLEDGE_PATH
        have_text = self.cli.read_text(target)
        have = {line.strip() for line in have_text.splitlines()}
        preamble, sections = _split(_strip_frontmatter(_records(source)), 2)
        lines = [r for r in _trim(preamble) if r[2].strip() and r[2].strip() not in have]
        counts = [f"preamble: {len(lines)}"] if lines else []
        for section in sections:
            body = _trim(section.body)
            if not _has_heading(have_text, f"## {section.title}"):
                missing, label = body, " (new section)"
            else:
                missing = [r for r in body if r[2].strip() and r[2].strip() not in have]
                label = ""
            if missing or label:
                lines += [_gen(f"## {section.title}")] + missing
                counts.append(f"{section.title}: {len(missing)}{label}")
        if not lines and target.is_file():
            return
        self.scan(lines)
        mode = "create" if not target.is_file() else "add missing lines"
        self.touch(checkout, target)
        self.act("sync-knowledge", target, f"{mode} from {source.name} ({', '.join(counts) or 'nothing'})",
                 _text(lines))

    def _retire_ledger(self) -> None:
        main = self.checkouts[0][0]
        rows = [r for r in _records(self.wdir / "DECISIONS.md")
                if r[2].lstrip().startswith("|") and not SEPARATOR_RE.match(r[2].strip())
                and not DECISION_HEADER_RE.match(r[2])]
        keep = [r for r in rows if not (DECISION_LINE_RE.match(r[2]) and len(_cells(r[2])) > 2
                                        and _cells(r[2])[2] in self.copied_scopes)]
        target = main / DECISIONS_FILE
        content = (
            "# Decisions\n\nFrozen copy of the decisions recorded before cloud mode. "
            "Rows keep their original ids.\n\n"
            + commands.DECISION_HEADER
            + _text(keep)
        )
        self.scan(keep)
        self.touch(main, target)
        ids = ", ".join(_cells(r[2])[0] if _cells(r[2]) else "?" for r in keep) or "none"
        self.act("write-decisions-file", target, f"remaining DECISIONS.md rows: {ids}", content)
        for item in LEDGER_FILES:
            path = self.wdir / item
            if path.exists():
                self.act("delete-ledger-file", path, f"no 2.2 milestone remains; delete {item}")

    def _dirty(self) -> None:
        for checkout, rels in self.touched.items():
            if not rels or not ledger_store.is_git(checkout):
                continue
            proc = ledger_store.git(
                checkout, "--no-optional-locks", "status", "--porcelain", "--untracked-files=all", "--", *rels,
                check=False,
            )
            lines = [line for line in proc.stdout.splitlines() if line.strip()]
            if lines:
                self.block(f"uncommitted changes in {checkout}: {'; '.join(lines)}")


def _cli_amend_header() -> str:
    from w2c import amend as legacy_amend

    return legacy_amend.HEADER


def plan_conversion(root: Path, milestones: list[str] | None) -> ConversionPlan:
    """Every action and blocker for converting `milestones` (None: --all). Reads only."""
    return _Planner(Path(root)).run(milestones)


# ====================================================================== apply

RUN_PREFIX = "cloud-migrate-"
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
RESTORE_FIRST = "run w2c cloud migrate --restore first"
# Applied only after verification passes.
DEFERRED_KINDS = frozenset({"roadmap-remove", "delete-ledger-file"})
APPEND_DETAIL_RE = re.compile(r"^(## .+?)(?: > (### .+?))? \((?:new|append-to-existing)\) <- ")
GROUP_DETAIL_RE = re.compile(r"^group (\d+) ")
KEY_DETAIL_RE = re.compile(r"^(x-delivery-[a-z-]+): ")
DECISION_HEAD_LINE_RE = re.compile(r"^\| # \| When \|")
TOP_KEY_RE = re.compile(r"^([A-Za-z_][\w.-]*)[ \t]*:(.*)$")
BLOCK_SCALAR_RE = re.compile(r"^[|>][+-]?[1-9]?$")


def _error(message: str) -> Exception:
    return _cli().W2CError(message)


def _rewrite_line(line: str, yes_rewrites: bool) -> str | None:
    """The line after approved rewrites; None when an approved Drop removes it."""
    new = KNOWN_REWRITES.get(line)
    if new is None or not yes_rewrites:
        return line
    return None if isinstance(new, Drop) else new


def _rewrite(text: str, yes_rewrites: bool) -> str:
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        new = _rewrite_line(body, yes_rewrites)
        if new is not None:
            out.append(new + line[len(body):])
    return "".join(out)


def _shown(new: str | Drop) -> str:
    return f"(drop: {new.reason})" if isinstance(new, Drop) else new


def _rel(base: Path, path: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return str(path)


def _lines(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return lines


def _block(content: str) -> list[str]:
    return _lines(content) if content.strip() else []


def _level2(lines: list[str]) -> list[tuple[str, int, int]]:
    """(heading, heading index, end index) of each `## ` section; fenced code is body."""
    heads: list[tuple[str, int]] = []
    fenced = False
    for index, line in enumerate(lines):
        text = line.rstrip("\r\n")
        if FENCE_RE.match(text):
            fenced = not fenced
            continue
        match = None if fenced else HEADING_RE.match(text)
        if match and len(match.group(1)) == 2:
            heads.append((f"## {match.group(2)}", index))
    out = []
    for number, (heading, start) in enumerate(heads):
        end = heads[number + 1][1] if number + 1 < len(heads) else len(lines)
        out.append((heading, start, end))
    return out


PREAMBLE = ""


def section_bodies(text: str) -> dict[str, list[str]]:
    """Body lines of each `## ` heading (first occurrence), subsections included.
    The text before the first `## ` is under the key "" (PREAMBLE)."""
    lines = text.splitlines()
    sections = _level2(lines)
    bodies: dict[str, list[str]] = {PREAMBLE: lines[: sections[0][1] if sections else len(lines)]}
    for heading, start, end in sections:
        bodies.setdefault(heading, lines[start + 1 : end])
    return bodies


def _collapse(lines: list[str], exclude: frozenset[str] | set[str] = frozenset()) -> str:
    kept = [line for line in lines if line.strip() not in exclude]
    return " ".join(" ".join(kept).split())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def section_fingerprints(text: str, exclude: frozenset[str] | set[str] = frozenset()) -> dict[str, str]:
    """Heading -> sha256 of the whitespace-collapsed body. Lines whose stripped text
    is in `exclude` are left out on both sides of a comparison."""
    return {heading: _sha(_collapse(body, exclude)) for heading, body in section_bodies(text).items()}


def _trim_end(lines: list[str], start: int, end: int) -> int:
    while end > start and not lines[end - 1].strip():
        end -= 1
    return end


def _append_to_section(text: str, heading: str, content: str, order: tuple[str, ...] = ()) -> str:
    """Append `content` at the end of `heading`'s section, creating the heading when
    missing. A new heading listed in `order` goes before the first later one present."""
    lines = _lines(text)
    block = _block(content)
    sections = _level2(lines)
    found = next((s for s in sections if s[0] == heading), None)
    if found is not None:
        _h, start, end = found
        stop = _trim_end(lines, start + 1, end)
        tail = lines[stop:end] or (["\n"] if end < len(lines) else [])
        insert = (["\n"] + block) if block else []
        return "".join(lines[:stop] + insert + tail + lines[end:])
    new = [heading + "\n", "\n"] + block
    if heading in order:
        later = order[order.index(heading) + 1 :]
        at = next((start for name, start, _e in sections if name in later), None)
        if at is not None:
            return "".join(lines[:at] + new + (["\n"] if block else []) + lines[at:])
    if lines and lines[-1].strip():
        lines.append("\n")
    return "".join(lines + new)


def _insert_group_fields(text: str, number: int, content: str) -> str:
    lines = _lines(text)
    for heading, start, end in _level2(lines):
        match = checks.GROUP_LINE_RE.match(heading)
        if not match or int(match.group(1)) != number:
            continue
        task = next((i for i in range(start + 1, end) if osl.TASK_RE.match(lines[i].rstrip("\n"))), None)
        if task is not None:
            before = lines[:task]
            if before and before[-1].strip():
                before.append("\n")
            return "".join(before + _block(content) + ["\n"] + lines[task:])
        stop = _trim_end(lines, start + 1, end)
        tail = lines[stop:end] or (["\n"] if end < len(lines) else [])
        return "".join(lines[:stop] + ["\n"] + _block(content) + tail + lines[end:])
    raise _error(f"tasks.md has no ## {number}. group")


def _insert_read_first(text: str, block: str) -> str:
    lines = _lines(text)
    at = 0
    if lines and lines[0].startswith("# "):
        at = 1
        while at < len(lines) and not lines[at].strip():
            at += 1
        head = lines[:1] + ["\n"]
    else:
        head = []
    return "".join(head + _block(block) + ["\n"] + lines[at:])


def _insert_decisions(text: str, rows: str) -> str:
    lines = _lines(text)
    found = next((s for s in _level2(lines) if s[0] == "## Decisions"), None)
    if found is not None:
        _h, start, end = found
        head = next((i for i in range(start + 1, end) if DECISION_HEAD_LINE_RE.match(lines[i])), None)
        if head is not None:
            stop = head + 1
            while stop < end and lines[stop].startswith("|"):
                stop += 1
            return "".join(lines[:stop] + _block(rows) + lines[stop:])
    return _append_to_section(text, "## Decisions", commands.DECISION_HEADER + rows, layout.DESIGN_HEADINGS)


def _sync_knowledge(text: str, content: str) -> str:
    """Add the planned CONTEXT lines: preamble before the first section, table rows
    after a section's last table row, other lines at the section end."""
    preamble, sections = _split([_gen(line) for line in content.splitlines()], 2)
    if not text.strip():
        out = [r[2] + "\n" for r in preamble]
        for section in sections:
            if out and out[-1].strip():
                out.append("\n")
            out += [f"## {section.title}\n", "\n"] + [r[2] + "\n" for r in _trim(section.body)]
        return "".join(out)
    lines = _lines(text)
    adds = [r[2] + "\n" for r in preamble if r[2].strip()]
    if adds:
        heads = _level2(lines)
        at = _trim_end(lines, 0, heads[0][1] if heads else len(lines))
        lines = lines[:at] + ["\n"] + adds + lines[at:]
    for section in sections:
        heading = f"## {section.title}"
        body = [r[2] + "\n" for r in section.body if r[2].strip()]
        found = next((s for s in _level2(lines) if s[0] == heading), None)
        if found is None:
            if lines and lines[-1].strip():
                lines.append("\n")
            lines += [heading + "\n", "\n"] + [r[2] + "\n" for r in _trim(section.body)]
            continue
        _h, start, end = found
        rows = [line for line in body if line.lstrip().startswith("|")]
        other = [line for line in body if not line.lstrip().startswith("|")]
        last_row = max((i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")), default=None)
        if rows and last_row is not None:
            lines[last_row + 1 : last_row + 1] = rows
            end += len(rows)
            rows = []
        rest = rows + other
        if rest:
            stop = _trim_end(lines, start + 1, end)
            lines[stop:stop] = ["\n"] + rest
    return "".join(lines)


# ---------------------------------------------------------------- config.yaml


class _Unsafe(Exception):
    pass


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _content(line: str) -> bool:
    text = line.strip()
    return bool(text) and not text.startswith("#")


def _value(line: str) -> str:
    rest = line.split(":", 1)[1] if ":" in line else ""
    return re.sub(r"(^|\s)#.*$", "", rest).strip()


def _snippet_blocks(snippet: str) -> list[tuple[str, str]]:
    """(top-level key, block text) in snippet order."""
    blocks: list[tuple[str, str]] = []
    for line in _lines(snippet):
        match = TOP_KEY_RE.match(line.rstrip("\n")) if _indent(line) == 0 and _content(line) else None
        if match:
            blocks.append((match.group(1), line))
        elif blocks:
            blocks[-1] = (blocks[-1][0], blocks[-1][1] + line)
    return blocks


def _snippet_parts(snippet: str) -> list[tuple[tuple[str, ...], str, list[str]]]:
    """(key path, 'scalar' | 'list', lines) for each leaf of the config snippet."""
    parts: list[tuple[tuple[str, ...], str, list[str]]] = []
    stack: list[tuple[int, str]] = []
    scalar_at: int | None = None
    for line in snippet.splitlines():
        if not line.strip():
            continue
        ind = _indent(line)
        text = line.strip()
        if scalar_at is not None and ind > scalar_at:
            parts[-1][2].append(text)
            continue
        scalar_at = None
        while stack and stack[-1][0] >= ind:
            stack.pop()
        if text.startswith("- "):
            path = tuple(key for _i, key in stack)
            if parts and parts[-1][0] == path and parts[-1][1] == "list":
                parts[-1][2].append(text)
            else:
                parts.append((path, "list", [text]))
            continue
        key, value = text.split(":", 1)
        stack.append((ind, key.strip()))
        if BLOCK_SCALAR_RE.match(value.strip()):
            parts.append((tuple(k for _i, k in stack), "scalar", []))
            scalar_at = ind
    return parts


def _find_key(lines: list[str], start: int, end: int, indent: int, key: str) -> list[int]:
    pattern = re.compile(rf"^{re.escape(key)}[ \t]*:")
    return [i for i in range(start, end)
            if _content(lines[i]) and _indent(lines[i]) == indent and pattern.match(lines[i][indent:])]


def _block_end(lines: list[str], at: int, indent: int) -> int:
    j = at + 1
    while j < len(lines):
        line = lines[j]
        if _content(line) and not (_indent(line) > indent or (
                _indent(line) == indent and line[indent:].startswith("- ") and indent > 0)):
            break
        j += 1
    while j > at + 1 and not lines[j - 1].strip():
        j -= 1
    return j


def _leaf_lines(lines: list[str], path: tuple[str, ...]) -> list[str] | None:
    """The stripped lines inside the block of the key at `path`, or None when absent."""
    start, end, indent = 0, len(lines), 0
    for key in path:
        found = _find_key(lines, start, end, indent, key)
        if not found:
            return None
        at = found[0]
        block = _block_end(lines, at, indent)
        body = [i for i in range(at + 1, block) if _content(lines[i])]
        start, end, indent = at + 1, block, (_indent(lines[body[0]]) if body else indent + 2)
    return [lines[i].strip() for i in range(start, end) if lines[i].strip()]


def _merge_leaf(lines: list[str], path: tuple[str, ...], kind: str, items: list[str]) -> None:
    start, end, indent = 0, len(lines), 0
    for depth, key in enumerate(path):
        found = _find_key(lines, start, end, indent, key)
        if len(found) > 1:
            raise _Unsafe(f"duplicate key {key}")
        if not found:
            missing = list(items)
            at = _trim_end(lines, start, end) if depth else len(lines)
            new: list[str] = []
            if not depth and lines and lines[-1].strip():
                new.append("\n")
            ind = indent
            for number, name in enumerate(path[depth:]):
                last = depth + number == len(path) - 1
                new.append(" " * ind + f"{name}:{' |' if last and kind == 'scalar' else ''}\n")
                ind += 2
            new += [" " * ind + item + "\n" for item in missing]
            lines[at:at] = new
            return
        at = found[0]
        value = _value(lines[at])
        last = depth == len(path) - 1
        block = _block_end(lines, at, indent)
        body = [i for i in range(at + 1, block) if _content(lines[i])]
        if last and kind == "scalar":
            if not BLOCK_SCALAR_RE.match(value):
                raise _Unsafe(f"{key} is not a block scalar")
            child = _indent(lines[body[0]]) if body else indent + 2
        else:
            if value:
                raise _Unsafe(f"{key} is not in block style")
            child = _indent(lines[body[0]]) if body else indent + 2
            if last and body and not lines[body[0]][child:].startswith("- "):
                raise _Unsafe(f"{key} is not a list")
        if last:
            # "Already present" means a line of this key's own block, not anywhere in the file.
            present = {lines[i].strip() for i in range(at + 1, block)}
            missing = [item for item in items if item.strip() not in present]
            if missing:
                lines[block:block] = [" " * child + item + "\n" for item in missing]
            return
        start, end, indent = at + 1, block, child


def merge_config(text: str, snippet: str = layout.CONFIG_RULES_SNIPPET) -> str:
    """Merge the cloud rules into config.yaml text, line by line, into existing
    block-style keys. Raises _Unsafe for forms that cannot be merged safely."""
    if "\t" in text:
        raise _Unsafe("tabs")
    lines = _lines(text)
    unquoted = [re.sub(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'", "", line) for line in lines]
    scalar_until = -1
    for index, line in enumerate(unquoted):
        if index <= scalar_until:
            continue
        stripped = line.strip()
        if stripped in ("---", "...") and index:
            raise _Unsafe("more than one YAML document")
        if re.search(r"(^|[\s:\[{,-])[&*][A-Za-z0-9_-]", re.sub(r"(^|\s)#.*$", "", line)):
            raise _Unsafe("anchors or aliases")
        if _content(line) and ":" in line and BLOCK_SCALAR_RE.match(_value(line)):
            ind = _indent(line)
            scalar_until = _block_end(lines, index, ind) - 1
    for key in CONFIG_KEYS:
        found = _find_key(lines, 0, len(lines), 0, key)
        if len(found) > 1:
            raise _Unsafe(f"duplicate top-level key {key}")
        if found:
            at = found[0]
            value = _value(lines[at])
            if value[:1] in ("{", "["):
                raise _Unsafe(f"{key} uses flow style")
            for i in range(at + 1, _block_end(lines, at, 0)):
                if _content(lines[i]) and ":" in lines[i] and _value(lines[i])[:1] in ("{", "["):
                    raise _Unsafe(f"{key} holds flow style")
    appended: list[str] = []
    for key, block in _snippet_blocks(snippet):
        if not _find_key(lines, 0, len(lines), 0, key):
            appended.append(block)
            continue
        for path, kind, items in _snippet_parts(block):
            _merge_leaf(lines, path, kind, items)
    if appended:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines += _lines("".join(appended))
    return "".join(lines)


def _config_change(path: Path) -> tuple[str | None, str]:
    """(new text, '') or (None, reason) for the planned config edit."""
    text = _cli().read_text(path)
    if not path.is_file():
        return layout.CONFIG_RULES_SNIPPET, ""
    try:
        return merge_config(text), ""
    except _Unsafe as exc:
        return None, str(exc)


def _config_lines(root: Path, action: Action, *, approved: bool, dry_run: bool = False) -> list[str]:
    cli = _cli()
    shown = _rel(root, action.path)
    new, reason = _config_change(action.path)
    if new is None:
        return [f"MANUAL_CONFIG {shown}: cannot merge safely ({reason}); add these lines by hand:"] + [
            "  " + line for line in layout.CONFIG_RULES_SNIPPET.splitlines()]
    old = cli.read_text(action.path)
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), shown, shown, n=1, lineterm=""))
    if not approved:
        return [f"NEED_CONFIG_APPROVAL {shown} (rerun with --yes-config to add):"] + diff
    if dry_run:
        return [f"CONFIG_MERGED {shown} (dry run; would add):"] + diff
    cli.atomic_write(action.path, new)
    return [f"CONFIG_MERGED {shown}"]


# ---------------------------------------------------------------- actions


def _safe_roots(root: Path) -> list[Path]:
    """Real locations conversion may touch: every checkout and its `.w2c/` ledger,
    which can itself be a link to a folder outside the checkout."""
    found: list[Path] = []
    for base in [path for path, _b in checkouts(root)] + [Path(root)]:
        for place in (base, base / ".w2c"):
            if place.exists():
                real = place.resolve()
                if real not in found:
                    found.append(real)
    return found


def _inside(path: Path, roots: list[Path], *, follow: bool = True) -> bool:
    """True when `path` really sits inside one of `roots` after links are resolved.
    With follow=False the last part is not followed, for removing a link itself."""
    if ".." in path.parts:
        return False
    real = path.resolve() if follow else path.parent.resolve() / path.name
    return any(real.is_relative_to(base) for base in roots)


def _allowed(path: Path, roots: list[Path]) -> None:
    if not _inside(path, roots):
        raise _error(f"refusing to write {path}: it is not inside a checkout")


def check_plan_paths(root: Path, plan: ConversionPlan) -> None:
    """Refuse the whole plan, before the backup or any write, when an action's
    path leads outside the checkouts (for example through a linked folder)."""
    roots = _safe_roots(root)
    for action in plan.actions:
        _allowed(action.path, roots)


def _copy_report(action: Action, yes_rewrites: bool) -> None:
    source = Path(action.detail.removeprefix("<- ").strip())
    raw = source.read_bytes()
    data = _rewrite(raw.decode("utf-8"), yes_rewrites).encode("utf-8") if yes_rewrites else raw
    target = action.path
    if target.exists():
        if target.read_bytes() == data:
            return
        raise _error(f"{target} exists and differs from {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _write_new(path: Path, content: str) -> None:
    if path.exists():
        if _cli().read_text(path) == content:
            return
        raise _error(f"{path} exists; it would be overwritten")
    _cli().atomic_write(path, content)


def _rename_link(meta: Path, mid: str) -> None:
    text = ledger._read_raw(meta)
    new, count = re.subn(rf"(?m)^{re.escape(LEGACY_LINK_KEY)}[ \t]*:.*$", f"x-delivery-legacy-id: {mid}", text, count=1)
    if not count:
        raise _error(f"{meta} has no {LEGACY_LINK_KEY} key")
    _cli().atomic_write(meta, new)


def apply_conversion(root: Path, plan: ConversionPlan, *, yes_config: bool, yes_rewrites: bool) -> list[str]:
    """Apply every planned action except the ROADMAP and ledger removals, which wait
    for verification (`finish_conversion`). Returns the lines to print."""
    cli = _cli()
    root = Path(root)
    roots = _safe_roots(root)
    out = _rewrite_lines(root, plan, yes_rewrites)
    for action in plan.actions:
        kind, path = action.kind, action.path
        if kind in DEFERRED_KINDS:
            continue
        _allowed(path, roots)
        if kind == "write-key":
            key = KEY_DETAIL_RE.match(action.detail)
            if not key:
                raise _error(f"cannot read the key in {action.detail!r}")
            ledger.write_key(path, key.group(1), action.content)
        elif kind == "rename-key":
            _rename_link(path, action.content)
        elif kind == "append-section":
            match = APPEND_DETAIL_RE.match(action.detail)
            if not match:
                raise _error(f"cannot read the heading in {action.detail!r}")
            order = layout.DESIGN_HEADINGS if path.name == "design.md" else ()
            text = _append_to_section(cli.read_text(path), match.group(1), _rewrite(action.content, yes_rewrites), order)
            cli.atomic_write(path, text)
        elif kind == "write-group-fields":
            number = int(GROUP_DETAIL_RE.match(action.detail).group(1))
            cli.atomic_write(path, _insert_group_fields(cli.read_text(path), number,
                                                        _rewrite(action.content, yes_rewrites)))
        elif kind == "write-read-first":
            cli.atomic_write(path, _insert_read_first(cli.read_text(path), action.content))
        elif kind == "copy-report":
            _copy_report(action, yes_rewrites)
        elif kind == "copy-decisions":
            cli.atomic_write(path, _insert_decisions(cli.read_text(path), _rewrite(action.content, yes_rewrites)))
        elif kind == "sync-knowledge":
            cli.atomic_write(path, _sync_knowledge(cli.read_text(path), _rewrite(action.content, yes_rewrites)))
        elif kind == "edit-gitattributes":
            existing = cli.read_text(path)
            if commands.ATTRIBUTES_LINE not in existing.splitlines():
                if existing and not existing.endswith("\n"):
                    existing += "\n"
                cli.atomic_write(path, existing + action.content)
        elif kind == "edit-config":
            out += _config_lines(root, action, approved=yes_config)
        elif kind == "mark-converted":
            cli.atomic_write(path, action.content.rstrip("\n") + "\n")
        elif kind == "write-decisions-file":
            _write_new(path, _rewrite(action.content, yes_rewrites))
        else:
            raise _error(f"unknown action kind {kind}")
    return out


def finish_conversion(root: Path, plan: ConversionPlan) -> None:
    """After verification: drop the converted ROADMAP lines, then rebuild STATE.md and
    QUEUE.md, or retire the ledger files when no 2.2 milestone remains."""
    cli = _cli()
    for action in plan.actions:
        if action.kind != "roadmap-remove":
            continue
        lines = _lines(cli.read_text(action.path))
        wanted = action.content.rstrip("\r\n")
        index = next((i for i, line in enumerate(lines) if line.rstrip("\r\n") == wanted), None)
        if index is not None:
            del lines[index]
            cli.atomic_write(action.path, "".join(lines))
    deletes = [a for a in plan.actions if a.kind == "delete-ledger-file"]
    for action in deletes:
        if action.path.is_dir() and not action.path.is_symlink():
            shutil.rmtree(action.path)
        elif action.path.exists() or action.path.is_symlink():
            action.path.unlink()
    if not deletes and any(a.kind == "roadmap-remove" for a in plan.actions):
        cli.rebuild_ledger(Path(root))


# ---------------------------------------------------------------- backup, restore


def _runs(root: Path) -> list[Path]:
    base = w2c_local.backup_dir_for(root)
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob(RUN_PREFIX + "*") if (p / MANIFEST_NAME).is_file())


def _read_manifest(run: Path) -> dict:
    return json.loads((run / MANIFEST_NAME).read_text(encoding="utf-8"))


def _write_manifest(run: Path, manifest: dict) -> None:
    _cli().atomic_write(run / MANIFEST_NAME, json.dumps(manifest, indent=2) + "\n")


def _run_label(run: Path) -> str:
    return f"the run started {_read_manifest(run).get('created', run.name)}"


def _owner(path: Path, roots: list[Path]) -> Path:
    found = [base for base in roots if path.is_relative_to(base)]
    return max(found, key=lambda base: len(base.parts)) if found else path.parent


def _touched(root: Path, plan: ConversionPlan) -> list[Path]:
    wdir = root / ".w2c"
    seen: list[Path] = []
    for action in plan.actions:
        if action.path.is_relative_to(wdir) or action.path in seen:
            continue
        seen.append(action.path)
    return seen


def backup(root: Path, plan: ConversionPlan, milestones: list[str]) -> Path:
    """Back up `.w2c/` and every file an action will touch; write the manifest."""
    root = Path(root)
    w2c_local.backup_w2c_assets(root)
    base = w2c_local.backup_dir_for(root)
    run = base / (RUN_PREFIX + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    run.mkdir(parents=True)
    roots = [path for path, _b in checkouts(root)]
    wdir = root / ".w2c"
    manifest: dict = {
        "version": MANIFEST_VERSION,
        "root": str(root),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "milestones": milestones,
        "w2c": None,
        "files": [],
        "complete": False,
        "restored": False,
    }
    if wdir.exists():
        real = wdir.resolve()
        shutil.copytree(real, run / "w2c", symlinks=True)
        manifest["w2c"] = {"path": str(real), "backup": "w2c"}
    for number, path in enumerate(_touched(root, plan), start=1):
        record: dict = {"path": str(path), "checkout": str(_owner(path, roots))}
        if path.is_file():
            stored = Path("files") / f"{number:04d}"
            (run / stored).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, run / stored)
            record.update(state="present", backup=stored.as_posix())
        elif path.exists():
            raise _error(f"{path} is not a file")
        else:
            missing: list[str] = []
            parent = path.parent
            while not parent.exists():
                missing.append(str(parent))
                parent = parent.parent
            record.update(state="absent", created_dirs=missing)
        manifest["files"].append(record)
    _write_manifest(run, manifest)
    return run


ABSENT = "absent"


def _file_hash(path: Path) -> str:
    if path.is_symlink():
        return "symlink:" + str(path.readlink())
    if not path.is_file():
        return ABSENT
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hashes(base: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    if not base.is_dir():
        return found
    for dirpath, dirs, files in os.walk(base):
        folder = Path(dirpath)
        for name in files + [d for d in dirs if (folder / d).is_symlink()]:
            path = folder / name
            found[path.relative_to(base).as_posix()] = _file_hash(path)
    return found


def _ledger_changes(run: Path, manifest: dict) -> dict[str, str]:
    """`.w2c/` paths the run changed, mapped to their hash after the run (or absent)."""
    saved = manifest.get("w2c")
    if not saved:
        return {}
    before = _tree_hashes(run / saved["backup"])
    after = _tree_hashes(Path(saved["path"]))
    return {rel: after.get(rel, ABSENT) for rel in sorted(set(before) | set(after))
            if before.get(rel) != after.get(rel)}


def _record_after(run: Path, manifest: dict) -> None:
    """At completion: each target's post-run hash, and every `.w2c/` file the run changed."""
    for record in manifest["files"]:
        record["after"] = _file_hash(Path(record["path"]))
    if manifest.get("w2c"):
        manifest["w2c"]["after"] = _ledger_changes(run, manifest)


def _drift(manifest: dict) -> list[str]:
    """Paths whose bytes differ from what a complete run left behind."""
    found = [record["path"] for record in manifest["files"]
             if "after" in record and _file_hash(Path(record["path"])) != record["after"]]
    saved = manifest.get("w2c") or {}
    base = Path(saved["path"]) if saved else None
    for rel, want in (saved.get("after") or {}).items():
        if _file_hash(base / rel) != want:
            found.append(str(base / rel))
    return found


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _check_restore_paths(manifest: dict, roots: list[Path]) -> None:
    """Refuse, before anything changes, a manifest that points outside the checkouts."""
    bad: list[str] = []
    for record in manifest["files"]:
        path = Path(record["path"])
        if not _inside(path, roots, follow=record["state"] == "present"):
            bad.append(str(path))
        bad += [folder for folder in record.get("created_dirs", [])
                if not _inside(Path(folder), roots, follow=False)]
    saved = manifest.get("w2c")
    if saved:
        target = Path(saved["path"])
        if not _inside(target, roots):
            bad.append(str(target))
        bad += [str(target / rel) for rel in saved.get("after") or {}
                if not _inside(target / rel, roots, follow=False)]
    if bad:
        raise _error("refusing to restore: these paths are not inside a checkout: " + ", ".join(bad))


def _restore_run(run: Path, root: Path) -> int:
    manifest = _read_manifest(run)
    _check_restore_paths(manifest, _safe_roots(root))
    for record in reversed(manifest["files"]):
        path = Path(record["path"])
        if record["state"] == "present":
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(run / record["backup"], path)
            continue
        _remove(path)
        for folder in record.get("created_dirs", []):
            try:
                Path(folder).rmdir()
            except OSError:
                break
    saved = manifest.get("w2c")
    if saved:
        target = Path(saved["path"])
        copy = run / saved["backup"]
        if "after" in saved:
            # A complete run: put back only what the run changed, keep everything else.
            for rel in saved["after"]:
                source, dest = copy / rel, target / rel
                _remove(dest)
                if source.is_symlink() or source.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if source.is_symlink():
                        dest.symlink_to(source.readlink())
                    else:
                        shutil.copy2(source, dest)
                else:
                    parent = dest.parent
                    while parent != target and parent.is_dir() and not any(parent.iterdir()):
                        parent.rmdir()
                        parent = parent.parent
            for folder in sorted((p for p in copy.rglob("*") if p.is_dir() and not p.is_symlink()), key=str):
                (target / folder.relative_to(copy)).mkdir(parents=True, exist_ok=True)
        else:
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(copy, target, symlinks=True)
    manifest["restored"] = True
    manifest["restored_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_manifest(run, manifest)
    return len(manifest["files"])


def _restore_latest(root: Path) -> int:
    runs = _runs(Path(root))
    if not runs or _read_manifest(runs[-1]).get("restored"):
        print("NOTHING_TO_RESTORE")
        return 0
    run = runs[-1]
    manifest = _read_manifest(run)
    if manifest.get("complete"):
        drift = _drift(manifest)
        if drift:
            for path in drift:
                print(f"CHANGED_SINCE_RUN {path}")
            print(f"RESTORE_REFUSED {len(drift)} file(s) changed after {_run_label(run)}; nothing restored. "
                  "Undo those edits or restore the files by hand.")
            return 1
    count = _restore_run(run, root)
    print(f"RESTORED {count} files and .w2c/ from {_run_label(run)}")
    return 0


def restore(root: Path) -> None:
    """Restore the latest run exactly, then mark it restored. A complete run is
    refused, with nothing changed, when any file it wrote has changed since."""
    _restore_latest(root)


def _changed(record: dict, run: Path) -> bool:
    path = Path(record["path"])
    if record["state"] == "absent":
        return path.exists()
    return not path.is_file() or path.read_bytes() != (run / record["backup"]).read_bytes()


# ---------------------------------------------------------------- verify


def _original(manifest: dict, run: Path, path: Path) -> str:
    for record in manifest["files"]:
        if Path(record["path"]) == path:
            if record["state"] == "absent":
                return ""
            return (run / record["backup"]).read_text(encoding="utf-8")
    return ""


def _pending_lines(plan: ConversionPlan, yes_rewrites: bool) -> set[str]:
    lines = {text.strip() for _p, _n, text in plan.unknown_w2c_lines}
    if not yes_rewrites:
        lines |= {old.strip() for _p, _n, old, _new in plan.known_rewrites}
    return lines


def _converted(plan: ConversionPlan) -> dict[str, Path]:
    """Legacy id -> change folder."""
    out: dict[str, Path] = {}
    for action in plan.actions:
        if action.kind == "rename-key" or (action.kind == "write-key" and action.detail.startswith("x-delivery-legacy-id:")):
            out[action.content] = action.path.parent
    return out


def _minus(lines: list[str], inserted: list[str]) -> tuple[list[str], list[str]]:
    """`lines` with one occurrence of each inserted line removed (compared stripped),
    and the inserted lines that were not found."""
    counts = Counter(line.strip() for line in inserted if line.strip())
    kept: list[str] = []
    for line in lines:
        key = line.strip()
        if key and counts[key] > 0:
            counts[key] -= 1
            continue
        kept.append(line)
    return kept, [line for line, left in counts.items() for _ in range(left)]


def _by_heading(content: str) -> dict[str, list[str]]:
    """Lines of planned content grouped by the `## ` section they land in."""
    return {heading: body for heading, body in section_bodies(content).items()}


def _inserted_problems(root: Path, plan: ConversionPlan, manifest: dict, run: Path, yes_rewrites: bool,
                       pending: set[str]) -> list[str]:
    """tasks.md, knowledge.md and config.yaml: each original section, minus exactly
    the lines this run inserted there, must equal the original."""
    cli = _cli()
    problems: list[str] = []
    inserted: dict[Path, dict[str, list[str]]] = {}
    configs: list[Path] = []
    for action in plan.actions:
        content = _rewrite(action.content, yes_rewrites)
        if action.kind == "write-group-fields":
            text = cli.read_text(action.path)
            number = int(GROUP_DETAIL_RE.match(action.detail).group(1))
            heading = next((h for h, _s, _e in _level2(text.splitlines())
                            if (m := checks.GROUP_LINE_RE.match(h)) and int(m.group(1)) == number), None)
            if heading is None:
                problems.append(f"group-fields {_rel(root, action.path)}: no ## {number}. group")
                continue
            inserted.setdefault(action.path, {}).setdefault(heading, []).extend(content.splitlines())
        elif action.kind == "write-read-first":
            inserted.setdefault(action.path, {}).setdefault(PREAMBLE, []).extend(content.splitlines())
            now = cli.read_text(action.path)
            head = section_bodies(now)[PREAMBLE]
            if checks.read_first_problems(now) or _collapse(action.content.splitlines()) not in _collapse(head):
                problems.append(f"read-first {_rel(root, action.path)}: the block is not at the top of tasks.md")
        elif action.kind == "sync-knowledge":
            for heading, body in _by_heading(content).items():
                inserted.setdefault(action.path, {}).setdefault(heading, []).extend(body)
        elif action.kind == "edit-config":
            configs.append(action.path)
    for path, by_heading in inserted.items():
        original = section_bodies(_original(manifest, run, path))
        now = section_bodies(cli.read_text(path))
        for heading in sorted(set(original) | set(now) | set(by_heading)):
            kept, lost = _minus(now.get(heading, []), by_heading.get(heading, []))
            label = f"{_rel(root, path)} {heading or '(before the first ##)'}"
            if lost:
                problems.append(f"inserted-lines {label}: missing {lost[0][:60]}")
            if _collapse(kept, pending) != _collapse(original.get(heading, []), pending):
                problems.append(f"section-fingerprint {label}: text other than the inserted lines changed")
    for path in configs:
        before, now = _original(manifest, run, path), cli.read_text(path)
        if now == before:
            continue
        problems += [f"config {_rel(root, path)}: {item}" for item in config_problems(now)]
        def count(text: str) -> Counter:
            return Counter(line.strip() for line in text.splitlines() if line.strip())

        if count(before) - count(now) or count(now) - count(before) - count(layout.CONFIG_RULES_SNIPPET):
            problems.append(f"config {_rel(root, path)}: lines other than the cloud rules changed")
    return problems


def config_problems(text: str, snippet: str = layout.CONFIG_RULES_SNIPPET) -> list[str]:
    """Each snippet item must sit exactly once under its key; no top-level key twice."""
    lines = _lines(text)
    problems = [f"top-level {key} appears {n} times" for key in CONFIG_KEYS
                if (n := len(_find_key(lines, 0, len(lines), 0, key))) > 1]
    for _key, block in _snippet_blocks(snippet):
        for path, _kind, items in _snippet_parts(block):
            got = _leaf_lines(lines, path)
            name = ".".join(path)
            if got is None:
                problems.append(f"{name} is missing")
                continue
            for item in items:
                count = got.count(item.strip())
                if count != 1:
                    problems.append(f"{name} holds {item.strip()[:50]!r} {count} times")
    return problems


def _verify(root: Path, plan: ConversionPlan, run: Path, yes_rewrites: bool) -> tuple[list[str], list[str]]:
    """(failures, pending edits). Every placed section, field, key, report and line
    is checked against the plan, then cloud smoke and cloud next."""
    cli = _cli()
    manifest = _read_manifest(run)
    pending = _pending_lines(plan, yes_rewrites)
    failures: list[str] = []
    notes: list[str] = []
    header = {line.strip() for line in commands.DECISION_HEADER.splitlines()}

    sections: dict[Path, list[Action]] = {}
    for action in plan.actions:
        if action.kind in ("append-section", "copy-decisions"):
            sections.setdefault(action.path, []).append(action)
    for path, actions in sections.items():
        original = section_bodies(_original(manifest, run, path))
        expected = {heading: list(body) for heading, body in original.items()}
        rows: list[str] = []
        touched: list[str] = []
        for action in actions:
            content = _rewrite(action.content, yes_rewrites)
            if action.kind == "copy-decisions":
                rows += [line for line in content.splitlines() if line.strip()]
                continue
            heading = APPEND_DETAIL_RE.match(action.detail).group(1)
            expected.setdefault(heading, []).extend(content.splitlines())
            if heading not in touched:
                touched.append(heading)
        exclude = pending | header | {row.strip() for row in rows}
        now = cli.read_text(path)
        actual = section_fingerprints(now, exclude)
        # Every section: the touched ones hold their original text plus what was
        # placed; every other one (and the text before the first heading) is unchanged.
        for heading, body in expected.items():
            if actual.get(heading) != _sha(_collapse(body, exclude)):
                failures.append(f"section-fingerprint {_rel(root, path)} {heading or '(before the first ##)'}")
        for heading in actual:
            if heading not in expected:
                failures.append(f"section-fingerprint {_rel(root, path)} {heading}: unexpected section")
        decisions = {line.strip() for line in section_bodies(now).get("## Decisions", [])}
        for row in rows:
            if row.strip() not in decisions:
                failures.append(f"decision-rows {_rel(root, path)}: {row.strip()[:60]}")

    failures += _inserted_problems(root, plan, manifest, run, yes_rewrites, pending)

    for action in plan.actions:
        kind, path = action.kind, action.path
        shown = _rel(root, path)
        if kind == "write-group-fields":
            number = int(GROUP_DETAIL_RE.match(action.detail).group(1))
            want = checks.slice_fields(f"## {number}. x\n" + _rewrite(action.content, yes_rewrites)).get(number, {})
            have = checks.slice_fields(cli.read_text(path)).get(number, {})
            for name, value in want.items():
                if _collapse(value.splitlines(), pending) != _collapse(have.get(name, "").splitlines(), pending):
                    failures.append(f"group-fields {shown} group {number}: {name}")
        elif kind in ("write-key", "rename-key"):
            keys = ledger.read_keys(path)
            name = "x-delivery-legacy-id" if kind == "rename-key" else KEY_DETAIL_RE.match(action.detail).group(1)
            if keys.get(name) != ledger._clean_value(action.content) or (
                    kind == "rename-key" and LEGACY_LINK_KEY in keys):
                failures.append(f"delivery-key {shown}: {name}")
        elif kind == "copy-report":
            source = Path(action.detail.removeprefix("<- ").strip())
            want = _rewrite(source.read_text(encoding="utf-8"), yes_rewrites) if yes_rewrites else source.read_text(encoding="utf-8")
            if not path.is_file() or path.read_text(encoding="utf-8") != want:
                failures.append(f"copy-report {shown}")
        elif kind in ("sync-knowledge", "write-decisions-file", "edit-gitattributes", "mark-converted"):
            have = {line.strip() for line in cli.read_text(path).splitlines()}
            content = _rewrite(action.content, yes_rewrites)
            lost = [line.strip() for line in content.splitlines() if line.strip() and line.strip() not in have]
            if lost:
                failures.append(f"{kind} {shown}: missing {lost[0][:60]}")

    changes: dict[Path, list[ledger.CloudChange]] = {}
    roots = [path for path, _b in checkouts(root)]
    folders = _converted(plan)
    for mid, folder in folders.items():
        change = ledger.load_change(folder)
        if change is None:
            failures.append(f"delivery-keys-valid {mid}: {_rel(root, folder)} has no x-delivery-status")
            continue
        changes.setdefault(_owner(folder, roots), []).append(change)
    for checkout, items in changes.items():
        for name, state, detail in checks.smoke_rows(checkout, items):
            if state == "FAIL" and name not in ("neutral-artifacts", "commit-pr-conventions"):
                failures.append(f"{name} {detail}")
        for change in items:
            if not change.archived:
                for found in checks.neutral_problems(change):
                    rel = found.split(": ", 1)[1]
                    target = change.path / rel
                    text = "" if not target.is_file() else checks._read(target)
                    left = [line for line in text.splitlines() if line.strip() not in pending]
                    if "w2c" in rel.lower() or "w2c" in "\n".join(left).lower():
                        failures.append(f"neutral-artifacts {found}")
                    else:
                        notes.append(f"neutral-artifacts {found} (a line listed above needs an edit)")
            if checks.converted_history(change):
                continue
            design = change.path / "design.md"
            text = cli.read_text(design)
            problems = checks.validate_conventions(text)
            if not problems:
                continue
            approved = "".join((_rewrite_line(line, True) or "") + "\n" for line in text.splitlines()
                               if _rewrite_line(line, True) is not None)
            target = notes if not checks.validate_conventions(approved) and pending else failures
            for problem in problems:
                target.append(f"commit-pr-conventions {change.name}: {problem}")

    for mid, before in plan.next_before.items():
        folder = folders.get(mid)
        change = ledger.load_change(folder) if folder else None
        if change is None or change.status == "DONE":
            continue
        task = commands.next_task(_owner(folder, roots), mid, None, None)
        after = (task.sid, task.tid) if task else None
        wanted = tuple(before[1:]) if before else None
        if after != wanted:
            failures.append(f"next {mid}: 2.2 {' '.join(wanted) if wanted else 'none'}, "
                            f"cloud {' '.join(after) if after else 'none'}")
    return failures, notes


# ---------------------------------------------------------------- command


def _rewrite_lines(root: Path, plan: ConversionPlan, yes_rewrites: bool) -> list[str]:
    token = "REWRITE" if yes_rewrites else "NEED_REWRITE_APPROVAL"
    out = [f"{token} {_rel(root, path)}:{number} {old} -> {_shown(new)}"
           for path, number, old, new in plan.known_rewrites]
    out += [f"MANUAL_EDIT {_rel(root, path)}:{number} {text}" for path, number, text in plan.unknown_w2c_lines]
    return out


def _print_plan(root: Path, plan: ConversionPlan, yes_config: bool, yes_rewrites: bool) -> None:
    """The dry run: the same approval labels the real run would print with these flags."""
    for action in plan.actions:
        print(f"PLAN {action.kind} {_rel(root, action.path)} {action.detail}".rstrip())
        if action.kind == "edit-config":
            for line in _config_lines(root, action, approved=yes_config, dry_run=True):
                print(line)
    for blocker in plan.blockers:
        print(f"BLOCKED {blocker}")
    for line in _rewrite_lines(root, plan, yes_rewrites):
        print(line)
    for mid in plan.skipped:
        print(f"SKIPPED {mid}: already converted (x-delivery-legacy-id is set)")
    for mid, task in plan.next_before.items():
        print(f"NEXT_BEFORE {mid} {' '.join(task[1:]) if task else 'none'}")
    print("DRY_RUN nothing written")


def cmd_migrate(root: Path, milestones: list[str] | None, all_: bool, dry_run: bool, restore_: bool,
                yes_config: bool, yes_rewrites: bool) -> int:
    root = Path(root)
    if restore_:
        if milestones or all_ or dry_run:
            raise _error("--restore takes no --milestone, --all or --dry-run")
        return _restore_latest(root)
    if bool(milestones) == bool(all_):
        raise _error("pass exactly one of --milestone or --all")
    runs = _runs(root)
    if runs:
        last = _read_manifest(runs[-1])
        if not last.get("complete") and not last.get("restored"):
            print(f"REFUSED {_run_label(runs[-1])} did not finish; {RESTORE_FIRST}")
            return 1
    plan = plan_conversion(root, None if all_ else list(milestones or []))
    if not plan.blockers and _converted(plan) and not osl.cli_check()[1]:
        plan.blockers.append("openspec is not installed or too old; cloud smoke needs it")
    if dry_run:
        _print_plan(root, plan, yes_config, yes_rewrites)
        return 1 if plan.blockers else 0
    if plan.blockers:
        for blocker in plan.blockers:
            print(f"BLOCKED {blocker}")
        return 1
    for mid in plan.skipped:
        print(f"SKIPPED {mid}: already converted (x-delivery-legacy-id is set)")
    if not plan.actions:
        print("NOTHING_TO_CONVERT")
        return 0
    converted = list(_converted(plan))
    check_plan_paths(root, plan)
    run = backup(root, plan, converted)
    try:
        for line in apply_conversion(root, plan, yes_config=yes_config, yes_rewrites=yes_rewrites):
            print(line)
        failures, notes = _verify(root, plan, run, yes_rewrites)
        for note in notes:
            print(f"PENDING_EDIT {note}")
        if failures:
            for failure in failures:
                print(f"VERIFY_FAIL {failure}")
            count = _restore_run(run, root)
            print(f"RESTORED {count} files and .w2c/ from {_run_label(run)}")
            return 1
        finish_conversion(root, plan)
    except Exception:
        count = _restore_run(run, root)
        print(f"RESTORED {count} files and .w2c/ from {_run_label(run)}")
        raise
    manifest = _read_manifest(run)
    _record_after(run, manifest)
    for mid, folder in _converted(plan).items():
        print(f"CONVERTED {mid} -> {folder.name}")
    for record in sorted(manifest["files"], key=lambda r: (r["checkout"], r["path"])):
        if _changed(record, run):
            checkout = Path(record["checkout"])
            print(f"COMMIT {checkout} {_rel(checkout, Path(record['path']))}")
    if manifest.get("w2c") and ledger_store.tracking(root):
        # track = true: the ledger is committed in this checkout, so its changes are listed too.
        for rel in manifest["w2c"]["after"]:
            if not (rel == "runtime" or rel.startswith("runtime/")):
                print(f"COMMIT {root} .w2c/{rel}")
    manifest["complete"] = True
    manifest["completed"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_manifest(run, manifest)
    print("NOT_COMMITTED review and commit the paths above yourself; undo with w2c cloud migrate --restore")
    return 0
