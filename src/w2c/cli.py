#!/usr/bin/env python3
"""W2C ledger CLI — the only writer of .w2c status bits."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from w2c import __version__
from w2c import base_dirt
from w2c import local as w2c_local
from w2c import git_delivery as w2c_gd
from w2c import openspec as w2c_openspec
from w2c import openspec_ledger
from w2c import trials as w2c_trials
from w2c.skills_install import install_skills, write_copilot_instructions

STATUS_EMOJI = {
    "PLANNING": "\U0001f4cb",
    "TODO": "\u231b",
    "PAUSED": "\u23f8\ufe0f",
    "INPROGRESS": "\U0001f504",
    "DONE": "\u2705",
    "ERROR": "\u26d4",
    "STOP": "\u23f9\ufe0f",
}
EMOJI_STATUS = {}
for _name, _emo in STATUS_EMOJI.items():
    EMOJI_STATUS[_emo] = _name
    EMOJI_STATUS[_emo.replace("\ufe0f", "")] = _name

VALID_STATUSES = tuple(STATUS_EMOJI)

# In progress and done stay put. Paused, stopped, and rejected (ERROR) may be displaced.
FROZEN_STATUSES = frozenset({"INPROGRESS", "DONE"})

_EMOJI_ALT = "|".join(
    re.escape(e)
    for e in dict.fromkeys(
        [*STATUS_EMOJI.values(), *(e.replace("\ufe0f", "") for e in STATUS_EMOJI.values())]
    )
)
MILESTONE_LINE_RE = re.compile(
    r"^- +(?P<emoji>" + _EMOJI_ALT + r")\s+\*\*(?P<id>M\d+):\s*(?P<title>.+?)\*\*"
)
SLICE_LINE_RE = re.compile(r"^- \[([ xXdD])\] \*\*(S\d+):")
TASK_LINE_RE = re.compile(r"^- \[([ xXdD])\] \*\*(T\d+)\*\*")
DECISION_ROW_RE = re.compile(r"^\| (D\d+) \|", re.M)
CONTEXT_FILE_RE = re.compile(r"^CONTEXTv(\d+)\.(\d+)\.md$")
ID_M = re.compile(r"^M\d+$")
ID_S = re.compile(r"^S\d+$")
ID_T = re.compile(r"^T\d+$")

DECISIONS_HEADER = (
    "# Decisions Register\n\n"
    "<!-- Append-only. Never edit or remove existing rows.\n"
    "     To reverse a decision, add a new row that supersedes it.\n"
    "     Read this file at the start of any planning or research phase. -->\n\n"
    "| # | When | Scope | Decision | Choice | Rationale | Revisable? | Made By |\n"
    "|---|------|-------|----------|--------|-----------|------------|---------|\n"
)

STATE_TEMPLATE = """# State\n\n**Active Milestone:** None\n**Active Slice:** None\n**Phase:** idle\n**Requirements Status:** 0 active · 0 validated · 0 deferred · 0 out of scope\n\n## Milestone Registry\n\n## Recent Decisions\n\n## Blockers\n- None\n\n## Next Action\nPlan work with work-to-chores.\n"""

ROADMAP_TEMPLATE = "# Roadmap\n\n## Milestones\n"
QUEUE_TEMPLATE = "# Queue\n"

CONTEXT_BODY = """# Project Knowledge\n\nAppend-only register of project-specific rules, patterns, and lessons learned.\nAgents read this before every unit. Add entries when you discover something worth remembering.\n## Rules\n\n| # | Scope | Rule | Why | Added |\n|---|-------|------|-----|-------|\n\n## Patterns\n\n| # | Pattern | Where | Notes |\n|---|---------|-------|-------|\n\n## Lessons Learned\n\n| # | What Happened | Root Cause | Fix | Scope |\n|---|--------------|------------|-----|-------|\n"""

M_ROADMAP_STUB = """# {mid}: {title}

**Vision:**

## Success Criteria

## Slices

## Boundary Map

## In scope

## Out of scope

## Soft dependency

## Delivery & Guardrails
| Field | Value |
| --- | --- |
| Milestone / planning ID | {mid} |
| Human-readable scope slug | {slug} |
| Workstream name | |
| External ticket ID | |
| Integration strategy | (from .w2c/DELIVERY-PROFILE.md) |
| Integration branch | |
| Commit cadence | (from .w2c/config.toml git_delivery) |
| Review unit | none |
| Git/PR checkpoint mode | none |
| Isolation mode | |
| Branch name | |
| Execution sequence | |
| Validation commands | |
| Completion condition | All slices verified; honor git_delivery + explicit approval gates |
| Size budget (LOC diff) | |
| Manual test guide | no |

## Git Operation Plan
| Field | Value |
| --- | --- |
| Isolation mode | |
| Local branch | |
| Remote branch | |
| Isolation scope | ticket |
| Setup when | first-do-chores |
| Plan commit | required-before-isolation |
| Reuse policy | reuse-if-same-ticket-else-stop |
| Worktree skill | |
| Push rule | from config + explicit approval; push ref must equal Remote branch |
| Base dirt policy | |

### Guardrails
- **Commit cadence** — read `git_delivery` from `.w2c/config.toml`. Never commit, push, or open a PR without explicit user approval for that action.
- **Remote mutation** — no push, PR, or remote git mutation without explicit user approval.
- **Git isolation** — honor Isolation mode (`worktree` or `branch` only). Local branch must equal Remote branch (ticket id or confirmed slug). Setup on first `do-chores`; reuse the same ticket isolation across milestones.
- **Plan commit** — commit `.w2c/` plan/ledger files (never `runtime/`, never product code) onto the ticket branch before isolation so a worktree can see the ledger. No push without approval.
- **No force git** — never force-reset, force-push, or delete worktrees/branches. Dirty or unexpected existing branch/worktree → hard stop and ask.
- **Validation** — run the validation commands in this table before each commit and before each push.
- **Status writes** — never hand-edit STATE.md, QUEUE.md, ROADMAP status emojis, or task checkboxes. Use `.w2c/scripts/w2c.sh`.
- **Verify loop** — a task is not complete until its Verify commands pass and requesting-code-review is clean.
- **Closeout reports** — write `S##-T##-SUMMARY.md` before `complete`; `S##-UAT.md` + `S##-SUMMARY.md` before `slice-complete`; `M###-VALIDATION.md` + `M###-SUMMARY.md` before milestone DONE.
- **Commit and PR** — honor `## Commit and PR conventions`. Never add `Co-authored-by:` or similar AI co-author trailers. Never stage deny-listed paths on product commits. Never mention any `.w2c/` path or artifact in commit or PR text.

## Commit and PR conventions

Planner: inspect this repo (`CONTRIBUTING*`, `.github/*PULL_REQUEST_TEMPLATE*`, recent `git log` title/body, `.gitignore`, `.w2c/config.toml` `track`) and fill this section. Do not leave TBD.

**Commit title:**

**Commit body:**

**Pull request:**

**Do not stage / commit:**
Planner: fill a deny-list. Always include `.w2c/runtime/`. When `track = false`, include all of `.w2c/` and Copilot W2C instruction files. Add notable paths from client `.gitignore` (e.g. `.env*`, credentials, local IDE junk). Product commits must never stage these paths. Plan-commit (only when `track = true`) may stage ledger/plan files under `.w2c/` except `runtime/`.

**Do not mention:**
Never name any `.w2c/` path, ledger file, closeout report (`*-SUMMARY.md` / `*-UAT.md` / `*-VALIDATION.md` under `.w2c/`), or other W2C artifact in the commit title/body or PR title/body/description. Prefer “W2C ledger” / “planning artifacts” with no paths.

**AI attribution — forbidden:**
Do not add `Co-authored-by:` trailers or similar AI co-author / “assisted by Cursor, Copilot, Claude, or Codex” lines.
"""

M_CONTEXT_STUB = """# {mid} — {title}\n\n## Problem\n\n## Solution\n\n## Key Decisions\n\n## Decision Rationale\n\nFor each grilled choice that shapes this milestone:\n\n### <Decision title>\n\n- **Choice:**\n- **Why we chose it:**\n- **Pros:**\n- **Cons:**\n- **Expected outcome:**\n- **Diagram:**\n\n```mermaid\nflowchart TD\n  placeholder[Replace with the choice-space diagram from grilling]\n```\n\n## Out of Scope\n\n## Validation\n\n## Completion Criteria\n"""


class W2CError(Exception):
    """User-facing CLI error."""


@dataclass
class Milestone:
    mid: str
    title: str
    status: str
    emoji: str
    depends: str = "—"


@dataclass
class Task:
    mid: str
    sid: str
    tid: str
    title: str
    done: bool
    plan_path: Path
    verify: str = ""
    openspec_id: str = ""
    dropped: bool = False


@dataclass
class Slice:
    """One slice checkbox. Iteration yields sid, done, title for older callers."""

    sid: str
    done: bool
    title: str
    dropped: bool = False

    def __iter__(self):
        yield self.sid
        yield self.done
        yield self.title

    def __getitem__(self, index: int):
        return (self.sid, self.done, self.title)[index]


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


class Report:
    def __init__(self) -> None:
        self.checks: list[Check] = []

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append(Check(name, status, detail))

    def failed(self) -> bool:
        return any(c.status == "FAIL" for c in self.checks)

    def print(self) -> None:
        width = max((len(c.name) for c in self.checks), default=8)
        for c in self.checks:
            extra = f"  {c.detail}" if c.detail else ""
            print(f"{c.status:<4} {c.name:<{width}}{extra}")
        print("FAIL" if self.failed() else "PASS")


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def events_path(root: Path) -> Path:
    return w2c_dir(root) / "runtime" / "events.jsonl"


def iso_ts() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def append_event(
    root: Path,
    *,
    skill: str,
    stage: str,
    event: str,
    milestone: str | None = None,
    slice_id: str | None = None,
    task_id: str | None = None,
    detail: str = "",
) -> dict:
    """Append one JSONL event under .w2c/runtime/ (gitignored, local-only)."""
    path = events_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": iso_ts(),
        "skill": skill,
        "stage": stage,
        "event": event,
        "milestone": milestone,
        "slice": slice_id,
        "task": task_id,
        "detail": detail or "",
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def read_events(root: Path) -> list[dict]:
    path = events_path(root)
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def cmd_event(
    root: Path,
    skill: str,
    stage: str,
    event: str,
    milestone: str | None,
    slice_id: str | None,
    task_id: str | None,
    detail: str,
) -> int:
    rec = append_event(
        root,
        skill=skill,
        stage=stage,
        event=event,
        milestone=milestone,
        slice_id=slice_id,
        task_id=task_id,
        detail=detail,
    )
    print(json.dumps(rec, ensure_ascii=False))
    return 0


def cmd_events(root: Path, tail: int, skill: str | None) -> int:
    rows = read_events(root)
    if skill:
        rows = [r for r in rows if r.get("skill") == skill]
    if tail > 0:
        rows = rows[-tail:]
    for rec in rows:
        print(json.dumps(rec, ensure_ascii=False))
    if not rows:
        print("(no events)")
    return 0


