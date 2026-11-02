"""The cloud step driver: the command line, not the agent, picks each next step.

`next_action` reads the change's committed files and a small local state file
and returns exactly one action. `record` stores the result of the action the
driver asked for. Files on disk always win over a record: a task is complete
only when its box is ticked, a report is written only when it exists, a slice
is done only when it is in `x-delivery-slices-done`, and the branch is checked
on every call.

State lives in `.w2c/runtime/step.json` (gitignored local runtime). A missing,
unreadable, or foreign state file means a fresh start. Standard library only;
the CLI package is imported lazily.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from w2c import local as w2c_local
from w2c import openspec_ledger as osl
from w2c.cloud import checks, commands, environment, layout, ledger

STEP_STATE = Path(".w2c/runtime/step.json")
STATE_VERSION = 1

TASK_STAGES: tuple[str, ...] = ("implement", "verify", "review", "write-report", "complete")
WORK_ACTIONS = frozenset(
    {"smoke", "isolate", *TASK_STAGES, "slice-reports", "slice-complete", "milestone-reports"}
)
ASK_ACTIONS = frozenset({"ask-commit", "ask-push", "ask-archive", "ask-pr"})
WORK_RESULTS = ("pass", "fail")
ASK_RESULTS = ("yes", "no", "no-answer")
SLICE_ASKS = ("ask-commit", "ask-push")
MILESTONE_ASKS = ("ask-archive", "ask-commit", "ask-push", "ask-pr")
RUNNABLE = frozenset({"INPROGRESS", "PLANNING", "TODO"})


def _cli():
    from w2c import cli as w2c_cli

    return w2c_cli


# --------------------------------------------------------------------------- state


def _empty_state(change: str | None) -> dict:
    return {
        "version": STATE_VERSION,
        "change": change,
        "task": None,
        "last_action": None,
        "last_result": None,
        "stage_action": None,
        "stage_result": None,
        "smoke": None,
        "isolate": None,
        "slice_answers": {"group": None},
        "milestone_answers": {},
        "expected": None,
    }


def _str_or_none(value: object) -> bool:
    return value is None or isinstance(value, str)


def _valid(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    for key in ("change", "task", "last_action", "last_result", "stage_action", "stage_result",
                "isolate"):
        if not _str_or_none(data.get(key)):
            return False
    smoke = data.get("smoke")
    if smoke is not None:
        if not isinstance(smoke, dict) or not all(
            _str_or_none(smoke.get(k)) for k in ("change", "task", "result")
        ):
            return False
    sl = data.get("slice_answers", {"group": None})
    if not isinstance(sl, dict):
        return False
    if sl.get("group") is not None and (not isinstance(sl.get("group"), int)
                                        or isinstance(sl.get("group"), bool)):
        return False
    if not all(isinstance(sl.get(a), str) for a in SLICE_ASKS if a in sl):
        return False
    expected = data.get("expected")
    if expected is not None:
        if not isinstance(expected, dict) or not isinstance(expected.get("action"), str):
            return False
        if not _str_or_none(expected.get("task")) or not _str_or_none(expected.get("ask_scope")):
            return False
        group = expected.get("ask_group")
        if group is not None and (not isinstance(group, int) or isinstance(group, bool)):
            return False
        recordable = expected.get("recordable")
        if not isinstance(recordable, list) or not all(isinstance(a, str) for a in recordable):
            return False
    ms = data.get("milestone_answers", {})
    if not isinstance(ms, dict) or not all(isinstance(ms.get(a), str) for a in MILESTONE_ASKS if a in ms):
        return False
    return True


def load_state(root: Path) -> dict | None:
    """The state file, or None when it is missing, unreadable, or malformed."""
    path = root / STEP_STATE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not _valid(data):
        return None
    state = _empty_state(data.get("change"))
    state.update({k: data.get(k, state[k]) for k in state})
    state["version"] = STATE_VERSION
    return state


def _state_for(root: Path, change: str) -> dict:
    """The state for this change; a foreign or missing state starts fresh."""
    state = load_state(root)
    if state is None or state.get("change") != change:
        return _empty_state(change)
    return state


def _save_state(root: Path, state: dict) -> None:
    _cli().atomic_write(root / STEP_STATE, json.dumps(state, indent=2, sort_keys=True) + "\n")


# --------------------------------------------------------------------------- plan


@dataclass
class Context:
    """Where the driver is in a change; filled by `_evaluate`."""

    change: ledger.CloudChange | None = None
    group: int | None = None
    task: object | None = None
    ask_scope: str | None = None  # "slice" or "milestone" while an ask is pending
    ask_group: int | None = None
    recordable: set[str] = field(default_factory=set)


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _out(action: str, ctx: Context, files: list[str] | None = None, reason: str | None = None) -> dict:
    sid = f"S{ctx.group:02d}" if ctx.group is not None else None
    return {
        "action": action,
        "change": ctx.change.name if ctx.change is not None else None,
        "slice": sid,
        "task": ctx.task.tid if ctx.task is not None else None,
        "files": files or [],
        "reason": reason,
    }


def _present(change: ledger.CloudChange, key: str, sid: str = "", tid: str = "") -> bool:
    return _cli().report_present(ledger.delivery_dir(change) / checks.report_name(key, sid, tid))


def _report_path(root: Path, change: ledger.CloudChange, key: str, sid: str = "", tid: str = "") -> str:
    return _rel(root, ledger.delivery_dir(change) / checks.report_name(key, sid, tid))


def _position(change: ledger.CloudChange) -> tuple[int | None, object | None, int | None, bool]:
    """(current group, its first open task, last finished slice group, every group done).

    The current group is the first unfinished group. The last finished slice
    group is the latest group before it that went through slice-complete; its
    asks are owed before the driver moves on.
    """
    tasks = commands._change_tasks(change)
    numbers, open_groups = commands._groups(change)
    last_done: int | None = None
    for number in numbers:
        if number in open_groups:
            in_group = [t for t in tasks if t.sid == f"S{number:02d}"]
            task = next((t for t in in_group if commands._is_open(t)), None)
            return number, task, last_done, False
        in_group = [t for t in tasks if t.sid == f"S{number:02d}"]
        if not all(t.dropped for t in in_group):
            last_done = number
    return None, None, last_done, True


def _ask(answers: dict, action: str) -> str | None:
    value = answers.get(action)
    return value if value in ASK_RESULTS else None


def _evaluate(root: Path, change: ledger.CloudChange, state: dict) -> tuple[dict, Context]:
    ctx = Context(change=change)
    if not change.archived and change.amend_lock:
        return _out("stop", ctx, reason="AMEND_LOCK"), ctx
    tasks_md = change.path / "tasks.md"
    if not commands._change_tasks(change):
        ctx.recordable.add("smoke")
        return _out("stop", ctx, reason="no-tasks"), ctx

    group, task, last_done, all_done = _position(change)
    ctx.group, ctx.task = group, task
    task_key = task.openspec_id if task is not None else None
    cadence = change.cadence

    # Asks owed for the last finished slice, before anything else moves on.
    # Work already ticked in the next group, or a closed change, shows the run
    # went past them, so a lost state does not ask them again.
    slice_answers = state["slice_answers"] if state["slice_answers"].get("group") == last_done else {}
    moved_on = change.archived or change.status == "DONE" or (
        group is not None
        and any(t.done for t in commands._change_tasks(change) if t.sid == f"S{group:02d}")
    )
    pending_slice: str | None = None
    if last_done is not None and cadence == w2c_local.GIT_DELIVERY_SLICE and not moved_on:
        commit = _ask(slice_answers, "ask-commit")
        if commit is None or commit == "no-answer":
            pending_slice = "ask-commit"
        elif commit == "yes" and environment.ephemeral_reason() is not None:
            if _ask(slice_answers, "ask-push") in (None, "no-answer"):
                pending_slice = "ask-push"
    if pending_slice is not None:
        ctx.group, ctx.task, task_key = last_done, None, None

    # Rule 3: smoke for this change and task.
    smoke = state.get("smoke") or {}
    smoked = smoke.get("change") == change.name and smoke.get("task") == task_key
    ctx.recordable.add("smoke")
    if not smoked:
        return _out("smoke", ctx), ctx
    if smoke.get("result") != "pass":
        return _out("stop", ctx, reason="smoke"), ctx

    # Rule 4: the branch is checked on every call.
    from w2c import ledger_store

    wanted = ledger.remote_branch(change)
    if wanted and ledger_store.current_branch(root) != wanted:
        ctx.recordable.add("isolate")
        if state.get("isolate") == "fail":
            return _out("stop", ctx, reason="isolate"), ctx
        return _out("isolate", ctx), ctx

    if pending_slice is not None:
        ctx.ask_scope, ctx.ask_group = "slice", last_done
        return _ask_out(ctx, pending_slice, _ask(slice_answers, pending_slice))

    if not all_done:
        sid = f"S{group:02d}"
        if task is not None:
            return _task_step(root, change, ctx, state, task, tasks_md)
        in_group = [t for t in commands._change_tasks(change) if t.sid == sid]
        if not in_group:
            return _out("stop", ctx, reason=f"empty-group:{sid}"), ctx
        missing = [
            _report_path(root, change, key, sid)
            for key in ("slice_uat", "slice_summary") if not _present(change, key, sid)
        ]
        if missing:
            ctx.recordable.add("slice-reports")
            return _out("slice-reports", ctx, missing), ctx
        ctx.recordable.add("slice-complete")
        return _out("slice-complete", ctx, [_rel(root, change.path / ".openspec.yaml")]), ctx

    # Rule 8: every group is done.
    ctx.group = None
    answers = state["milestone_answers"]
    closed = change.archived or change.status == "DONE"
    if not closed:
        missing = [
            _report_path(root, change, key)
            for key in ("validation", "summary") if not _present(change, key)
        ]
        if missing:
            ctx.recordable.add("milestone-reports")
            return _out("milestone-reports", ctx, missing), ctx
    ctx.ask_scope = "milestone"
    archive = _ask(answers, "ask-archive")
    if change.archived:
        archive = "yes"
    elif change.status == "DONE" and change.archive == "declined":
        archive = "no"
    if archive in (None, "no-answer"):
        return _ask_out(ctx, "ask-archive", archive, [_rel(root, change.path)])
    if not closed:
        reason = "archive-not-applied" if archive == "yes" else "decline-not-applied"
        ctx.recordable.add("ask-archive")
        return _out("ask-archive", ctx, [_rel(root, change.path)], reason=reason), ctx
    if cadence == w2c_local.GIT_DELIVERY_MILESTONE:
        commit = _ask(answers, "ask-commit")
        if commit in (None, "no-answer"):
            return _ask_out(ctx, "ask-commit", commit)
    push = _ask(answers, "ask-push")
    if push in (None, "no-answer"):
        return _ask_out(ctx, "ask-push", push)
    if push == "yes":
        pr = _ask(answers, "ask-pr")
        if pr in (None, "no-answer"):
            return _ask_out(ctx, "ask-pr", pr)
    return _out("done", ctx), ctx


def _ask_out(ctx: Context, action: str, answer: str | None,
             files: list[str] | None = None) -> tuple[dict, Context]:
    ctx.recordable.add(action)
    if answer == "no-answer":
        return _out("stop", ctx, reason=f"approval-needed:{action}"), ctx
    return _out(action, ctx, files), ctx


def _task_step(root: Path, change: ledger.CloudChange, ctx: Context, state: dict, task,
               tasks_md: Path) -> tuple[dict, Context]:
    fresh = state.get("task") != task.openspec_id
    last = None if fresh else state.get("stage_action")
    result = None if fresh else state.get("stage_result")
    summary = _report_path(root, change, "task_summary", task.sid, task.tid)
    if last is None or (last == "implement" and result != "pass") \
            or (last in ("verify", "review") and result != "pass"):
        action = "implement"
    elif last == "implement":
        action = "verify"
    elif last == "verify":
        action = "review"
    elif last == "review":
        action = "write-report"
    elif last == "write-report":
        written = result == "pass" and _present(change, "task_summary", task.sid, task.tid)
        action = "complete" if written else "write-report"
    else:  # complete recorded but the box is not ticked
        action = "complete"
    ctx.recordable.add(action)
    files = [summary] if action == "write-report" else [_rel(root, tasks_md)]
    return _out(action, ctx, files), ctx


def _rank(change: ledger.CloudChange) -> int:
    status = change.amend_prior_status if change.amend_lock else change.status
    return 0 if status == "INPROGRESS" else 1


def _candidates(root: Path) -> list[ledger.CloudChange]:
    names = ledger.branch_names(root)
    found = []
    for change in ledger.list_changes(root):
        if names is not None and change.name not in names:
            continue
        if change.status == "DONE":
            continue
        if not change.amend_lock and change.status not in RUNNABLE:
            continue
        if not commands._change_tasks(change):
            continue
        found.append(change)
    return sorted(found, key=_rank)


def _plan(root: Path, change: str | None) -> tuple[dict, Context]:
    if change:
        item = ledger.resolve(root, change)
        return _evaluate(root, item, _state_for(root, item.name))
    state = load_state(root)
    finished: str | None = None
    if state is not None and state.get("change"):
        try:
            item = ledger.resolve(root, state["change"])
        except Exception:  # noqa: BLE001 - a vanished change means a fresh start
            item = None
        if item is not None:
            out, ctx = _evaluate(root, item, _state_for(root, item.name))
            if out["action"] != "done":
                return out, ctx
            finished = item.name
    for item in _candidates(root):
        if item.name == finished:
            continue
        return _evaluate(root, item, _state_for(root, item.name))
    ctx = Context()
    out = _out("done", ctx)
    out["change"] = finished
    return out, ctx


def _where(out: dict, ctx: Context) -> dict:
    """The context a record applies to, kept as `expected` in the state."""
    return {
        "action": out["action"],
        "task": ctx.task.openspec_id if ctx.task is not None else None,
        "ask_scope": ctx.ask_scope,
        "ask_group": ctx.ask_group,
        "recordable": sorted(ctx.recordable),
    }


def next_action(root: Path, change: str | None) -> dict:
    """Exactly one next action: keys action, change, slice, task, files, reason.

    The action and what may be recorded for it are kept in the state, so the
    agent can record an action after doing it even when the files on disk
    already moved the driver on (a ticked box, an archived change)."""
    out, ctx = _plan(root, change)
    if ctx.change is not None:
        state = _state_for(root, ctx.change.name)
        state["expected"] = _where(out, ctx)
        _save_state(root, state)
    return out


def record(root: Path, action: str, result: str, change: str | None = None) -> None:
    """Store the result of the action the driver asked for. Raises W2CError and
    changes nothing on an invalid combination."""
    cli = _cli()
    if action in WORK_ACTIONS:
        allowed: tuple[str, ...] = WORK_RESULTS
    elif action in ASK_ACTIONS:
        allowed = ASK_RESULTS
    else:
        known = ", ".join(sorted(WORK_ACTIONS | ASK_ACTIONS))
        raise cli.W2CError(f"cannot record {action!r}; record one of: {known}")
    if result not in allowed:
        raise cli.W2CError(f"{action} takes --result {'|'.join(allowed)}, not {result!r}")
    out, ctx = _plan(root, change)
    where: dict | None = None
    name: str | None = None
    if ctx.change is not None and action in ctx.recordable:
        where, name = _where(out, ctx), ctx.change.name
    else:
        saved = load_state(root)
        expected = saved.get("expected") if saved else None
        if expected and action in expected["recordable"] and saved["change"] and (
            change is None or ledger.resolve(root, change).name == saved["change"]
        ):
            where, name = expected, saved["change"]
    if where is None or name is None:
        if ctx.change is None:
            raise cli.W2CError("no active cloud change to record a step for")
        raise cli.W2CError(f"step expects {out['action']}, not {action}; run w2c cloud step")
    state = _state_for(root, name)
    task_key = where["task"]
    if state.get("task") != task_key:
        state["task"] = task_key
        state["stage_action"] = state["stage_result"] = None
    state["isolate"] = result if action == "isolate" else None
    if action == "smoke":
        state["smoke"] = {"change": name, "task": task_key, "result": result}
    elif action in TASK_STAGES:
        state["stage_action"], state["stage_result"] = action, result
    elif action in ASK_ACTIONS:
        if where["ask_scope"] == "slice":
            answers = state["slice_answers"]
            if answers.get("group") != where["ask_group"]:
                answers = {"group": where["ask_group"]}
            answers[action] = result
            state["slice_answers"] = answers
        else:
            state["milestone_answers"][action] = result
    state["change"] = name
    state["last_action"], state["last_result"] = action, result
    state["expected"] = None
    _save_state(root, state)


# --------------------------------------------------------------------------- brief


def _section(text: str, heading: str) -> str:
    title = heading.removeprefix("## ")
    body = _cli().section_under_heading(text, title)
    return f"{heading}\n{body.rstrip()}" if body is not None else f"{heading}\n\n(missing)"


def brief(root: Path, change: str | None) -> str:
    """The three delivery sections, the current group's slice fields, and the
    current task line with its Verify line. Nothing else. The current task is
    the one `step` works on; while a gate or ask is pending there is none."""
    cli = _cli()
    ctx = _plan(root, change)[1]
    item = ctx.change
    if item is None:
        raise cli.W2CError("no active cloud change on this branch")
    design = item.path / "design.md"
    text = design.read_text(encoding="utf-8") if design.is_file() else ""
    parts = [_section(text, heading) for heading in layout.DESIGN_HEADINGS[:3]]
    group, task = ctx.group, ctx.task
    if task is None or group is None:
        parts.append("No open task.")
        return "\n\n".join(parts) + "\n"
    tasks_text = (item.path / "tasks.md").read_text(encoding="utf-8")
    fields = checks.slice_fields(tasks_text).get(group, {})
    parts.append("\n".join(f"**{name}:** {fields.get(name, '')}".rstrip() for name in layout.SLICE_FIELDS))
    lines = tasks_text.splitlines()
    block: list[str] = []
    for index, line in enumerate(lines):
        match = osl.TASK_RE.match(line)
        if match and f"{match.group('major')}.{match.group('minor')}" == task.openspec_id:
            block.append(line)
            for follow in lines[index + 1 : index + 8]:
                if osl.VERIFY_RE.match(follow):
                    block.append(follow)
                    break
                if osl.TASK_RE.match(follow) or follow.startswith("## "):
                    break
            break
    parts.append("\n".join(block))
    return "\n\n".join(parts) + "\n"


# --------------------------------------------------------------------------- commands


def step_cmd(root: Path, change: str | None, as_json: bool, action: str | None,
             result: str | None) -> int:
    cli = _cli()
    if (action is None) != (result is None):
        raise cli.W2CError("pass --record ACTION and --result RESULT together")
    if action is not None:
        assert result is not None
        record(root, action, result, change)
        print(f"recorded {action} {result}")
        return 0
    out = next_action(root, change)
    if as_json:
        print(json.dumps(out))
        return 0
    print("STEP " + " ".join(str(out[k]) if out[k] is not None else "-"
                             for k in ("action", "change", "slice", "task")))
    if out["reason"]:
        print(f"reason: {out['reason']}")
    return 0


def brief_cmd(root: Path, change: str | None) -> int:
    print(brief(root, change), end="")
    return 0
