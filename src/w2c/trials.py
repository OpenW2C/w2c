"""Shape checks for skill trials. No model call."""

from __future__ import annotations

import json
import re
from pathlib import Path

from w2c import local as w2c_local

SKILL_NAMES = ("work-to-chores", "do-chores")
MODES = ("openspec", "classic")
KINDS = ("ordinary", "hostile")

SHARED_GROUPS = ("isolation", "base-dirt", "commit-rules", "hard-stop")
GROUPS_BOTH: dict[str, tuple[str, ...]] = {
    "work-to-chores": SHARED_GROUPS + ("interview", "plan-write", "reorder"),
    "do-chores": SHARED_GROUPS + ("execute", "closeout"),
}
GROUPS_ONE: dict[str, dict[str, tuple[str, ...]]] = {
    "work-to-chores": {
        "openspec": ("install-ask", "spec-commit"),
        "classic": ("plan-commit",),
    },
    "do-chores": {
        "openspec": ("archive",),
        "classic": ("classic-boundary",),
    },
}

ID_RE = re.compile(r"^R\d{2}$")
VAGUE_WORDS = ("process", "conventions", "correctly", "appropriately")
CONCRETE_TOKENS = (
    "openspec",
    "classic",
    "legacy",
    "checkbox",
    "archive",
    "push",
    "approve",
    "approval",
    "spec",
    "branch",
    "worktree",
    "smoke",
    "commit",
    "co-authored-by",
    ".w2c",
    "track",
    "verify",
    "isolate",
    "report",
    "force",
    "dirty",
    "tasks.md",
    "decide",
    "install",
    "reorder",
    "pending",
    "in-progress",
    "in progress",
    "max-units",
    "critical",
    "leave-untouched",
    "pull request",
    "milestone",
    "slice",
    "sudo",
    "stage 5",
    "deny-listed",
)


def required_groups(skill: str, mode: str) -> tuple[str, ...]:
    both = GROUPS_BOTH.get(skill, ())
    one = GROUPS_ONE.get(skill, {}).get(mode, ())
    return both + one


def exclusive_groups(skill: str) -> dict[str, str]:
    """group -> the only mode allowed to use it."""
    out: dict[str, str] = {}
    for mode, names in GROUPS_ONE.get(skill, {}).items():
        for name in names:
            out[name] = mode
    return out


def locate_trials(skill: str) -> Path | None:
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    if len(here.parents) >= 3:
        candidates.append(here.parents[2] / "skills" / skill / "trials.json")
    candidates.append(here.parent / "assets" / "skills" / skill / "trials.json")
    candidates.append(w2c_local.data_home() / "skills" / skill / "trials.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _vague_problem(line: str) -> str | None:
    folded = line.casefold()
    if not any(word in folded for word in VAGUE_WORDS):
        return None
    if any(token in folded for token in CONCRETE_TOKENS):
        return None
    return "vague must line has no concrete noun"


def check_trials(data: object, skill: str) -> list[str]:
    problems: list[str] = []
    if not isinstance(data, dict):
        return [f"{skill}: trials file must be an object"]
    if data.get("skill") != skill:
        problems.append(f"{skill}: skill field is {data.get('skill')!r}")
    trials = data.get("trials")
    if not isinstance(trials, list):
        return problems + [f"{skill}: trials must be a list"]

    seen: set[str] = set()
    hostile = {mode: False for mode in MODES}
    present = {(mode, group) for mode in MODES for group in required_groups(skill, mode)}
    found: set[tuple[str, str]] = set()
    exclusive = exclusive_groups(skill)

    for index, trial in enumerate(trials):
        label = f"{skill} trial {index + 1}"
        if not isinstance(trial, dict):
            problems.append(f"{label}: must be an object")
            continue
        tid = trial.get("id")
        if not isinstance(tid, str) or not ID_RE.match(tid):
            problems.append(f"{label}: id must look like R01")
        elif tid in seen:
            problems.append(f"{skill}: duplicate id {tid}")
        else:
            seen.add(tid)
            label = f"{skill} {tid}"
        kind = trial.get("kind")
        mode = trial.get("mode")
        group = trial.get("group")
        known = required_groups(skill, "openspec") + required_groups(skill, "classic")
        if kind not in KINDS:
            problems.append(f"{label}: kind must be ordinary or hostile")
        if mode not in MODES:
            problems.append(f"{label}: mode must be openspec or classic")
        if not isinstance(group, str) or group not in known:
            problems.append(f"{label}: unknown group {group!r}")
        elif mode in MODES and exclusive.get(group) not in (None, mode):
            problems.append(f"{label}: group {group} is only for mode {exclusive[group]}")
        elif mode in MODES:
            found.add((mode, group))
        if kind == "hostile" and mode in hostile:
            hostile[mode] = True
        ask = trial.get("ask")
        passes = trial.get("passes_when")
        must = trial.get("must")
        if not isinstance(ask, str) or not ask.strip():
            problems.append(f"{label}: ask is empty")
        elif "legacy" in ask.casefold() and (mode != "classic" or group != "interview"):
            problems.append(f"{label}: an ask that says legacy must be classic interview")
        if not isinstance(passes, str) or not passes.strip():
            problems.append(f"{label}: passes_when is empty")
        if not isinstance(must, list):
            problems.append(f"{label}: need at least 2 must lines")
        else:
            filled = 0
            for line in must:
                if not isinstance(line, str) or not line.strip():
                    problems.append(f"{label}: empty must line")
                    continue
                filled += 1
                vague = _vague_problem(line)
                if vague:
                    problems.append(f"{label}: {vague}")
            if filled < 2:
                problems.append(f"{label}: need at least 2 must lines")

    for mode in MODES:
        if not hostile[mode]:
            problems.append(f"{skill}: no hostile trial for mode {mode}")
    missing = sorted(present - found)
    for mode, group in missing:
        problems.append(f"{skill}: missing {mode} group {group}")
    return problems


def load_trials(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def run_trials() -> tuple[list[tuple[str, str, str]], int]:
    """Return (skill, PASS|FAIL, detail) rows and an exit code."""
    rows: list[tuple[str, str, str]] = []
    failed = False
    for skill in SKILL_NAMES:
        path = locate_trials(skill)
        if path is None:
            rows.append((skill, "FAIL", "trials.json missing"))
            failed = True
            continue
        try:
            data = load_trials(path)
        except json.JSONDecodeError as exc:
            rows.append((skill, "FAIL", f"invalid JSON: {exc}"))
            failed = True
            continue
        problems = check_trials(data, skill)
        if problems:
            rows.append((skill, "FAIL", "; ".join(problems)))
            failed = True
        else:
            rows.append((skill, "PASS", ""))
    return rows, (1 if failed else 0)


def cmd_trials() -> int:
    rows, code = run_trials()
    for skill, status, detail in rows:
        if detail:
            print(f"{skill} {status}: {detail}")
        else:
            print(f"{skill} {status}")
    return code