def format_datetime(dt: datetime | None = None) -> str:
    dt = dt or datetime.now().astimezone()
    offset = dt.utcoffset()
    hours = int((offset.total_seconds() if offset else 0) // 3600)
    sign = "+" if hours >= 0 else "-"
    return dt.strftime("%b %d, %Y %I:%M %p") + f" (GMT {sign}{abs(hours)})"


def find_repo_root(start: Path | None = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / ".w2c").is_dir() or (p / ".git").exists():
            return p
    return cur


def w2c_dir(root: Path) -> Path:
    return root / ".w2c"


def _first_existing_dir(candidates: list[Path]) -> Path | None:
    for cand in candidates:
        if cand.is_dir():
            return cand
    return None


def _package_asset(name: str) -> Path | None:
    here = Path(__file__).resolve().parent
    return _first_existing_dir([here / "assets" / name])


def _checkout_or_data_asset(name: str) -> Path | None:
    here = Path(__file__).resolve()
    cands: list[Path] = []
    if len(here.parents) >= 2:
        cands.append(here.parents[2] / name)
    cands.append(w2c_local.data_home() / name)
    return _first_existing_dir(cands)


def templates_dir(script_file: Path | None = None) -> Path:
    return w2c_local.data_home() / "templates"


def skills_dir() -> Path | None:
    return _package_asset("skills") or _checkout_or_data_asset("skills")


def load_template(name: str, embedded: str) -> str:
    tdir = templates_dir()
    if tdir is not None:
        path = tdir / name
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return embedded


def parse_milestones(text: str) -> list[Milestone]:
    out: list[Milestone] = []
    for line in text.splitlines():
        m = MILESTONE_LINE_RE.match(line.strip() if False else line)
        if not m:
            continue
        emoji = m.group("emoji")
        status = EMOJI_STATUS.get(emoji) or EMOJI_STATUS.get(emoji.replace("\ufe0f", ""))
        if not status:
            continue
        dep_m = re.search(r"`depends:\[(.+?)\]`", line)
        out.append(
            Milestone(
                mid=m.group("id"),
                title=m.group("title").strip(),
                status=status,
                emoji=STATUS_EMOJI[status],
                depends=dep_m.group(1) if dep_m else "\u2014",
            )
        )
    return out


def parse_state_field(text: str, label: str) -> str:
    m = re.search(rf"^\*\*{re.escape(label)}:\*\*\s*(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def parse_active_id(value: str) -> str | None:
    if not value or value.lower() in {"none", "—", "-"}:
        return None
    m = re.match(r"(M\d+|S\d+)", value.strip())
    return m.group(1) if m else None


def set_state_field(text: str, label: str, value: str) -> str:
    pat = rf"^(\*\*{re.escape(label)}:\*\*)\s*.*$", 
    repl = rf"\1 {value}"
    new, n = re.subn(pat, repl, text, count=1, flags=re.M)
    if n == 0:
        raise W2CError(f"STATE.md missing field {label}")
    return new


def replace_section(text: str, heading: str, body: str) -> str:
    """Replace markdown section body until the next ## heading or EOF."""
    pat = re.compile(
        rf"(## {re.escape(heading)}\n)(.*?)(?=\n## |\Z)",
        re.S,
    )
    if not pat.search(text):
        if not text.endswith("\n"):
            text += "\n"
        return text + f"\n## {heading}\n{body}"
    return pat.sub(lambda m: m.group(1) + body, text, count=1)


def list_plan_dirs(root: Path) -> list[Path]:
    plans = w2c_dir(root) / "plans"
    if not plans.is_dir():
        return []
    return sorted(p for p in plans.iterdir() if p.is_dir() and re.match(r"M\d+-", p.name))


def plan_dir_for(root: Path, mid: str) -> Path | None:
    plans = w2c_dir(root) / "plans"
    if not plans.is_dir():
        return None
    matches = sorted(plans.glob(f"{mid}-*"))
    dirs = [p for p in matches if p.is_dir()]
    return dirs[0] if dirs else None


def report_present(path: Path) -> bool:
    return path.is_file() and bool(read_text(path).strip())


def require_report(path: Path, label: str) -> None:
    if not report_present(path):
        raise W2CError(f"missing report {label}")


def task_summary_path(plan_dir: Path, sid: str, tid: str) -> Path:
    return plan_dir / f"{sid}-{tid}-SUMMARY.md"


def slice_uat_path(plan_dir: Path, sid: str) -> Path:
    return plan_dir / f"{sid}-UAT.md"


def slice_summary_path(plan_dir: Path, sid: str) -> Path:
    return plan_dir / f"{sid}-SUMMARY.md"


def milestone_validation_path(plan_dir: Path, mid: str) -> Path:
    return plan_dir / f"{mid}-VALIDATION.md"


def milestone_summary_path(plan_dir: Path, mid: str) -> Path:
    return plan_dir / f"{mid}-SUMMARY.md"


def milestone_manual_test_path(plan_dir: Path, mid: str) -> Path:
    return plan_dir / f"{mid}-MANUAL-TEST.md"


def slice_plan_path(root: Path, mid: str, sid: str) -> Path | None:
    d = plan_dir_for(root, mid)
    if d is None:
        return None
    p = d / f"{mid}-{sid}-PLAN.md"
    return p if p.is_file() else None


def parse_slices(text: str) -> list[Slice]:
    """Return slice checkboxes. A ``d`` mark is dropped, not done and not open."""
    out: list[Slice] = []
    for line in text.splitlines():
        m = re.match(r"^- \[([ xXdD])\] \*\*(S\d+):\s*(.+?)\*\*", line)
        if m:
            mark = m.group(1).lower()
            out.append(
                Slice(
                    sid=m.group(2),
                    done=mark == "x",
                    title=m.group(3).strip(),
                    dropped=mark == "d",
                )
            )
    return out


def parse_tasks(plan_path: Path, mid: str, sid: str) -> list[Task]:
    text = read_text(plan_path)
    tasks: list[Task] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = TASK_LINE_RE.match(line)
        if not m:
            continue
        mark = m.group(1).lower()
        done = mark == "x"
        dropped = mark == "d"
        rest = line.split("**" + m.group(2) + "**:", 1)
        title = rest[1].strip() if len(rest) == 2 else line
        title = re.sub(r"_\([^)]*\)_\s*$", "", title).strip().rstrip(".")
        verify = ""
        for follow in lines[i + 1 : i + 8]:
            vm = re.match(r"^\s+- Verify:\s*(.*)$", follow)
            if vm:
                verify = vm.group(1).strip()
                break
            if follow.startswith("- ["):
                break
        tasks.append(
            Task(
                mid=mid,
                sid=sid,
                tid=m.group(2),
                title=title or m.group(2),
                done=done,
                plan_path=plan_path,
                verify=verify,
                dropped=dropped,
            )
        )
    return tasks


def all_tasks(root: Path, milestones: list[Milestone] | None = None) -> list[Task]:
    ms = milestones if milestones is not None else parse_milestones(read_text(w2c_dir(root) / "ROADMAP.md"))
    found: list[Task] = []
    for mil in ms:
        d = plan_dir_for(root, mil.mid)
        if d is None:
            continue
        road = read_text(d / f"{mil.mid}-ROADMAP.md")
        slices = parse_slices(road)
        if not slices:
            for p in sorted(d.glob(f"{mil.mid}-S*-PLAN.md")):
                sm = re.search(r"-(S\d+)-PLAN\.md$", p.name)
                if sm:
                    slices.append((sm.group(1), False, ""))
        for sid, _done, _title in slices:
            found.extend(openspec_ledger.tasks_in_slice(root, mil.mid, sid, d))
    return found


def filter_tasks(
    tasks: Iterable[Task],
    milestone: str | None = None,
    slice_id: str | None = None,
    task_id: str | None = None,
) -> list[Task]:
    out = list(tasks)
    if milestone:
        out = [t for t in out if t.mid == milestone]
    if slice_id:
        out = [t for t in out if t.sid == slice_id]
    if task_id:
        out = [t for t in out if t.tid == task_id or t.openspec_id == task_id]
    return out


def next_open_task(
    root: Path,
    milestone: str | None = None,
    slice_id: str | None = None,
    task_id: str | None = None,
) -> Task | None:
    locked = amend_lock_mid(root)
    tasks = filter_tasks(all_tasks(root), milestone, slice_id, task_id)
    for t in tasks:
        if not task_is_open(t):
            continue
        if locked and t.mid == locked:
            continue
        return t
    return None


def task_is_open(task: Task) -> bool:
    return not task.done and not task.dropped


def amend_lock_mid(root: Path) -> str:
    raw = w2c_local.load_repo_config(root).get("amend_lock") or ""
    return str(raw).strip()


def refuse_if_amend_locked(root: Path, mid: str) -> None:
    locked = amend_lock_mid(root)
    if locked and locked == mid:
        raise W2CError(f"AMEND_LOCK {mid}")


def ledger_has_dropped(root: Path, milestones: list[Milestone]) -> bool:
    for mil in milestones:
        d = plan_dir_for(root, mil.mid)
        if d is None:
            continue
        road = d / f"{mil.mid}-ROADMAP.md"
        if road.is_file() and any(item.dropped for item in parse_slices(read_text(road))):
            return True
    return any(task.dropped for task in all_tasks(root, milestones))


def collected_ids_from_plans(root: Path) -> set[str]:
    ids: set[str] = set()
    for d in list_plan_dirs(root):
        m = re.match(r"(M\d+)-", d.name)
        if m:
            ids.add(m.group(1))
    return ids


def next_milestone_id(root: Path) -> str:
    nums: list[int] = []
    for mil in parse_milestones(read_text(w2c_dir(root) / "ROADMAP.md")):
        nums.append(int(mil.mid[1:]))
    for mid in collected_ids_from_plans(root):
        nums.append(int(mid[1:]))
    n = (max(nums) + 1) if nums else 1
    return f"M{n:03d}"


def parse_decisions(text: str) -> list[str]:
    return DECISION_ROW_RE.findall(text)


def next_decision_id(text: str) -> str:
    ids = parse_decisions(text)
    if not ids:
        return "D001"
    n = max(int(i[1:]) for i in ids) + 1
    return f"D{n:03d}"


def latest_context(root: Path) -> tuple[int, int, Path] | None:
    ctx = w2c_dir(root) / "contexts"
    if not ctx.is_dir():
        return None
    best: tuple[int, int, Path] | None = None
    for p in ctx.glob("CONTEXTv*.md"):
        m = CONTEXT_FILE_RE.match(p.name)
        if not m:
            continue
        ver = (int(m.group(1)), int(m.group(2)), p)
        if best is None or ver[:2] > best[:2]:
            best = ver
    return best


def context_frontmatter(version: str, slug: str = "") -> str:
    return (
        "---\n"
        f"version: {version}\n"
        f"datetime: {format_datetime()}\n"
        f"slug: {slug}\n"
        "---\n\n"
    )


def strip_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, parts[2].lstrip("\n")


def rebuild_ledger(root: Path, state_overrides: dict[str, str] | None = None) -> None:
    """Rebuild STATE registry, QUEUE, and ROADMAP-derived pointers."""
    wdir = w2c_dir(root)
    milestones = parse_milestones(read_text(wdir / "ROADMAP.md"))
    state = read_text(wdir / "STATE.md") or STATE_TEMPLATE
    overrides = state_overrides or {}

    active_m = overrides.get("active_milestone")
    if active_m is None:
        active_m = parse_state_field(state, "Active Milestone")
    active_s = overrides.get("active_slice")
    if active_s is None:
        active_s = parse_state_field(state, "Active Slice")
    phase = overrides.get("phase") or parse_state_field(state, "Phase") or "idle"
    req = parse_state_field(state, "Requirements Status") or (
        "0 active · 0 validated · 0 deferred · 0 out of scope"
    )
    blockers = "- None\n"
    bm = re.search(r"## Blockers\n(.*?)(?=\n## |\Z)", state, re.S)
    if bm and bm.group(1).strip():
        blockers = bm.group(1)
        if not blockers.endswith("\n"):
            blockers += "\n"

    nxt = next_open_task(root)
    if nxt:
        next_action = f"Execute {nxt.mid} {nxt.sid} {nxt.tid}: {nxt.title}"
    elif any(m.status not in {"DONE", "STOP"} for m in milestones):
        next_action = "Continue planned work (no open tasks in current filters)."
    else:
        next_action = "Plan work with work-to-chores."

    registry_lines = []
    for m in milestones:
        registry_lines.append(f"- {m.emoji} **{m.mid}:** {m.title}")
    registry = ("\n".join(registry_lines) + "\n") if registry_lines else "\n"

    dec_text = read_text(wdir / "DECISIONS.md")
    recent_lines = []
    rows = re.findall(
        r"^\| (D\d+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|",
        dec_text,
        re.M,
    )
    for row in rows[-5:]:
        did, when, scope, decision, choice = (x.strip() for x in row[:5])
        recent_lines.append(f"- {did} ({when} {scope}): {decision} -> {choice}")
    recent = ("\n".join(recent_lines) + "\n") if recent_lines else "\n"

    active_m_display = active_m if active_m else "None"
    active_s_display = active_s if active_s else "None"

    new_state = (
        "# State\n\n"
        f"**Active Milestone:** {active_m_display}\n"
        f"**Active Slice:** {active_s_display}\n"
        f"**Phase:** {phase}\n"
        f"**Requirements Status:** {req}\n\n"
        f"## Milestone Registry\n{registry}\n"
        f"## Recent Decisions\n{recent}\n"
        f"## Blockers\n{blockers}"
        f"{chr(10) if not blockers.endswith(chr(10)) else ''}"
        f"## Next Action\n{next_action}\n"
    )
    atomic_write(wdir / "STATE.md", new_state)

    q_lines = ["# Queue\n"]
    for m in milestones:
        if m.status != "DONE":
            q_lines.append(f"- {m.emoji} **{m.mid}: {m.title}**\n")
    atomic_write(wdir / "QUEUE.md", "".join(q_lines) if len(q_lines) > 1 else "# Queue\n")


def set_task_checked(text: str, tid: str, checked: bool = True) -> str:
    mark = "x" if checked else " "
    new, n = re.subn(
        rf"^- \[[ xX]\] \*\*({re.escape(tid)})\*\*",
        lambda m: f"- [{mark}] **{m.group(1)}**",
        text,
        count=1,
        flags=re.M,
    )
    if n != 1:
        raise W2CError(f"task {tid} not found in plan")
    return new


def set_slice_checked(text: str, sid: str, checked: bool = True) -> str:
    mark = "x" if checked else " "
    new, n = re.subn(
        rf"^- \[[ xX]\] \*\*({re.escape(sid)}):",
        lambda m: f"- [{mark}] **{m.group(1)}:",
        text,
        count=1,
        flags=re.M,
    )
    return new if n else text


def set_task_mark(text: str, tid: str, mark: str) -> str:
    if mark not in {" ", "x", "d"}:
        raise W2CError(f"invalid task mark {mark!r}")
    new, n = re.subn(
        rf"^- \[[ xXdD]\] \*\*({re.escape(tid)})\*\*",
        lambda m: f"- [{mark}] **{m.group(1)}**",
        text,
        count=1,
        flags=re.M,
    )
    if n != 1:
        raise W2CError(f"task {tid} not found in plan")
    return new


def set_slice_mark(text: str, sid: str, mark: str) -> str:
    if mark not in {" ", "x", "d"}:
        raise W2CError(f"invalid slice mark {mark!r}")
    new, n = re.subn(
        rf"^- \[[ xXdD]\] \*\*({re.escape(sid)}):",
        lambda m: f"- [{mark}] **{m.group(1)}:",
        text,
        count=1,
        flags=re.M,
    )
    if n != 1:
        raise W2CError(f"slice {sid} not found")
    return new


def set_milestone_status_in_roadmap(text: str, mid: str, status: str) -> str:
    emoji = STATUS_EMOJI[status]
    new, n = re.subn(
        r"^- +(?:" + _EMOJI_ALT + r")\s+\*\*(" + re.escape(mid) + r"):",
        lambda m: f"- {emoji} **{m.group(1)}:",
        text,
        count=1,
        flags=re.M,
    )
    if n != 1:
        raise W2CError(f"milestone {mid} not found in ROADMAP.md")
    return new




def resolve_git_delivery(
    root: Path,
    git_delivery: str | None,
    *,
    allow_prompt: bool = True,
) -> str:
    try:
        return w2c_gd.resolve_git_delivery(root, git_delivery, allow_prompt=allow_prompt)
    except w2c_local.GitDeliveryError as e:
        raise W2CError(str(e)) from e


def cmd_init(
    root: Path,
    track: bool | None = None,
    git_delivery: str | None = None,
    planning: str | None = None,
) -> int:
    wdir = w2c_dir(root)
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "plans").mkdir(exist_ok=True)
    (wdir / "contexts").mkdir(exist_ok=True)
    (wdir / "runtime").mkdir(exist_ok=True)
    files = {
        "DECISIONS.md": load_template("DECISIONS.md", DECISIONS_HEADER),
        "ROADMAP.md": load_template("ROADMAP.md", ROADMAP_TEMPLATE),
        "STATE.md": load_template("STATE.md", STATE_TEMPLATE),
        "QUEUE.md": load_template("QUEUE.md", QUEUE_TEMPLATE),
    }
    created = []
    for name, body in files.items():
        path = wdir / name
        if not path.exists():
            atomic_write(path, body if body.endswith("\n") else body + "\n")
            created.append(name)
    ctx0 = wdir / "contexts" / "CONTEXTv1.0.md"
    if not ctx0.exists() and latest_context(root) is None:
        tpl = load_template("CONTEXTv1.0.md", context_frontmatter("1.0") + CONTEXT_BODY)
        tpl = tpl.replace("PLACEHOLDER", format_datetime())
        if "datetime:" in tpl and "PLACEHOLDER" not in tpl:
            pass
        atomic_write(ctx0, tpl if tpl.endswith("\n") else tpl + "\n")
        created.append("contexts/CONTEXTv1.0.md")
    rebuild_ledger(root)
    gd = resolve_git_delivery(root, git_delivery)
    creating = not w2c_local.repo_config_path(root).is_file()
    if planning is None:
        chosen_planning = w2c_local.PLANNING_OPENSPEC if creating else None
    else:
        chosen_planning = w2c_local.normalize_planning(planning)
    if creating:
        w2c_local.write_repo_config(
            root,
            track=bool(track),
            git_delivery=gd,
            planning=chosen_planning or w2c_local.PLANNING_OPENSPEC,
        )
    else:
        kwargs: dict = {"git_delivery": gd}
        if track is True:
            kwargs["track"] = True
        if chosen_planning is not None:
            kwargs["planning"] = chosen_planning
        w2c_local.write_repo_config(root, **kwargs)
    track_flag = True if track is True else w2c_local.is_track_enabled(root)
    w2c_local.ensure_gitignore(root, track=track_flag)
    created.extend(write_copilot_instructions(root, skills_dir()))
    w2c_local.register_project(root)
    append_event(
        root,
        skill="w2c",
        stage="init",
        event="complete",
        detail=", ".join(created) or "already present",
    )
    print("initialized .w2c/" + (f" ({', '.join(created)})" if created else " (already present)"))
    if w2c_local.load_repo_config(root).get("planning") == w2c_local.PLANNING_OPENSPEC:
        for token in w2c_openspec.check(root)["needs"]:
            print(token)
    return 0


def cmd_status(root: Path) -> int:
    path = w2c_dir(root) / "STATE.md"
    if not path.exists():
        raise W2CError("STATE.md missing — run `w2c init`")
    sys.stdout.write(read_text(path))
    if not read_text(path).endswith("\n"):
        print()
    return 0


def task_to_dict(t: Task) -> dict:
    return {
        "milestone_id": t.mid,
        "slice_id": t.sid,
        "task_id": t.tid,
        "title": t.title,
        "plan_path": str(t.plan_path),
        "verify": t.verify,
        "openspec_id": t.openspec_id,
    }


def cmd_next(
    root: Path,
    milestone: str | None,
    slice_id: str | None,
    task_id: str | None,
) -> int:
    locked = amend_lock_mid(root)
    if milestone and locked and milestone == locked:
        print(f"AMEND_LOCK {locked}")
        return 1
    t = next_open_task(root, milestone, slice_id, task_id)
    if t is None:
        print("NEXT none")
        print(json.dumps({"task": None}))
        return 0
    print(f"NEXT {t.mid} {t.sid} {t.tid} — {t.title}")
    print(json.dumps({"task": task_to_dict(t)}, indent=2))
    return 0


def cmd_complete(root: Path, mid: str, sid: str, tid: str) -> int:
    refuse_if_amend_locked(root, mid)
    d = plan_dir_for(root, mid)
    if d is None:
        raise W2CError(f"plan folder not found for {mid}")
    mroad = d / f"{mid}-ROADMAP.md"
    mtext = read_text(mroad) if mroad.is_file() else ""
    if openspec_ledger.planning_mode(mtext) == w2c_local.PLANNING_OPENSPEC:
        tasks = openspec_ledger.tasks_in_slice(root, mid, sid, d)
        match = [t for t in tasks if t.tid == tid or t.openspec_id == tid]
        if not match:
            raise W2CError(f"unknown task {mid} {sid} {tid}")
        task = match[0]
        tid = task.tid
        require_report(task_summary_path(d, sid, tid), f"{sid}-{tid}-SUMMARY.md")
        if task.done:
            raise W2CError(f"{tid} is already complete")
        if task.dropped:
            raise W2CError(f"{tid} is dropped")
        path = task.plan_path
        atomic_write(
            path,
            openspec_ledger.set_task_checked(read_text(path), task.openspec_id, True),
        )
    else:
        path = slice_plan_path(root, mid, sid)
        if path is None:
            raise W2CError(f"slice plan not found for {mid} {sid}")
        require_report(task_summary_path(d, sid, tid), f"{sid}-{tid}-SUMMARY.md")
        tasks = parse_tasks(path, mid, sid)
        match = [t for t in tasks if t.tid == tid]
        if not match:
            raise W2CError(f"unknown task {mid} {sid} {tid}")
        if match[0].done:
            raise W2CError(f"{tid} is already complete")
        if match[0].dropped:
            raise W2CError(f"{tid} is dropped")
        atomic_write(path, set_task_checked(read_text(path), tid, True))

    remaining = [
        t for t in openspec_ledger.tasks_in_slice(root, mid, sid, d) if task_is_open(t)
    ]
    road_path = w2c_dir(root) / "ROADMAP.md"
    mils = parse_milestones(read_text(road_path))
    mil = next((m for m in mils if m.mid == mid), None)
    if mil and mil.status in {"PLANNING", "TODO", "PAUSED"}:
        atomic_write(
            road_path, set_milestone_status_in_roadmap(read_text(road_path), mid, "INPROGRESS")
        )
    nxt = next_open_task(root, milestone=mid)
    overrides = {
        "active_milestone": f"{mid}: {mil.title if mil else mid}",
        "active_slice": sid if not remaining else (nxt.sid if nxt else sid),
        "phase": "executing",
    }
    rebuild_ledger(root, overrides)
    append_event(
        root,
        skill="do-chores",
        stage="complete",
        event="complete",
        milestone=mid,
        slice_id=sid,
        task_id=tid,
        detail=f"complete {mid} {sid} {tid}",
    )
    print(f"complete {mid} {sid} {tid}")
    if remaining:
        print(f"OPEN_IN_SLICE {len(remaining)}")
    elif report_present(slice_uat_path(d, sid)) and report_present(slice_summary_path(d, sid)):
        print(f"NEED_SLICE_COMPLETE {sid}")
    else:
        print(f"NEED_SLICE_REPORTS {sid}")
    return 0


def cmd_slice_complete(root: Path, mid: str, sid: str) -> int:
    refuse_if_amend_locked(root, mid)
    d = plan_dir_for(root, mid)
    if d is None:
        raise W2CError(f"plan folder not found for {mid}")
    path = slice_plan_path(root, mid, sid)
    if path is None:
        raise W2CError(f"slice plan not found for {mid} {sid}")
    road_now = d / f"{mid}-ROADMAP.md"
    current = parse_slices(read_text(road_now)) if road_now.is_file() else []
    sl = next((item for item in current if item.sid == sid), None)
    if sl is not None and sl.dropped:
        raise W2CError(f"{sid} is dropped")
    tasks = openspec_ledger.tasks_in_slice(root, mid, sid, d)
    if not tasks:
        raise W2CError(f"no tasks in {mid} {sid}")
    open_tasks = [t.tid for t in tasks if task_is_open(t)]
    if open_tasks:
        raise W2CError(f"open tasks remain in {mid} {sid}: {', '.join(open_tasks)}")
    if not any(t.done for t in tasks):
        raise W2CError(f"{sid} has no finished task; use drop-slice")
    for t in tasks:
        if t.done:
            require_report(task_summary_path(d, sid, t.tid), f"{sid}-{t.tid}-SUMMARY.md")
    require_report(slice_uat_path(d, sid), f"{sid}-UAT.md")
    require_report(slice_summary_path(d, sid), f"{sid}-SUMMARY.md")
    summary = read_text(slice_summary_path(d, sid))
    unnamed = [
        t.tid
        for t in tasks
        if t.dropped and re.search(rf"\b{re.escape(t.tid)}\b", summary) is None
    ]
    if unnamed:
        raise W2CError(f"slice summary must name dropped tasks: {', '.join(unnamed)}")
    mroad_path = d / f"{mid}-ROADMAP.md"
    if not mroad_path.is_file():
        raise W2CError(f"missing {mid}-ROADMAP.md")
    atomic_write(mroad_path, set_slice_checked(read_text(mroad_path), sid, True))
    slices = parse_slices(read_text(mroad_path))
    all_slices_done = bool(slices) and all(item.done or item.dropped for item in slices)
    road_path = w2c_dir(root) / "ROADMAP.md"
    mils = parse_milestones(read_text(road_path))
    mil = next((m for m in mils if m.mid == mid), None)
    nxt = next_open_task(root, milestone=mid)
    overrides = {
        "active_milestone": f"{mid}: {mil.title if mil else mid}",
        "active_slice": nxt.sid if nxt else sid,
        "phase": "executing",
    }
    rebuild_ledger(root, overrides)
    append_event(
        root,
        skill="do-chores",
        stage="slice-complete",
        event="complete",
        milestone=mid,
        slice_id=sid,
        detail=f"slice-complete {mid} {sid}",
    )
    print(f"slice-complete {mid} {sid}")
    if not all_slices_done:
        print(f"OPEN_SLICES {sum(1 for item in slices if not item.done and not item.dropped)}")
    elif report_present(milestone_validation_path(d, mid)) and report_present(
        milestone_summary_path(d, mid)
    ):
        print(f"NEED_MILESTONE_COMPLETE {mid}")
    else:
        print(f"NEED_MILESTONE_REPORTS {mid}")
    return 0


def cmd_set(
    root: Path,
    active_milestone: str | None,
    active_slice: str | None,
    phase: str | None,
) -> int:
    overrides: dict[str, str] = {}
    if active_milestone is not None:
        mils = parse_milestones(read_text(w2c_dir(root) / "ROADMAP.md"))
        mil = next((m for m in mils if m.mid == active_milestone or m.mid == parse_active_id(active_milestone or "")), None)
        mid = parse_active_id(active_milestone) or active_milestone
        title = mil.title if mil else active_milestone
        overrides["active_milestone"] = f"{mid}: {title}" if mil else active_milestone
    if active_slice is not None:
        overrides["active_slice"] = active_slice
    if phase is not None:
        overrides["phase"] = phase
    rebuild_ledger(root, overrides)
    print("updated STATE.md")
    return 0


def cmd_milestone_status(
    root: Path, mid: str, status: str, archive_declined: bool = False
) -> int:
    status = status.upper()
    if status not in STATUS_EMOJI:
        raise W2CError(f"invalid status {status}; use {', '.join(VALID_STATUSES)}")
    refuse_if_amend_locked(root, mid)
    if status == "DONE":
        d = plan_dir_for(root, mid)
        if d is None:
            raise W2CError(f"plan folder not found for {mid}")
        mroad_path = d / f"{mid}-ROADMAP.md"
        slices = parse_slices(read_text(mroad_path)) if mroad_path.is_file() else []
        if not slices:
            on_disk = sorted(p.name for p in d.glob(f"{mid}-S*-PLAN.md"))
            hint = (
                f" (found {len(on_disk)} slice plan file(s) on disk: {', '.join(on_disk)}; "
                f"{mid}-ROADMAP.md '## Slices' must list them as literal "
                '"- [ ] **S##: <title>**" lines -- a table or other format parses as zero slices)'
                if on_disk
                else ""
            )
            raise W2CError(f"no slices found in {mid}-ROADMAP.md{hint}")
        open_sids = [item.sid for item in slices if not item.done and not item.dropped]
        if open_sids:
            raise W2CError(f"slices still open in {mid}: {', '.join(open_sids)}")
        require_report(milestone_validation_path(d, mid), f"{mid}-VALIDATION.md")
        require_report(milestone_summary_path(d, mid), f"{mid}-SUMMARY.md")
        openspec_ledger.require_archive_for_done(root, mid, d, archive_declined)
    road = w2c_dir(root) / "ROADMAP.md"
    atomic_write(road, set_milestone_status_in_roadmap(read_text(road), mid, status))
    mils = parse_milestones(read_text(road))
    mil = next((m for m in mils if m.mid == mid), None)
    overrides = {}
    if mil:
        overrides["active_milestone"] = f"{mil.mid}: {mil.title}"
        if status == "INPROGRESS":
            overrides["phase"] = "executing"
        elif status == "DONE":
            overrides["phase"] = "idle"
    rebuild_ledger(root, overrides or None)
    append_event(
        root,
        skill="w2c",
        stage="plan",
        event="status",
        milestone=mid,
        detail=f"{mid} -> {status}",
    )
    print(f"{mid} -> {status} {STATUS_EMOJI[status]}")
    return 0


def cmd_next_milestone_id(root: Path) -> int:
    print(next_milestone_id(root))
    return 0


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "milestone"


def load_checkout_template(rel: str) -> str:
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    asset = _package_asset("templates")
    if asset is not None:
        candidates.append(asset / rel)
    if len(here.parents) >= 3:
        candidates.append(here.parents[2] / "templates" / rel)
    candidates.append(w2c_local.data_home() / "templates" / rel)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise W2CError(f"missing template templates/{rel}")


def cmd_spec_archive(root: Path, mid: str) -> int:
    plan_dir = plan_dir_for(root, mid)
    if plan_dir is None:
        raise W2CError(f"plan folder not found for {mid}")
    path = plan_dir / f"{mid}-ROADMAP.md"
    if not path.is_file():
        raise W2CError(f"missing {mid}-ROADMAP.md")
    text = read_text(path)
    if openspec_ledger.planning_mode(text) != w2c_local.PLANNING_OPENSPEC:
        raise W2CError(f"{mid} is not an OpenSpec milestone")
    name = openspec_ledger.change_name(text)
    if not name:
        raise W2CError(f"{mid} has no OpenSpec change name")
    if openspec_ledger.is_archived(text):
        raise W2CError(f"{mid} is already archived")
    try:
        data = w2c_openspec.archive(root, name)
    except w2c_openspec.OpenSpecError as exc:
        raise W2CError(str(exc)) from exc
    info = data.get("archive") if isinstance(data, dict) else None
    archived_as = str(info.get("archivedAs") or "") if isinstance(info, dict) else ""
    raw_path = str(info.get("path") or "") if isinstance(info, dict) else ""
    recorded = archived_as or raw_path
    if raw_path:
        try:
            recorded = str(Path(raw_path).resolve().relative_to(root.resolve()))
        except ValueError:
            recorded = raw_path
    atomic_write(path, openspec_ledger.set_guardrail_field(text, "OpenSpec archive", recorded))
    print(f"archived {name} as {archived_as or recorded}")
    return 0


def cmd_openspec_check(root: Path) -> int:
    print(json.dumps(w2c_openspec.check(root), indent=2))
    return 0


def cmd_milestone_new(root: Path, slug: str, planning: str | None = None) -> int:
    slug = slugify(slug)
    if planning is None:
        mode = str(
            w2c_local.load_repo_config(root).get("planning") or w2c_local.PLANNING_CLASSIC
        )
    else:
        mode = w2c_local.normalize_planning(planning)
    mid = next_milestone_id(root)
    title = slug.replace("-", " ")
    if mode == w2c_local.PLANNING_OPENSPEC:
        try:
            created = w2c_openspec.new_change(root, slug, goal=title)
        except w2c_openspec.OpenSpecError as exc:
            raise W2CError(str(exc)) from exc
        change = created.get("change") if isinstance(created, dict) else None
        meta = str(change.get("metadataPath") or "") if isinstance(change, dict) else ""
        if not meta:
            raise W2CError("openspec new change did not return metadataPath")
        w2c_openspec.link_milestone(Path(meta), mid)
        roadmap_body = load_checkout_template("openspec/M-ROADMAP.md").format(
            mid=mid, title=title, slug=slug
        )
    else:
        roadmap_body = M_ROADMAP_STUB.format(mid=mid, title=title, slug=slug)
    d = w2c_dir(root) / "plans" / f"{mid}-{slug}"
    if d.exists():
        raise W2CError(f"already exists: {d}")
    d.mkdir(parents=True)
    atomic_write(d / f"{mid}-ROADMAP.md", roadmap_body if roadmap_body.endswith("\n") else roadmap_body + "\n")
    atomic_write(d / f"{mid}-CONTEXT.md", M_CONTEXT_STUB.format(mid=mid, title=title))
    road = w2c_dir(root) / "ROADMAP.md"
    text = read_text(road) or ROADMAP_TEMPLATE
    if not text.endswith("\n"):
        text += "\n"
    line = f"- {STATUS_EMOJI['PLANNING']} **{mid}: {title}** (`depends:[—]`)\n"
    if "## Milestones" in text:
        # append after the Milestones heading block
        if not text.endswith("\n"):
            text += "\n"
        text = text.rstrip() + "\n" + line
    else:
        text = text.rstrip() + "\n\n## Milestones\n" + line
    atomic_write(road, text if text.endswith("\n") else text + "\n")
    rebuild_ledger(
        root,
        {
            "active_milestone": f"{mid}: {title}",
            "active_slice": "None",
            "phase": "planning",
        },
    )
    append_event(
        root,
        skill="work-to-chores",
        stage="write",
        event="complete",
        milestone=mid,
        detail=f"created {d.relative_to(root)}",
    )
    print(f"created {d.relative_to(root)} ({mid})")
    return 0


def canonical_mid(raw: str) -> str:
    text = raw.strip().upper()
    if not re.fullmatch(r"M\d+", text):
        raise W2CError(f"invalid milestone id {raw}")
    return text


def roadmap_milestone_rows(text: str) -> tuple[list[str], list[tuple[int, str, Milestone]]]:
    """Return file lines and each milestone row as (line index, raw line, parsed)."""
    lines = text.splitlines(keepends=True)
    rows: list[tuple[int, str, Milestone]] = []
    for i, line in enumerate(lines):
        parsed = parse_milestones(line)
        if not parsed:
            continue
        if len(parsed) != 1:
            raise W2CError("milestone line parsed as more than one milestone")
        raw = line if line.endswith("\n") else line + "\n"
        rows.append((i, raw, parsed[0]))
    return lines, rows


def assert_reorder_allowed(before: list[Milestone], after: list[Milestone]) -> None:
    """Pending milestones may not take the place of an in-progress or done milestone.

    A milestone that already sits after an in-progress or done line may move
    among other lines in that same tail. PAUSED, STOP, and ERROR may be
    displaced, because they are no longer in progress.
    """
    before_ids = [m.mid for m in before]
    after_ids = [m.mid for m in after]
    if before_ids == after_ids:
        return
    if set(before_ids) != set(after_ids) or len(before_ids) != len(set(before_ids)):
        raise W2CError("reorder changed the milestone set")
    b_idx = {mid: i for i, mid in enumerate(before_ids)}
    a_idx = {mid: i for i, mid in enumerate(after_ids)}
    status_of = {m.mid: m.status for m in before}
    for mid, status in status_of.items():
        if status not in FROZEN_STATUSES:
            continue
        if a_idx[mid] != b_idx[mid]:
            raise W2CError(
                f"{mid} is {status}; a pending milestone cannot swap with it or take its place. "
                "Set it to PAUSED, STOP, or ERROR first."
            )
        for other in before_ids:
            if other == mid:
                continue
            if b_idx[other] > b_idx[mid] and a_idx[other] < a_idx[mid]:
                raise W2CError(
                    f"{other} cannot move ahead of {mid} while {mid} is {status}. "
                    "Set it to PAUSED, STOP, or ERROR first."
                )


def print_milestone_order(milestones: list[Milestone]) -> None:
    for m in milestones:
        print(f"{m.mid} {m.status} {m.title}")


def load_milestone_rows(root: Path) -> list[tuple[int, str, Milestone]]:
    text = read_text(w2c_dir(root) / "ROADMAP.md")
    if not text:
        raise W2CError("ROADMAP.md missing — run `w2c init`")
    _lines, rows = roadmap_milestone_rows(text)
    ids = [row[2].mid for row in rows]
    dupes = sorted({mid for mid in ids if ids.count(mid) > 1})
    if dupes:
        raise W2CError(f"duplicate milestone id {', '.join(dupes)}")
    return rows


def write_milestone_line_order(root: Path, ordered_raw: list[str], detail: str) -> list[Milestone]:
    road_path = w2c_dir(root) / "ROADMAP.md"
    text = read_text(road_path)
    if not text:
        raise W2CError("ROADMAP.md missing — run `w2c init`")
    lines, rows = roadmap_milestone_rows(text)
    if len(ordered_raw) != len(rows):
        raise W2CError("internal reorder size mismatch")
    before = [row[2] for row in rows]
    after: list[Milestone] = []
    normalized: list[str] = []
    for raw in ordered_raw:
        parsed = parse_milestones(raw)
        if len(parsed) != 1:
            raise W2CError("reorder produced a line that is not a milestone")
        after.append(parsed[0])
        normalized.append(raw if raw.endswith("\n") else raw + "\n")
    assert_reorder_allowed(before, after)
    for (index, _old, _mil), raw in zip(rows, normalized):
        lines[index] = raw
    new_text = "".join(lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
    atomic_write(road_path, new_text)
    rebuild_ledger(root)
    append_event(
        root,
        skill="work-to-chores",
        stage="reorder",
        event="complete",
        detail=detail,
    )
    return after


def cmd_milestone_order(root: Path, mids: list[str]) -> int:
    rows = load_milestone_rows(root)
    if not mids:
        print_milestone_order([row[2] for row in rows])
        return 0
    named = [canonical_mid(mid) for mid in mids]
    if len(named) != len(set(named)):
        raise W2CError("duplicate milestone id in order list")
    by_mid = {row[2].mid: row for row in rows}
    for mid in named:
        if mid not in by_mid:
            raise W2CError(f"unknown milestone {mid}")
        status = by_mid[mid][2].status
        if status in FROZEN_STATUSES:
            raise W2CError(
                f"{mid} is {status}; a pending milestone cannot take its place. "
                "Set it to PAUSED, STOP, or ERROR first."
            )
    named_set = set(named)
    positions = [i for i, row in enumerate(rows) if row[2].mid in named_set]
    raws = [row[1] for row in rows]
    for pos, mid in zip(positions, named):
        raws[pos] = by_mid[mid][1]
    after = write_milestone_line_order(root, raws, detail="order " + " ".join(named))
    print_milestone_order(after)
    return 0


def cmd_milestone_swap(root: Path, left: str, right: str) -> int:
    rows = load_milestone_rows(root)
    a = canonical_mid(left)
    b = canonical_mid(right)
    if a == b:
        raise W2CError("cannot swap a milestone with itself")
    by_mid = {row[2].mid: i for i, row in enumerate(rows)}
    for mid in (a, b):
        if mid not in by_mid:
            raise W2CError(f"unknown milestone {mid}")
    raws = [row[1] for row in rows]
    i, j = by_mid[a], by_mid[b]
    raws[i], raws[j] = raws[j], raws[i]
    after = write_milestone_line_order(root, raws, detail=f"swap {a} {b}")
    print_milestone_order(after)
    return 0


def cmd_milestone_move(root: Path, mid: str, before: str | None, after: str | None) -> int:
    if (before is None) == (after is None):
        raise W2CError("pass exactly one of --before or --after")
    rows = load_milestone_rows(root)
    src = canonical_mid(mid)
    dest = canonical_mid(before if before else after or "")
    if src == dest:
        raise W2CError("cannot move a milestone relative to itself")
    by_mid = {row[2].mid: i for i, row in enumerate(rows)}
    for item in (src, dest):
        if item not in by_mid:
            raise W2CError(f"unknown milestone {item}")
    raws = [row[1] for row in rows]
    src_raw = raws.pop(by_mid[src])
    dest_i = next(i for i, raw in enumerate(raws) if parse_milestones(raw)[0].mid == dest)
    insert_at = dest_i if before else dest_i + 1
    raws.insert(insert_at, src_raw)
    place = "before" if before else "after"
    ordered = write_milestone_line_order(root, raws, detail=f"move {src} {place} {dest}")
    print_milestone_order(ordered)
    return 0


def cmd_decide(
    root: Path,
    scope: str,
    decision: str,
    choice: str,
    rationale: str,
    revisable: str,
    made_by: str,
    when: str | None,
) -> int:
    path = w2c_dir(root) / "DECISIONS.md"
    text = read_text(path)
    if not text:
        text = DECISIONS_HEADER
    if "| # | When | Scope |" not in text:
        raise W2CError("DECISIONS.md missing table header")
    did = next_decision_id(text)
    when_s = when or datetime.now().astimezone().strftime("%Y-%m-%d")
    def cell(s: str) -> str:
        return s.replace("|", "\\|").strip()
    row = (
        f"| {did} | {cell(when_s)} | {cell(scope)} | {cell(decision)} | "
        f"{cell(choice)} | {cell(rationale)} | {cell(revisable)} | {cell(made_by)} |\n"
    )
    if not text.endswith("\n"):
        text += "\n"
    atomic_write(path, text + row)
    rebuild_ledger(root)
    append_event(
        root,
        skill="work-to-chores",
        stage="decide",
        event="complete",
        detail=f"{did} {scope}",
    )
    print(did)
    return 0


def cmd_context_new(root: Path, major: bool, minor: bool) -> int:
    if major == minor:
        raise W2CError("pass exactly one of --major or --minor")
    ctx_dir = w2c_dir(root) / "contexts"
    ctx_dir.mkdir(parents=True, exist_ok=True)
    latest = latest_context(root)
    if latest is None:
        x, y, prev_path = 1, 0, None
        body = CONTEXT_BODY
        slug = ""
    else:
        x, y, prev_path = latest
        meta, body = strip_frontmatter(read_text(prev_path))
        slug = meta.get("slug", "")
        if major:
            x, y = x + 1, 0
        else:
            y = y + 1
    version = f"{x}.{y}"
    dest = ctx_dir / f"CONTEXTv{version}.md"
    if dest.exists():
        raise W2CError(f"refusing to overwrite {dest.name}")
    atomic_write(dest, context_frontmatter(version, slug) + body)
    append_event(
        root,
        skill="work-to-chores",
        stage="write",
        event="complete",
        detail=str(dest.relative_to(root)),
    )
    print(dest.relative_to(root))
    return 0



def parse_table_under_heading(text: str, heading: str) -> dict[str, str]:
    """Parse | Field | Value | rows under a ## heading until the next ##."""
    m = re.search(rf"^## {re.escape(heading)}\s*$", text, re.M)
    if not m:
        return {}
    rest = text[m.end() :]
    next_h = re.search(r"^## ", rest, re.M)
    if next_h:
        rest = rest[: next_h.start()]
    fields: dict[str, str] = {}
    for line in rest.splitlines():
        mm = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*$", line)
        if not mm:
            continue
        key = mm.group(1).strip()
        val = mm.group(2).strip()
        if not key or key.lower() == "field" or set(key) <= {"-"}:
            continue
        fields[key] = val
    return fields


def parse_git_operation_fields(text: str) -> dict[str, str]:
    """Parse | Field | Value | rows under ## Git Operation Plan."""
    return parse_table_under_heading(text, "Git Operation Plan")


BASE_DIRT_POLICIES = frozenset({"clean-at-plan", "leave-untouched", "n/a-worktree"})


def base_dirt_paths_body(text: str) -> str | None:
    """Body of ### Base dirt paths inside ## Git Operation Plan, or None if absent."""
    plan = section_under_heading(text, "Git Operation Plan")
    if plan is None:
        return None
    match = re.search(r"^### Base dirt paths\s*$", plan, re.M)
    if not match:
        return None
    rest = plan[match.end() :]
    nxt = re.search(r"^### ", rest, re.M)
    if nxt:
        rest = rest[: nxt.start()]
    return rest


def validate_git_operation_plan(
    fields: dict[str, str],
    *,
    require_worktree_skill: bool = True,
    plan_text: str | None = None,
) -> list[str]:
    """Return human-readable problems; empty list means OK."""
    problems: list[str] = []
    if not fields:
        return ["missing ## Git Operation Plan section or table"]
    mode = fields.get("Isolation mode", "").strip().lower()
    local = fields.get("Local branch", "").strip()
    remote = fields.get("Remote branch", "").strip()
    if mode not in ("worktree", "branch"):
        problems.append(f"Isolation mode must be worktree|branch (got {mode!r})")
    if not local or local.upper() == "N/A":
        problems.append("Local branch empty or N/A")
    if not remote or remote.upper() == "N/A":
        problems.append("Remote branch empty or N/A")
    if local and remote and local != remote:
        problems.append(f"Local branch {local!r} != Remote branch {remote!r}")
    if require_worktree_skill and mode == "worktree":
        skill = fields.get("Worktree skill", "")
        if "using-git-worktrees" not in skill:
            problems.append("worktree mode requires Worktree skill mentioning using-git-worktrees")
    policy = fields.get("Base dirt policy", "").strip()
    if policy:
        if policy not in BASE_DIRT_POLICIES:
            problems.append(
                "Base dirt policy must be clean-at-plan|leave-untouched|n/a-worktree "
                f"(got {policy!r})"
            )
        elif mode == "worktree" and policy != "n/a-worktree":
            problems.append("worktree mode Base dirt policy must be n/a-worktree")
        elif mode == "branch" and policy == "n/a-worktree":
            problems.append("branch mode Base dirt policy must not be n/a-worktree")
        elif policy == "leave-untouched":
            body = None if plan_text is None else base_dirt_paths_body(plan_text)
            if body is None or not body.strip():
                problems.append(
                    "leave-untouched requires a non-empty ### Base dirt paths subsection"
                )
    return problems


_PROHIBITION_RE = re.compile(r"\b(do not|don't|never|must not)\b", re.I)


def section_under_heading(text: str, heading: str) -> str | None:
    m = re.search(rf"^## {re.escape(heading)}\s*$", text, re.M)
    if not m:
        return None
    rest = text[m.end() :]
    next_h = re.search(r"^## ", rest, re.M)
    if next_h:
        rest = rest[: next_h.start()]
    return rest


def validate_commit_pr_conventions(text: str) -> list[str]:
    """Return problems; empty list means section is present with Co-authored-by, deny-list, and do-not-mention rules."""
    body = section_under_heading(text, "Commit and PR conventions")
    if body is None:
        return ["missing ## Commit and PR conventions section"]
    if not body.strip():
        return ["empty ## Commit and PR conventions section"]
    problems: list[str] = []
    lower = body.lower()
    if "co-authored-by" not in lower:
        problems.append("Commit and PR conventions must mention Co-authored-by")
    elif not _PROHIBITION_RE.search(body):
        problems.append("Commit and PR conventions must forbid Co-authored-by")
    if ".w2c" not in lower:
        problems.append("Commit and PR conventions must mention .w2c path/artifact exclusion")
    # Do not stage / commit deny-list
    if "do not stage" not in lower and "don't stage" not in lower and "never stage" not in lower:
        if not (
            _PROHIBITION_RE.search(body)
            and ("stage" in lower or ("deny" in lower and "commit" in lower))
        ):
            problems.append(
                "Commit and PR conventions must forbid staging/committing deny-listed paths"
            )
    # Do not mention .w2c artifacts
    if "do not mention" not in lower and "don't mention" not in lower and "never mention" not in lower:
        if not (_PROHIBITION_RE.search(body) and "mention" in lower and ".w2c" in lower):
            problems.append(
                "Commit and PR conventions must forbid mentioning .w2c artifacts"
            )
    return problems


def parse_manual_test_guide(text: str) -> str:
    fields = parse_table_under_heading(text, "Delivery & Guardrails")
    return fields.get("Manual test guide", "").strip().lower()


def run_smoke(root: Path) -> Report:
    report = Report()
    wdir = w2c_dir(root)
    if not wdir.is_dir():
        report.add("w2c-present", "FAIL", ".w2c/ missing")
        return report
    report.add("w2c-present", "PASS")

    cfg = w2c_local.load_repo_config(root)
    schema = int(cfg.get("schema_version") or 1)
    if schema > w2c_local.CURRENT_SCHEMA_VERSION:
        report.add(
            "schema-version",
            "FAIL",
            f"this project's ledger requires a newer w2c (has schema {schema}, "
            f"this install supports up to {w2c_local.CURRENT_SCHEMA_VERSION}); "
            f"upgrade your w2c install",
        )
    elif schema < w2c_local.MIN_SUPPORTED_SCHEMA_VERSION:
        report.add(
            "schema-version",
            "FAIL",
            f"this project's ledger predates what this w2c supports "
            f"(has schema {schema}, minimum {w2c_local.MIN_SUPPORTED_SCHEMA_VERSION}); "
            f"run `w2c migrate adopt` / see CHANGELOG for manual steps",
        )
    else:
        report.add(
            "schema-version",
            "PASS",
            f"schema {schema} (written by w2c {cfg.get('w2c_version', 'unknown')})",
        )

    road = read_text(wdir / "ROADMAP.md")
    state = read_text(wdir / "STATE.md")
    queue = read_text(wdir / "QUEUE.md")
    decisions = read_text(wdir / "DECISIONS.md")

    mils = parse_milestones(road)
    if schema < 3 and (amend_lock_mid(root) or ledger_has_dropped(root, mils)):
        report.add(
            "dropped-schema",
            "FAIL",
            "dropped work or an amendment lock requires schema 3; run w2c amend-begin",
        )
    else:
        report.add("dropped-schema", "PASS")
    seen_m: dict[str, int] = {}
    for m in mils:
        seen_m[m.mid] = seen_m.get(m.mid, 0) + 1
    dup_m = [k for k, v in seen_m.items() if v > 1]
    plan_ids = collected_ids_from_plans(root)
    clash = sorted(set(seen_m) & plan_ids)
    # unique among ROADMAP rows
    if dup_m:
        report.add("unique-milestone-ids", "FAIL", ", ".join(dup_m))
    else:
        report.add("unique-milestone-ids", "PASS")

    slice_ok = True
    task_ok = True
    details = []
    for mil in mils:
        d = plan_dir_for(root, mil.mid)
        if d is None:
            continue
        slices = parse_slices(read_text(d / f"{mil.mid}-ROADMAP.md"))
        sids = [s[0] for s in slices]
        if len(sids) != len(set(sids)):
            slice_ok = False
            details.append(f"{mil.mid} duplicate slices")
        for sid, _done, _t in slices:
            p = d / f"{mil.mid}-{sid}-PLAN.md"
            tids = [t.tid for t in openspec_ledger.tasks_in_slice(root, mil.mid, sid, d)]
            if not tids and not p.is_file():
                continue
            if len(tids) != len(set(tids)):
                task_ok = False
                details.append(f"{mil.mid}/{sid} duplicate tasks")
    report.add("unique-slice-ids", "PASS" if slice_ok else "FAIL", "; ".join(details) if not slice_ok else "")
    report.add("unique-task-ids", "PASS" if task_ok else "FAIL", "; ".join(d for d in details if "task" in d))

    # Catch the "table instead of checkbox lines" class of bug: on-disk slice plan
    # files exist, but parse_slices() sees none/fewer of them in the milestone
    # ROADMAP's "## Slices" section (e.g. because it was written as a markdown
    # table instead of the required "- [ ] **S01: <title>**" lines). Without this
    # check, milestone-complete only surfaces the mismatch as a confusing
    # "slices still open" error after all task work is already done.
    roadmap_ok = True
    roadmap_detail = []
    for mil in mils:
        d = plan_dir_for(root, mil.mid)
        if d is None:
            continue
        slices = parse_slices(read_text(d / f"{mil.mid}-ROADMAP.md"))
        parsed_sids = {s[0] for s in slices}
        on_disk_sids = {
            m.group(1)
            for p in d.glob(f"{mil.mid}-S*-PLAN.md")
            if (m := re.search(r"-(S\d+)-PLAN\.md$", p.name))
        }
        missing = sorted(on_disk_sids - parsed_sids)
        if missing:
            roadmap_ok = False
            roadmap_detail.append(
                f"{mil.mid} has slice plan(s) {', '.join(missing)} on disk but "
                f"{mil.mid}-ROADMAP.md '## Slices' does not list them as "
                f'"- [ ] **S##: <title>**" lines (check for a table or other format)'
            )
    report.add(
        "roadmap-slices-match-plans",
        "PASS" if roadmap_ok else "FAIL",
        "; ".join(roadmap_detail),
    )

    active = parse_active_id(parse_state_field(state, "Active Milestone"))
    if not state:
        report.add("state-active-exists", "FAIL", "STATE.md missing")
    elif active is None:
        report.add("state-active-exists", "PASS", "None")
    elif any(m.mid == active for m in mils) or active in plan_ids:
        report.add("state-active-exists", "PASS", active)
    else:
        report.add("state-active-exists", "FAIL", f"{active} not in ROADMAP or plans/")

    # QUEUE ids subset of ROADMAP; emoji matches
    q_mils = parse_milestones(queue)
    road_map = {m.mid: m for m in mils}
    q_ok = True
    q_detail = []
    for q in q_mils:
        if q.mid not in road_map:
            q_ok = False
            q_detail.append(f"{q.mid} not in ROADMAP")
        elif q.status != road_map[q.mid].status:
            q_ok = False
            q_detail.append(f"{q.mid} status {q.status}!={road_map[q.mid].status}")
    report.add("queue-agrees-roadmap", "PASS" if q_ok else "FAIL", "; ".join(q_detail))

    road_open = [m.mid for m in mils if m.status != "DONE"]
    q_ids = [q.mid for q in q_mils]
    if q_ids != road_open:
        report.add(
            "queue-order-matches-roadmap",
            "FAIL",
            "non-DONE queue order "
            + " ".join(q_ids)
            + " != roadmap "
            + " ".join(road_open),
        )
    else:
        report.add("queue-order-matches-roadmap", "PASS")

    # STATE registry vs ROADMAP
    reg_ok = True
    reg_detail = []
    for line in state.splitlines():
        m = re.match(r"^- (\S+) \*\*(M\d+):\*\*", line)
        if not m:
            continue
        emoji, mid = m.group(1), m.group(2)
        st = EMOJI_STATUS.get(emoji) or EMOJI_STATUS.get(emoji.replace("\ufe0f", ""))
        if mid not in road_map:
            reg_ok = False
            reg_detail.append(f"{mid} in STATE not ROADMAP")
        elif st and st != road_map[mid].status:
            reg_ok = False
            reg_detail.append(f"{mid} STATE {st} ROADMAP {road_map[mid].status}")
    report.add("state-agrees-roadmap", "PASS" if reg_ok else "FAIL", "; ".join(reg_detail))

    nxt = next_open_task(root)
    locked = amend_lock_mid(root)
    open_count = sum(1 for t in all_tasks(root) if task_is_open(t) and t.mid != locked)
    if open_count and nxt is None:
        report.add("next-agrees-checkboxes", "FAIL", "open tasks exist but next is none")
    elif nxt and not task_is_open(nxt):
        report.add("next-agrees-checkboxes", "FAIL", f"{nxt.tid} is not an open task")
    else:
        report.add("next-agrees-checkboxes", "PASS", f"{nxt.mid} {nxt.sid} {nxt.tid}" if nxt else "none")

    if "| # | When | Scope | Decision | Choice | Rationale | Revisable? | Made By |" in decisions:
        report.add("decisions-header", "PASS")
    else:
        report.add("decisions-header", "FAIL", "missing table header")

    gd = cfg.get("git_delivery")
    if gd in w2c_local.GIT_DELIVERY_VALUES:
        report.add("git-delivery-config", "PASS", str(gd))
    else:
        report.add(
            "git-delivery-config",
            "FAIL",
            "missing or invalid git_delivery in .w2c/config.toml; run "
            f"w2c init --git-delivery {w2c_local.GIT_DELIVERY_SLICE}|{w2c_local.GIT_DELIVERY_MILESTONE}",
        )

    git_m_ok = True
    git_m_detail: list[str] = []
    git_s_ok = True
    git_s_detail: list[str] = []
    for mil in mils:
        d = plan_dir_for(root, mil.mid)
        if d is None:
            continue
        mroad = d / f"{mil.mid}-ROADMAP.md"
        if not mroad.is_file():
            continue
        mtext = read_text(mroad)
        mfields = parse_git_operation_fields(mtext)
        mprobs = validate_git_operation_plan(mfields, plan_text=mtext)
        if mprobs:
            git_m_ok = False
            git_m_detail.append(f"{mil.mid}: {'; '.join(mprobs)}")
        for sid, _done, _title in parse_slices(mtext):
            p = d / f"{mil.mid}-{sid}-PLAN.md"
            if not p.is_file():
                continue
            stext = read_text(p)
            sfields = parse_git_operation_fields(stext)
            # Slice mirror: mode/branches required; Worktree skill optional on slice
            sprobs = validate_git_operation_plan(
                sfields, require_worktree_skill=False, plan_text=stext
            )
            if sprobs:
                git_s_ok = False
                git_s_detail.append(f"{mil.mid}/{sid}: {'; '.join(sprobs)}")
            elif mfields and sfields:
                for key in ("Isolation mode", "Local branch", "Remote branch", "Base dirt policy"):
                    mv = mfields.get(key, "").strip()
                    sv = sfields.get(key, "").strip()
                    if mv and sv and mv != sv:
                        git_s_ok = False
                        git_s_detail.append(f"{mil.mid}/{sid}: {key} mismatch milestone={mv!r} slice={sv!r}")
    report.add(
        "git-operation-plan-milestone",
        "PASS" if git_m_ok else "FAIL",
        "; ".join(git_m_detail[:8]),
    )
    report.add(
        "git-operation-plan-slice",
        "PASS" if git_s_ok else "FAIL",
        "; ".join(git_s_detail[:8]),
    )

    cpr_m_ok = True
    cpr_m_detail: list[str] = []
    cpr_s_ok = True
    cpr_s_detail: list[str] = []
    mt_ok = True
    mt_detail: list[str] = []
    for mil in mils:
        d = plan_dir_for(root, mil.mid)
        if d is None:
            continue
        mroad = d / f"{mil.mid}-ROADMAP.md"
        if not mroad.is_file():
            continue
        mtext = read_text(mroad)
        mprobs = validate_commit_pr_conventions(mtext)
        if mprobs:
            cpr_m_ok = False
            cpr_m_detail.append(f"{mil.mid}: {'; '.join(mprobs)}")
        guide = parse_manual_test_guide(mtext)
        if guide not in ("yes", "no"):
            mt_ok = False
            mt_detail.append(f"{mil.mid}: Manual test guide must be yes|no (got {guide!r})")
        elif guide == "yes" and not report_present(milestone_manual_test_path(d, mil.mid)):
            mt_ok = False
            mt_detail.append(f"{mil.mid}: missing or empty {mil.mid}-MANUAL-TEST.md")
        for sid, _done, _title in parse_slices(mtext):
            p = d / f"{mil.mid}-{sid}-PLAN.md"
            if not p.is_file():
                continue
            sprobs = validate_commit_pr_conventions(read_text(p))
            if sprobs:
                cpr_s_ok = False
                cpr_s_detail.append(f"{mil.mid}/{sid}: {'; '.join(sprobs)}")
    report.add(
        "commit-pr-conventions-milestone",
        "PASS" if cpr_m_ok else "FAIL",
        "; ".join(cpr_m_detail[:8]),
    )
    report.add(
        "commit-pr-conventions-slice",
        "PASS" if cpr_s_ok else "FAIL",
        "; ".join(cpr_s_detail[:8]),
    )
    report.add(
        "manual-test-guide",
        "PASS" if mt_ok else "FAIL",
        "; ".join(mt_detail[:8]),
    )

    missing: list[str] = []
    for mil in mils:
        d = plan_dir_for(root, mil.mid)
        if d is None:
            continue
        mroad = d / f"{mil.mid}-ROADMAP.md"
        slices = parse_slices(read_text(mroad)) if mroad.is_file() else []
        for sid, done, _title in slices:
            p = d / f"{mil.mid}-{sid}-PLAN.md"
            for t in openspec_ledger.tasks_in_slice(root, mil.mid, sid, d):
                if t.done and not report_present(task_summary_path(d, sid, t.tid)):
                    missing.append(f"{sid}-{t.tid}-SUMMARY.md")
            if done:
                if not report_present(slice_uat_path(d, sid)):
                    missing.append(f"{sid}-UAT.md")
                if not report_present(slice_summary_path(d, sid)):
                    missing.append(f"{sid}-SUMMARY.md")
        if mil.status == "DONE":
            if not report_present(milestone_validation_path(d, mil.mid)):
                missing.append(f"{mil.mid}-VALIDATION.md")
            if not report_present(milestone_summary_path(d, mil.mid)):
                missing.append(f"{mil.mid}-SUMMARY.md")
    report.add(
        "closeout-reports",
        "FAIL" if missing else "PASS",
        "; ".join(missing[:12]),
    )

    for name, status, detail in openspec_ledger.smoke_checks(root, mils):
        report.add(name, status, detail)

    return report


def cmd_smoke(root: Path) -> int:
    report = run_smoke(root)
    report.print()
    failed = report.failed()
    append_event(
        root,
        skill="w2c",
        stage="smoke",
        event="fail" if failed else "pass",
        detail="smoke FAIL" if failed else "smoke PASS",
    )
    return 1 if failed else 0


def main_smoke(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="w2c-smoke")
    p.add_argument("--root", type=Path, default=None)
    args = p.parse_args(argv)
    root = args.root.resolve() if args.root else find_repo_root()
    try:
        return cmd_smoke(root)
    except W2CError as e:
        die(str(e))
        return 1


def cmd_gitignore_ensure(root: Path, track: bool) -> int:
    added = w2c_local.ensure_gitignore(root, track=track)
    if track:
        w2c_local.write_repo_config(root, track=True)
    else:
        w2c_local.write_repo_config(root, track=False)
    print("gitignore " + (", ".join(added) if added else "already current"))
    return 0


def cmd_migrate(root: Path, action: str, git_delivery: str | None = None) -> int:
    if action == "untrack":
        backup = w2c_local.migrate_untrack(root)
        gd = resolve_git_delivery(root, git_delivery)
        w2c_local.write_repo_config(root, track=False, git_delivery=gd)
        print(f"backed up to {backup}")
        print("updated .gitignore (default: ignore .w2c/ and Copilot W2C instruction files)")
        print("git index untracked (working tree files kept)")
        print("Commit .gitignore and the index change. Other clones must run:")
        print("  w2c migrate adopt --git-delivery <value>")
        print("before they pull this commit.")
        return 0
    if action == "adopt":
        restored = w2c_local.migrate_adopt(root)
        gd = resolve_git_delivery(root, git_delivery)
        w2c_local.write_repo_config(root, track=False, git_delivery=gd)
        if restored:
            print("restored: " + ", ".join(restored))
        else:
            print("nothing to restore (files already present)")
        return 0
    raise W2CError(f"unknown migrate action {action}")


def cmd_projects() -> int:
    projects = w2c_local.load_global_config().get("projects") or []
    if not projects:
        print("(no registered projects)")
        return 0
    for path in projects:
        mark = "" if Path(path).is_dir() else " (missing)"
        print(f"{path}{mark}")
    return 0


def cmd_register(root: Path) -> int:
    added = w2c_local.register_project(root)
    print(("registered " if added else "already registered ") + str(root.resolve()))
    return 0


def cmd_unregister(root: Path) -> int:
    removed = w2c_local.unregister_project(root)
    print(("unregistered " if removed else "not registered ") + str(root.resolve()))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="w2c", description="W2C ledger CLI")
    p.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"w2c {__version__}",
    )
    p.add_argument("--root", type=Path, default=None, help="repo root (default: discover)")
    sub = p.add_subparsers(dest="cmd", required=True)

    init_p = sub.add_parser("init", help="create ledger stubs if missing")
    init_p.add_argument(
        "--track", action="store_true", help="commit .w2c ledger and Copilot W2C files"
    )
    init_p.add_argument(
        "--planning",
        choices=["openspec", "classic", "legacy"],
        default=None,
        help="planning backbone for new milestones (default openspec on first init)",
    )
    init_p.add_argument(
        "--git-delivery",
        dest="git_delivery",
        choices=sorted(w2c_local.GIT_DELIVERY_VALUES),
        default=None,
        help="mandatory git commit/push cadence (required unless already set or TTY prompt)",
    )
    sub.add_parser("status", help="print STATE.md")
    sub.add_parser("smoke", help="ledger coherence checks")
    sub.add_parser("trials", help="check skill trial files for required guardrail groups")
    sub.add_parser(
        "base-dirt",
        help="classify untracked and modified files before creating a branch",
    )
    sub.add_parser(
        "openspec-check",
        help="print JSON: OpenSpec CLI, project root, and W2C rules",
    )
    spec_archive = sub.add_parser(
        "spec-archive",
        help="archive an OpenSpec change and record it on the milestone",
    )
    spec_archive.add_argument("mid")
    sub.add_parser("next-milestone-id", help="print next unused M###")

    n = sub.add_parser("next", help="next open task")
    n.add_argument("--milestone", default=None)
    n.add_argument("--slice", dest="slice_id", default=None)
    n.add_argument("--task", dest="task_id", default=None)

    c = sub.add_parser("complete", help="mark a task done (requires S##-T##-SUMMARY.md)")
    c.add_argument("--milestone", required=True)
    c.add_argument("--slice", dest="slice_id", required=True)
    c.add_argument("--task", dest="task_id", required=True)

    sc = sub.add_parser("slice-complete", help="mark a slice done (requires UAT + SUMMARY)")
    sc.add_argument("--milestone", required=True)
    sc.add_argument("--slice", dest="slice_id", required=True)

    mcp = sub.add_parser("milestone-complete", help="mark milestone DONE (requires VALIDATION + SUMMARY)")
    mcp.add_argument("mid")
    mcp.add_argument(
        "--archive-declined",
        action="store_true",
        help="finish an OpenSpec milestone without archiving; prints a follow-up",
    )

    s = sub.add_parser("set", help="update active pointer")
    s.add_argument("--active-milestone", default=None)
    s.add_argument("--active-slice", default=None)
    s.add_argument("--phase", default=None)

    ms = sub.add_parser("milestone-status", help="set milestone status")
    ms.add_argument("mid")
    ms.add_argument("status")

    mn = sub.add_parser("milestone-new", help="allocate M### and create stubs")
    mn.add_argument("--slug", required=True)
    mn.add_argument(
        "--planning",
        choices=["openspec", "classic", "legacy"],
        default=None,
        help="openspec (default from config) or classic; legacy is an alias of classic",
    )

    d = sub.add_parser("decide", help="append a decisions row")
    d.add_argument("--scope", required=True)
    d.add_argument("--decision", required=True)
    d.add_argument("--choice", required=True)
    d.add_argument("--rationale", required=True)
    d.add_argument("--revisable", default="Yes")
    d.add_argument("--made-by", default="collaborative")
    d.add_argument("--when", default=None)

    cx = sub.add_parser("context-new", help="write a new CONTEXTvX.Y.md")
    g = cx.add_mutually_exclusive_group(required=True)
    g.add_argument("--major", action="store_true")
    g.add_argument("--minor", action="store_true")

    ev = sub.add_parser("event", help="append a local runtime event (gitignored)")
    ev.add_argument("--skill", required=True)
    ev.add_argument("--stage", required=True)
    ev.add_argument("--event", required=True)
    ev.add_argument("--milestone", default=None)
    ev.add_argument("--slice", dest="slice_id", default=None)
    ev.add_argument("--task", dest="task_id", default=None)
    ev.add_argument("--detail", default="")

    evs = sub.add_parser("events", help="print local runtime events")
    evs.add_argument("--tail", type=int, default=20, help="last N events; 0 = all")
    evs.add_argument("--skill", default=None)

    mig = sub.add_parser("migrate", help="untrack or restore W2C files")
    mig.add_argument("action", choices=["untrack", "adopt"])
    mig.add_argument(
        "--git-delivery",
        dest="git_delivery",
        choices=sorted(w2c_local.GIT_DELIVERY_VALUES),
        default=None,
        help="mandatory git commit/push cadence when not already set",
    )

    gi = sub.add_parser("gitignore-ensure", help="ensure W2C gitignore entries")
    gi.add_argument("--track", action="store_true")

    mv = sub.add_parser(
        "milestone-move",
        help="move a milestone before or after another in execution order",
    )
    mv.add_argument("mid")
    place = mv.add_mutually_exclusive_group(required=True)
    place.add_argument("--before", default=None)
    place.add_argument("--after", default=None)

    mo = sub.add_parser(
        "milestone-order",
        help="print execution order, or set relative order of pending milestones",
    )
    mo.add_argument("mids", nargs="*", help="relative order of these milestone ids")

    sw = sub.add_parser("milestone-swap", help="swap two milestones in execution order")
    sw.add_argument("left")
    sw.add_argument("right")

    sub.add_parser("projects", help="list registered project roots")
    sub.add_parser("register", help="register this repo in global config")
    sub.add_parser("unregister", help="remove this repo from global config")

    ins = sub.add_parser(
        "install-skills",
        help="install work-to-chores / do-chores into ~/.agents/skills",
    )
    ins.add_argument("--force", action="store_true")
    ins.add_argument("--dry-run", action="store_true")
    ins.add_argument("--no-cursor", action="store_true")
    ins.add_argument("--no-claude", action="store_true")
    _add_amend_parsers(sub)
    return p


