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

from w2c import local as w2c_local
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

_EMOJI_ALT = "|".join(
    re.escape(e)
    for e in dict.fromkeys(
        [*STATUS_EMOJI.values(), *(e.replace("\ufe0f", "") for e in STATUS_EMOJI.values())]
    )
)
MILESTONE_LINE_RE = re.compile(
    r"^- +(?P<emoji>" + _EMOJI_ALT + r")\s+\*\*(?P<id>M\d+):\s*(?P<title>.+?)\*\*"
)
SLICE_LINE_RE = re.compile(r"^- \[([ xX])\] \*\*(S\d+):")
TASK_LINE_RE = re.compile(r"^- \[([ xX])\] \*\*(T\d+)\*\*")
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
| Integration strategy | trunk-direct |
| Integration branch | |
| Commit cadence | milestone |
| Review unit | none |
| Git/PR checkpoint mode | none |
| Isolation mode | |
| Branch name | |
| Execution sequence | |
| Validation commands | |
| Completion condition | All slices verified; single commit after milestone verification; push only with explicit approval |
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
| Push rule | after milestone verification + explicit user approval; push ref must equal Remote branch |

### Guardrails
- **Commit cadence** — one commit after the milestone is verified unless this table says otherwise. Do not commit per slice by default.
- **Remote mutation** — no push, PR, or remote git mutation without explicit user approval.
- **Git isolation** — honor Isolation mode (`worktree` or `branch` only). Local branch must equal Remote branch (ticket id or confirmed slug). Setup on first `do-chores`; reuse the same ticket isolation across milestones.
- **Plan commit** — commit `.w2c/` plan/ledger files (never `runtime/`, never product code) onto the ticket branch before isolation so a worktree can see the ledger. No push without approval.
- **No force git** — never force-reset, force-push, or delete worktrees/branches. Dirty or unexpected existing branch/worktree → hard stop and ask.
- **Validation** — run the validation commands in this table before each commit and before each push.
- **Status writes** — never hand-edit STATE.md, QUEUE.md, ROADMAP status emojis, or task checkboxes. Use `.w2c/scripts/w2c.sh`.
- **Verify loop** — a task is not complete until its Verify commands pass and requesting-code-review is clean.
- **Closeout reports** — write `S##-T##-SUMMARY.md` before `complete`; `S##-UAT.md` + `S##-SUMMARY.md` before `slice-complete`; `M###-VALIDATION.md` + `M###-SUMMARY.md` before milestone DONE.
- **Commit and PR** — honor `## Commit and PR conventions`. Never add `Co-authored-by:` or similar AI co-author trailers.

## Commit and PR conventions

Planner: inspect this repo (`CONTRIBUTING*`, `.github/*PULL_REQUEST_TEMPLATE*`, recent `git log` title/body) and fill this section. Do not leave TBD.

**Commit title:**

**Commit body:**

**Pull request:**

**AI attribution — forbidden:**
Do not add `Co-authored-by:` trailers or similar AI co-author / “assisted by Cursor, Copilot, Claude, or Codex” lines.
"""

M_CONTEXT_STUB = """# {mid} — {title}\n\n## Problem\n\n## Solution\n\n## Key Decisions\n\n## Out of Scope\n\n## Validation\n\n## Completion Criteria\n"""


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


def parse_slices(text: str) -> list[tuple[str, bool, str]]:
    """Return (sid, done, title)."""
    out: list[tuple[str, bool, str]] = []
    for line in text.splitlines():
        m = re.match(r"^- \[([ xX])\] \*\*(S\d+):\s*(.+?)\*\*", line)
        if m:
            out.append((m.group(2), m.group(1).lower() == "x", m.group(3).strip()))
    return out


def parse_tasks(plan_path: Path, mid: str, sid: str) -> list[Task]:
    text = read_text(plan_path)
    tasks: list[Task] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = TASK_LINE_RE.match(line)
        if not m:
            continue
        done = m.group(1).lower() == "x"
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
            p = d / f"{mil.mid}-{sid}-PLAN.md"
            if p.is_file():
                found.extend(parse_tasks(p, mil.mid, sid))
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
        out = [t for t in out if t.tid == task_id]
    return out


def next_open_task(
    root: Path,
    milestone: str | None = None,
    slice_id: str | None = None,
    task_id: str | None = None,
) -> Task | None:
    tasks = filter_tasks(all_tasks(root), milestone, slice_id, task_id)
    for t in tasks:
        if not t.done:
            return t
    return None


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


def cmd_init(root: Path, track: bool | None = None) -> int:
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
    if not w2c_local.repo_config_path(root).is_file():
        w2c_local.write_repo_config(root, track=bool(track))
    elif track is True:
        w2c_local.write_repo_config(root, track=True)
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
    }


