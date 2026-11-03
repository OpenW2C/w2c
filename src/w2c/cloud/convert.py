"""Plan the conversion of 2.2 OpenSpec milestones to cloud changes.

`plan_conversion` reads the 2.2 ledger, the plan folders, and the target
changes, and returns every action and every blocker. It writes nothing. Every
source section maps to a target, is consumed into a key, is a documented drop
(`layout.LEGACY_DROPPED_FIELDS`, `layout.LEGACY_DROPPED_GUARDRAILS`), or is a
blocker. The CLI package is imported lazily.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from w2c import ledger_store
from w2c import local as w2c_local
from w2c import openspec_ledger as osl
from w2c.cloud import checks, commands, layout

ACTION_KINDS: tuple[str, ...] = (
    "write-key",
    "rename-key",
    "append-section",
    "write-group-fields",
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
    ("slice", "**Demo:**"): ("tasks.md", "**Demo:**"),
    **{("slice", f"## {f}"): ("tasks.md", f"**{f}:**") for f in _SLICE_SECTION_FIELDS},
    ("slice", "## Git Operation Plan"): ("design.md", "## Delivery Plan"),
    ("slice", "### Guardrails"): ("design.md", "## Guardrails"),
    ("slice", "## Commit and PR conventions"): ("design.md", "## Commit and PR Conventions"),
    ("manual-test", "MANUAL-TEST.md"): ("design.md", "## Manual Test Guide"),
    ("amendments", "AMENDMENTS.md"): ("design.md", "## Amendments"),
}

# Context sections land inside a design section as `###` subsections.
SUBSECTIONS: dict[tuple[str, str], str] = {
    ("context", "## Key Decisions"): "### Key Decisions",
    ("context", "## Decision Rationale"): "### Decision Rationale",
    ("context", "## Validation"): "### Validation",
    ("context", "## Completion Criteria"): "### Completion Criteria",
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
    "Planner: fill a deny-list. Always include `.delivery/` and any local planner files. Add notable "
    "paths from the client `.gitignore` (e.g. `.env*`, credentials, local IDE junk). Product commits "
    "must never stage these paths, including any `### Base dirt paths` listed in the Delivery Plan."
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

# Every 2.x template line that names the tool, mapped to the neutral line in
# templates/cloud/ that carries the same rule. Applied only with approval.
KNOWN_REWRITES: dict[str, str] = {
    "| Integration strategy | (from .w2c/DELIVERY-PROFILE.md) |":
        "| Integration strategy | (from the project's delivery profile) |",
    # The row is a dropped field; its rule (cadence source) lives in this guardrail.
    "| Commit cadence | (from .w2c/config.toml git_delivery) |": _NEUTRAL_CADENCE,
    "- **Commit cadence** — read `git_delivery` from `.w2c/config.toml`. Never commit, push, or open a "
    "PR without explicit user approval for that action.": _NEUTRAL_CADENCE,
    # A dropped guardrail; its rule (planner files are never committed) lives in the deny-list line.
    "- **Plan commit** — when `track` is false, write `ledger-bind` and do not commit `.w2c/`. The `w2c` "
    "command shares one ledger across worktrees. When `track` is true, a separate plan commit may include "
    "`.w2c/` plan files except `runtime/`. No push without approval.": _NEUTRAL_DENY,
    "- **Status writes** — never hand-edit STATE.md, QUEUE.md, ROADMAP status emojis, or task checkboxes. "
    "Use `w2c` on PATH. `w2c complete` is the only writer of checkboxes in `tasks.md`.": _NEUTRAL_STATUS,
    "- **Status writes** — never hand-edit STATE.md, QUEUE.md, ROADMAP status emojis, or task checkboxes. "
    "Use `w2c` on PATH.": _NEUTRAL_STATUS,
    "- **Status writes** — never hand-edit STATE.md, QUEUE.md, ROADMAP status emojis, or task checkboxes. "
    "Use `.w2c/scripts/w2c.sh`.": _NEUTRAL_STATUS,
    _LEGACY_COMMIT_PR: _NEUTRAL_COMMIT_PR,
    _LEGACY_INSPECT: _NEUTRAL_INSPECT,
    _LEGACY_DENY: _NEUTRAL_DENY,
    _LEGACY_MENTION: _NEUTRAL_MENTION,
    _LEGACY_SLICE_STATUS: _NEUTRAL_STATUS,
    _LEGACY_SLICE_CADENCE: _NEUTRAL_CADENCE,
    _LEGACY_SLICE_COMMIT_PR.format(who="roadmap"): _NEUTRAL_COMMIT_PR,
    _LEGACY_SLICE_COMMIT_PR.format(who="ROADMAP"): _NEUTRAL_COMMIT_PR,
    # The classic Slices comment: in cloud mode a slice is a `## N.` task group.
    "<!-- REQUIRED literal format -- the w2c CLI's parse_slices() only recognizes this exact": "## N. TITLE",
    "     checkbox line shape. A markdown table (or any other shape) here means w2c will see": "## N. TITLE",
}

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
CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
AMEND_HEAD_RE = re.compile(r"^## (A\d+) (\S+) (\S+)[ \t]*$")
TASK_REPORT_RE = re.compile(r"^S\d+-T\d+-SUMMARY\.md$")
SLICE_REPORT_RE = re.compile(r"^S\d+-(UAT|SUMMARY)\.md$")

Record = tuple[Path, int | None, str]


def _cli():
    from w2c import cli as w2c_cli

    return w2c_cli


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
    known_rewrites: list[tuple[Path, int, str, str]] = field(default_factory=list)
    unknown_w2c_lines: list[tuple[Path, int, str]] = field(default_factory=list)
    next_before: dict[str, tuple[str, str, str] | None] = field(default_factory=dict)


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
        """Sort copied lines that name the tool into known rewrites and manual edits."""
        for path, number, text in lines:
            if "w2c" not in text.lower():
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
        if not ledger_store.is_git(self.root):
            return [(self.root, "")]
        found: list[tuple[Path, str]] = []
        for path in ledger_store._worktree_paths(self.root):
            if not path.is_dir():
                continue
            if path.resolve() == self.root.resolve():
                path = self.root
            found.append((path, ledger_store.current_branch(path)))
        return found or [(self.root, ledger_store.current_branch(self.root))]

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
        remaining = [mid for mid in by_id if mid not in selected]
        if milestones is None and selected and not remaining:
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
        self.touch(checkout, folder)
        done = mil.status == "DONE"
        declined = archive == "declined"
        archived = osl.is_archived(text)
        if done and not (declined or archived):
            self.block(f"{mid}: DONE but its OpenSpec archive is neither recorded nor declined")
        self._keys(mid, mil.status, order, text, folder, done=done, archived=archived, declined=declined)
        if not done:
            self._content(mid, plan_dir, text, folder, name)
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
                found["conventions"] = section.body
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
        for path in sorted(plan_dir.iterdir()):
            match = plan_re.match(path.name)
            if not match or not path.is_file():
                continue
            number = int(match.group(1))
            sid = f"S{number:02d}"
            where = path.name
            fields, guards = self._slice_plan(mid, path, merged, extras_text, conv, base_dirt)
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
                    lines.append(_gen(f"**{name}:**"))
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
            if empty:
                detail += f"; empty: {', '.join(empty)}"
            self.act("write-group-fields", tasks, detail, _text(lines))
        return carried

    def _slice_plan(self, mid: str, path: Path, merged: dict[str, str], extras_text: set[str],
                    conv: list[str], base_dirt: list[str]) -> tuple[dict[str, list[Record]], list[Record]]:
        where = path.name
        lines = _strip_frontmatter(_records(path))
        preamble, sections = _split(lines, 2)
        fields: dict[str, list[Record]] = {}
        guards: list[Record] = []
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
                fields[current] = [record] if bold.group(2).strip() else []
                continue
            if not text.strip():
                current = None
                continue
            if current is not None:
                fields[current].append(record)
            elif text.strip() not in SLICE_TEMPLATE_PROSE:
                self.block(f"{mid}: {where}:{record[1]} text before the first heading has no target")
        for section in sections:
            title = section.title
            if title in _SLICE_SECTION_FIELDS:
                fields[title] = section.body
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
                if _norm(section.body, _CONVENTIONS_INSTRUCTIONS) != conv:
                    self.block(f"{mid}: {where}:{section.heading[1]} Commit and PR conventions differ from the milestone's")
            else:
                self.block(f"{mid}: {where}:{section.heading[1]} ## {title} has no target")
        return fields, guards

    # ---------------------------------------------------------- design

    def _design(self, mid: str, plan_dir: Path, design: Path, design_text: str, milestone: dict,
                slice_guardrails: list[Record], name: str) -> None:
        road_name = f"{mid}-ROADMAP.md"
        self._delivery_plan(mid, design, design_text, milestone)
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

    @staticmethod
    def _demote(lines: list[Record]) -> list[Record]:
        levels = [len(m.group(1)) for r in lines if (m := HEADING_RE.match(r[2]))]
        if not levels:
            return lines
        shift = 3 - min(levels)
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

    def _reports(self, mid: str, plan_dir: Path, folder: Path) -> None:
        dest = folder / layout.REPORT_DIR
        for path in sorted(plan_dir.iterdir()):
            item = path.name
            if TASK_REPORT_RE.match(item) or SLICE_REPORT_RE.match(item):
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
        latest = self.cli.latest_context(self.root)
        if latest is None:
            return
        source = latest[2]
        target = checkout / commands.KNOWLEDGE_PATH
        have = {line.strip() for line in self.cli.read_text(target).splitlines()}
        _pre, sections = _split(_strip_frontmatter(_records(source)), 2)
        missing: dict[str, list[Record]] = {}
        for section in sections:
            if section.title not in KNOWLEDGE_SECTIONS:
                continue
            table = [r for r in section.body if r[2].lstrip().startswith("|")]
            for record in table[2:]:
                if record[2].strip() and record[2].strip() not in have:
                    missing.setdefault(section.title, []).append(record)
        if not missing and target.is_file():
            return
        lines: list[Record] = []
        for title in KNOWLEDGE_SECTIONS:
            if title in missing:
                lines += [_gen(f"## {title}")] + missing[title]
        self.scan(lines)
        counts = ", ".join(f"{t}: {len(missing[t])}" for t in KNOWLEDGE_SECTIONS if t in missing)
        mode = "create" if not target.is_file() else "add missing rows"
        self.touch(checkout, target)
        self.act("sync-knowledge", target, f"{mode} from {source.name} ({counts or 'no rows'})", _text(lines))

    def _retire_ledger(self) -> None:
        main = self.checkouts[0][0]
        rows = [r for r in _records(self.wdir / "DECISIONS.md") if DECISION_LINE_RE.match(r[2])]
        keep = [r for r in rows if len(_cells(r[2])) <= 2 or _cells(r[2])[2] not in self.copied_scopes]
        target = main / DECISIONS_FILE
        content = (
            "# Decisions\n\nFrozen copy of the decisions recorded before cloud mode. "
            "Rows keep their original ids.\n\n"
            + commands.DECISION_HEADER
            + _text(keep)
        )
        self.scan(keep)
        self.touch(main, target)
        ids = ", ".join(DECISION_LINE_RE.match(r[2]).group(1) for r in keep) or "none"
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