def _add_amend_parsers(sub: argparse._SubParsersAction) -> None:
    begin = sub.add_parser("amend-begin", help="pause an in-progress milestone and lock amendments")
    begin.add_argument("mid")
    begin.add_argument("--decision", required=True)
    end = sub.add_parser("amend-end", help="clear the amendment lock after smoke passes")
    end.add_argument("mid")
    listed = sub.add_parser("amendments", help="print the milestone amendment record")
    listed.add_argument("mid")
    drop_task = sub.add_parser("drop-task", help="mark an unfinished task dropped")
    drop_task.add_argument("--milestone", required=True)
    drop_task.add_argument("--slice", dest="slice_id", required=True)
    drop_task.add_argument("--task", dest="task_id", required=True)
    drop_task.add_argument("--reason", required=True)
    drop_task.add_argument("--decision", required=True)
    drop_task.add_argument("--follow-up", default="")
    drop_task.add_argument("--ticket", default="")
    drop_slice = sub.add_parser("drop-slice", help="mark an unfinished slice dropped")
    drop_slice.add_argument("--milestone", required=True)
    drop_slice.add_argument("--slice", dest="slice_id", required=True)
    drop_slice.add_argument("--reason", required=True)
    drop_slice.add_argument("--decision", required=True)
    drop_slice.add_argument("--follow-up", default="")
    drop_slice.add_argument("--ticket", default="")
    add_task = sub.add_parser("task-add", help="append an open task")
    add_task.add_argument("--milestone", required=True)
    add_task.add_argument("--slice", dest="slice_id", required=True)
    add_task.add_argument("--title", required=True)
    add_task.add_argument("--verify", required=True)
    add_task.add_argument("--reason", required=True)
    add_task.add_argument("--decision", required=True)
    edit_task = sub.add_parser("task-edit", help="edit an unfinished task title and Verify line")
    edit_task.add_argument("--milestone", required=True)
    edit_task.add_argument("--slice", dest="slice_id", required=True)
    edit_task.add_argument("--task", dest="task_id", required=True)
    edit_task.add_argument("--title", required=True)
    edit_task.add_argument("--verify", required=True)
    edit_task.add_argument("--reason", required=True)
    edit_task.add_argument("--decision", required=True)
    add_slice = sub.add_parser("slice-add", help="append an open slice")
    add_slice.add_argument("--milestone", required=True)
    add_slice.add_argument("--title", required=True)
    add_slice.add_argument("--reason", required=True)
    add_slice.add_argument("--decision", required=True)
    follow = sub.add_parser("follow-up", help="set the ticket link on an amendment")
    follow.add_argument("--milestone", required=True)
    follow.add_argument("--slice", dest="slice_id", required=True)
    follow.add_argument("--task", dest="task_id", default=None)
    follow.add_argument("--ticket", required=True)