def cmd_next(
    root: Path,
    milestone: str | None,
    slice_id: str | None,
    task_id: str | None,
) -> int:
    t = next_open_task(root, milestone, slice_id, task_id)
    if t is None:
        print("NEXT none")
        print(json.dumps({"task": None}))
        return 0
    print(f"NEXT {t.mid} {t.sid} {t.tid} — {t.title}")
    print(json.dumps({"task": task_to_dict(t)}, indent=2))
    return 0


def cmd_complete(root: Path, mid: str, sid: str, tid: str) -> int:
    path = slice_plan_path(root, mid, sid)
    if path is None:
        raise W2CError(f"slice plan not found for {mid} {sid}")
    d = plan_dir_for(root, mid)
    if d is None:
        raise W2CError(f"plan folder not found for {mid}")
    require_report(task_summary_path(d, sid, tid), f"{sid}-{tid}-SUMMARY.md")
    tasks = parse_tasks(path, mid, sid)
    match = [t for t in tasks if t.tid == tid]
    if not match:
        raise W2CError(f"unknown task {mid} {sid} {tid}")
    if match[0].done:
        raise W2CError(f"{tid} is already complete")
    atomic_write(path, set_task_checked(read_text(path), tid, True))

    remaining = [t for t in parse_tasks(path, mid, sid) if not t.done]
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
    d = plan_dir_for(root, mid)
    if d is None:
        raise W2CError(f"plan folder not found for {mid}")
    path = slice_plan_path(root, mid, sid)
    if path is None:
        raise W2CError(f"slice plan not found for {mid} {sid}")
    tasks = parse_tasks(path, mid, sid)
    if not tasks:
        raise W2CError(f"no tasks in {mid} {sid}")
    open_tasks = [t.tid for t in tasks if not t.done]
    if open_tasks:
        raise W2CError(f"open tasks remain in {mid} {sid}: {', '.join(open_tasks)}")
    for t in tasks:
        require_report(task_summary_path(d, sid, t.tid), f"{sid}-{t.tid}-SUMMARY.md")
    require_report(slice_uat_path(d, sid), f"{sid}-UAT.md")
    require_report(slice_summary_path(d, sid), f"{sid}-SUMMARY.md")
    mroad_path = d / f"{mid}-ROADMAP.md"
    if not mroad_path.is_file():
        raise W2CError(f"missing {mid}-ROADMAP.md")
    atomic_write(mroad_path, set_slice_checked(read_text(mroad_path), sid, True))
    slices = parse_slices(read_text(mroad_path))
    all_slices_done = bool(slices) and all(done for _s, done, _t in slices)
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
        print(f"OPEN_SLICES {sum(1 for _s, done, _t in slices if not done)}")
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


def cmd_milestone_status(root: Path, mid: str, status: str) -> int:
    status = status.upper()
    if status not in STATUS_EMOJI:
        raise W2CError(f"invalid status {status}; use {', '.join(VALID_STATUSES)}")
    if status == "DONE":
        d = plan_dir_for(root, mid)
        if d is None:
            raise W2CError(f"plan folder not found for {mid}")
        mroad_path = d / f"{mid}-ROADMAP.md"
        slices = parse_slices(read_text(mroad_path)) if mroad_path.is_file() else []
        if not slices or not all(done for _s, done, _t in slices):
            raise W2CError(f"slices still open in {mid}")
        require_report(milestone_validation_path(d, mid), f"{mid}-VALIDATION.md")
        require_report(milestone_summary_path(d, mid), f"{mid}-SUMMARY.md")
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


def cmd_milestone_new(root: Path, slug: str) -> int:
    slug = slugify(slug)
    mid = next_milestone_id(root)
    title = slug.replace("-", " ")
    d = w2c_dir(root) / "plans" / f"{mid}-{slug}"
    if d.exists():
        raise W2CError(f"already exists: {d}")
    d.mkdir(parents=True)
    atomic_write(d / f"{mid}-ROADMAP.md", M_ROADMAP_STUB.format(mid=mid, title=title, slug=slug))
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