def dispatch(args: argparse.Namespace) -> int:
    cmd = args.cmd
    if cmd == "install-skills":
        return install_skills(
            skills_dir(),
            W2CError,
            force=bool(getattr(args, "force", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
            cursor=not bool(getattr(args, "no_cursor", False)),
            claude=not bool(getattr(args, "no_claude", False)),
        )
    root = args.root.resolve() if args.root else find_repo_root()
    if cmd == "init":
        return cmd_init(
            root,
            track=True if getattr(args, "track", False) else None,
            git_delivery=getattr(args, "git_delivery", None),
            planning=getattr(args, "planning", None),
        )
    if cmd == "status":
        return cmd_status(root)
    if cmd == "smoke":
        return cmd_smoke(root)
    if cmd == "trials":
        return w2c_trials.cmd_trials()
    if cmd == "base-dirt":
        try:
            return base_dirt.cmd_base_dirt(
                str(root), extra_prefixes=openspec_ledger.change_prefixes(root)
            )
        except base_dirt.BaseDirtError as exc:
            raise W2CError(str(exc)) from exc
    if cmd == "openspec-check":
        return cmd_openspec_check(root)
    if cmd == "spec-archive":
        return cmd_spec_archive(root, args.mid)
    if cmd == "next":
        return cmd_next(root, args.milestone, args.slice_id, args.task_id)
    if cmd == "complete":
        return cmd_complete(root, args.milestone, args.slice_id, args.task_id)
    if cmd == "slice-complete":
        return cmd_slice_complete(root, args.milestone, args.slice_id)
    if cmd == "milestone-complete":
        return cmd_milestone_status(
            root, args.mid, "DONE", archive_declined=bool(args.archive_declined)
        )
    if cmd == "set":
        return cmd_set(root, args.active_milestone, args.active_slice, args.phase)
    if cmd == "milestone-status":
        return cmd_milestone_status(root, args.mid, args.status)
    if cmd == "next-milestone-id":
        return cmd_next_milestone_id(root)
    if cmd == "milestone-new":
        return cmd_milestone_new(root, args.slug, getattr(args, "planning", None))
    if cmd == "milestone-order":
        return cmd_milestone_order(root, args.mids)
    if cmd == "milestone-swap":
        return cmd_milestone_swap(root, args.left, args.right)
    if cmd == "milestone-move":
        return cmd_milestone_move(root, args.mid, args.before, args.after)
    if cmd == "decide":
        return cmd_decide(
            root,
            args.scope,
            args.decision,
            args.choice,
            args.rationale,
            args.revisable,
            args.made_by,
            args.when,
        )
    if cmd == "context-new":
        return cmd_context_new(root, args.major, args.minor)
    if cmd == "event":
        return cmd_event(
            root,
            args.skill,
            args.stage,
            args.event,
            args.milestone,
            args.slice_id,
            args.task_id,
            args.detail or "",
        )
    if cmd == "events":
        return cmd_events(root, args.tail, args.skill)
    if cmd == "migrate":
        return cmd_migrate(root, args.action, git_delivery=getattr(args, "git_delivery", None))
    if cmd == "gitignore-ensure":
        return cmd_gitignore_ensure(root, bool(getattr(args, "track", False)))
    if cmd == "projects":
        return cmd_projects()
    if cmd == "register":
        return cmd_register(root)
    if cmd == "unregister":
        return cmd_unregister(root)
    if cmd in {
        "amend-begin",
        "amend-end",
        "amendments",
        "drop-task",
        "drop-slice",
        "task-add",
        "task-edit",
        "slice-add",
        "follow-up",
    }:
        return _dispatch_amend(args, root)
    raise W2CError(f"unknown command {cmd}")


def _dispatch_amend(args: argparse.Namespace, root: Path) -> int:
    from w2c import amend as w2c_amend

    cmd = args.cmd
    if cmd == "amend-begin":
        return w2c_amend.cmd_amend_begin(root, args.mid, args.decision)
    if cmd == "amend-end":
        return w2c_amend.cmd_amend_end(root, args.mid)
    if cmd == "amendments":
        return w2c_amend.cmd_amendments(root, args.mid)
    if cmd == "drop-task":
        return w2c_amend.cmd_drop_task(
            root,
            args.milestone,
            args.slice_id,
            args.task_id,
            args.reason,
            args.decision,
            args.follow_up,
            args.ticket,
        )
    if cmd == "drop-slice":
        return w2c_amend.cmd_drop_slice(
            root,
            args.milestone,
            args.slice_id,
            args.reason,
            args.decision,
            args.follow_up,
            args.ticket,
        )
    if cmd == "task-add":
        return w2c_amend.cmd_task_add(
            root,
            args.milestone,
            args.slice_id,
            args.title,
            args.verify,
            args.reason,
            args.decision,
        )
    if cmd == "task-edit":
        return w2c_amend.cmd_task_edit(
            root,
            args.milestone,
            args.slice_id,
            args.task_id,
            args.title,
            args.verify,
            args.reason,
            args.decision,
        )
    if cmd == "slice-add":
        return w2c_amend.cmd_slice_add(
            root, args.milestone, args.title, args.reason, args.decision
        )
    if cmd == "follow-up":
        return w2c_amend.cmd_follow_up(
            root, args.milestone, args.slice_id, args.ticket, args.task_id
        )
    raise W2CError(f"unknown command {cmd}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except (W2CError, w2c_local.GitDeliveryError, w2c_local.LocalError, w2c_openspec.OpenSpecError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