def validate_git_operation_plan(fields: dict[str, str], *, require_worktree_skill: bool = True) -> list[str]:
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
    """Return problems; empty list means the section is present, non-empty, and forbids Co-authored-by."""
    body = section_under_heading(text, "Commit and PR conventions")
    if body is None:
        return ["missing ## Commit and PR conventions section"]
    if not body.strip():
        return ["empty ## Commit and PR conventions section"]
    if "co-authored-by" not in body.lower():
        return ["Commit and PR conventions must mention Co-authored-by"]
    if not _PROHIBITION_RE.search(body):
        return ["Commit and PR conventions must forbid Co-authored-by"]
    return []


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

    road = read_text(wdir / "ROADMAP.md")
    state = read_text(wdir / "STATE.md")
    queue = read_text(wdir / "QUEUE.md")
    decisions = read_text(wdir / "DECISIONS.md")

    mils = parse_milestones(road)
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
            if not p.is_file():
                continue
            tids = [t.tid for t in parse_tasks(p, mil.mid, sid)]
            if len(tids) != len(set(tids)):
                task_ok = False
                details.append(f"{mil.mid}/{sid} duplicate tasks")
    report.add("unique-slice-ids", "PASS" if slice_ok else "FAIL", "; ".join(details) if not slice_ok else "")
    report.add("unique-task-ids", "PASS" if task_ok else "FAIL", "; ".join(d for d in details if "task" in d))

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
    open_count = sum(1 for t in all_tasks(root) if not t.done)
    if open_count and nxt is None:
        report.add("next-agrees-checkboxes", "FAIL", "open tasks exist but next is none")
    elif nxt and nxt.done:
        report.add("next-agrees-checkboxes", "FAIL", f"{nxt.tid} marked done")
    else:
        report.add("next-agrees-checkboxes", "PASS", f"{nxt.mid} {nxt.sid} {nxt.tid}" if nxt else "none")

    if "| # | When | Scope | Decision | Choice | Rationale | Revisable? | Made By |" in decisions:
        report.add("decisions-header", "PASS")
    else:
        report.add("decisions-header", "FAIL", "missing table header")


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
        mprobs = validate_git_operation_plan(mfields)
        if mprobs:
            git_m_ok = False
            git_m_detail.append(f"{mil.mid}: {'; '.join(mprobs)}")
        for sid, _done, _title in parse_slices(mtext):
            p = d / f"{mil.mid}-{sid}-PLAN.md"
            if not p.is_file():
                continue
            sfields = parse_git_operation_fields(read_text(p))
            # Slice mirror: mode/branches required; Worktree skill optional on slice
            sprobs = validate_git_operation_plan(sfields, require_worktree_skill=False)
            if sprobs:
                git_s_ok = False
                git_s_detail.append(f"{mil.mid}/{sid}: {'; '.join(sprobs)}")
            elif mfields and sfields:
                for key in ("Isolation mode", "Local branch", "Remote branch"):
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
            if p.is_file():
                for t in parse_tasks(p, mil.mid, sid):
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


def cmd_migrate(root: Path, action: str) -> int:
    if action == "untrack":
        backup = w2c_local.migrate_untrack(root)
        print(f"backed up to {backup}")
        print("updated .gitignore (default: ignore .w2c/ and Copilot W2C instruction files)")
        print("git index untracked (working tree files kept)")
        print("Commit .gitignore and the index change. Other clones must run:")
        print("  w2c migrate adopt")
        print("before they pull this commit.")
        return 0
    if action == "adopt":
        restored = w2c_local.migrate_adopt(root)
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
    p.add_argument("--root", type=Path, default=None, help="repo root (default: discover)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create ledger stubs if missing").add_argument(
        "--track", action="store_true", help="commit .w2c ledger and Copilot W2C files"
    )
    sub.add_parser("status", help="print STATE.md")
    sub.add_parser("smoke", help="ledger coherence checks")
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

    s = sub.add_parser("set", help="update active pointer")
    s.add_argument("--active-milestone", default=None)
    s.add_argument("--active-slice", default=None)
    s.add_argument("--phase", default=None)

    ms = sub.add_parser("milestone-status", help="set milestone status")
    ms.add_argument("mid")
    ms.add_argument("status")

    mn = sub.add_parser("milestone-new", help="allocate M### and create stubs")
    mn.add_argument("--slug", required=True)

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

    gi = sub.add_parser("gitignore-ensure", help="ensure W2C gitignore entries")
    gi.add_argument("--track", action="store_true")

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
    return p


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
        return cmd_init(root, track=True if getattr(args, "track", False) else None)
    if cmd == "status":
        return cmd_status(root)
    if cmd == "smoke":
        return cmd_smoke(root)
    if cmd == "next":
        return cmd_next(root, args.milestone, args.slice_id, args.task_id)
    if cmd == "complete":
        return cmd_complete(root, args.milestone, args.slice_id, args.task_id)
    if cmd == "slice-complete":
        return cmd_slice_complete(root, args.milestone, args.slice_id)
    if cmd == "milestone-complete":
        return cmd_milestone_status(root, args.mid, "DONE")
    if cmd == "set":
        return cmd_set(root, args.active_milestone, args.active_slice, args.phase)
    if cmd == "milestone-status":
        return cmd_milestone_status(root, args.mid, args.status)
    if cmd == "next-milestone-id":
        return cmd_next_milestone_id(root)
    if cmd == "milestone-new":
        return cmd_milestone_new(root, args.slug)
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
        return cmd_migrate(root, args.action)
    if cmd == "gitignore-ensure":
        return cmd_gitignore_ensure(root, bool(getattr(args, "track", False)))
    if cmd == "projects":
        return cmd_projects()
    if cmd == "register":
        return cmd_register(root)
    if cmd == "unregister":
        return cmd_unregister(root)
    raise W2CError(f"unknown command {cmd}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except W2CError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
