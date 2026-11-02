"""Amendments of open work in a cloud change.

The lock lives in the change's `x-delivery-amend-*` keys. Records go under
`## Amendments` in the change's design.md; decisions are checked against its
`## Decisions` table. The CLI package is imported lazily.
"""

from __future__ import annotations

import re
from pathlib import Path

from w2c import amend as legacy
from w2c import openspec_ledger as osl
from w2c.cloud import checks, commands, layout, ledger

BLOCK_RE = re.compile(legacy.BLOCK_RE.pattern.replace("^## ", "^### ", 1), re.M)
HEADING_RE = re.compile(r"^## Amendments[ \t]*$", re.M)
HEADING = "## Amendments"
TASK_START_RE = osl.TASK_RE


def _cli():
    from w2c import cli as w2c_cli

    return w2c_cli


def _design(change: ledger.CloudChange) -> Path:
    return change.path / "design.md"


def _decision(change: ledger.CloudChange, decision: str) -> str:
    cli = _cli()
    did = decision.strip().upper()
    if not re.fullmatch(r"D\d+", did):
        raise cli.W2CError(f"invalid decision id {decision}")
    path = _design(change)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    span = commands._decisions_span(text)
    body = text[span[0]:span[1]] if span else ""
    if not re.search(rf"^\|\s*{re.escape(did)}\s*\|", body, re.M):
        raise cli.W2CError(f"decision {did} not found in {change.name} design.md")
    return did


def _held(change: ledger.CloudChange, decision: str) -> None:
    cli = _cli()
    if not change.amend_lock:
        raise cli.W2CError(f"amend lock is not held for {change.name}")
    if change.amend_lock != decision or change.amend_decision != decision:
        raise cli.W2CError(f"decision {decision} does not match the amendment lock")


def _locked(root: Path, name: str, decision: str) -> tuple[ledger.CloudChange, str]:
    change = commands._active(root, name)
    did = _decision(change, decision)
    _held(change, did)
    return change, did


def _section(text: str) -> tuple[int, int] | None:
    match = HEADING_RE.search(text)
    if not match:
        return None
    nxt = re.search(r"^## ", text[match.end():], re.M)
    return match.end(), match.end() + nxt.start() if nxt else len(text)


def _records(text: str) -> str:
    span = _section(text)
    return text[span[0]:span[1]] if span else ""


def _next_amend_id(text: str) -> str:
    nums = [int(item) for item in re.findall(r"^### A(\d+)\b", _records(text), re.M)]
    return f"A{(max(nums) + 1) if nums else 1:03d}"


def _target(name: str, sid: str, tid: str | None = None) -> str:
    return f"{name}/{sid}/{tid}" if tid else f"{name}/{sid}"


def _append(change, kind, target, decision, reason, follow_up="", ticket="") -> None:
    path = _design(change)
    text = path.read_text(encoding="utf-8")
    block = (
        f"### {_next_amend_id(text)} {kind} {target}\n\n"
        f"- decision: {decision}\n"
        f"- reason: {reason}\n"
        f"- follow-up: {follow_up}\n"
        f"- ticket: {ticket}\n"
    )
    span = _section(text)
    if span is None:
        new = text.rstrip("\n") + f"\n\n{HEADING}\n\n" + block
    else:
        start, end = span
        rest = text[end:]
        new = text[:start] + text[start:end].rstrip("\n") + "\n\n" + block + ("\n" + rest if rest else "")
    _cli().atomic_write(path, new)


def _count_decision(text: str, decision: str) -> int:
    return len(re.findall(rf"^- decision: {re.escape(decision)}$", _records(text), re.M))


def _matches(text: str, target: str) -> list[re.Match]:
    span = _section(text)
    if span is None:
        return []
    found = [m for m in BLOCK_RE.finditer(text, span[0], span[1]) if m.group(3) == target]
    return found


def _tasks(change: ledger.CloudChange, sid: str) -> list:
    return [t for t in commands._change_tasks(change) if t.sid == sid]


def _group(change: ledger.CloudChange, sid: str) -> int:
    number = int(sid[1:])
    if number not in osl.group_numbers(commands._tasks_path(change)):
        raise _cli().W2CError(f"unknown slice {change.name} {sid}")
    return number


def _find_task(change: ledger.CloudChange, sid: str, tid: str):
    _group(change, sid)
    found = [t for t in _tasks(change, sid) if t.tid == tid or t.openspec_id == tid]
    if not found:
        raise _cli().W2CError(f"unknown task {change.name} {sid} {tid}")
    return found[0]


def _opt_line(value: str, label: str) -> str:
    return legacy._one_line(value, label) if value.strip() else ""


def _event(root: Path, change: ledger.CloudChange, detail: str, sid=None, tid=None) -> None:
    commands._event(root, stage="amend", event="complete", milestone=change.name,
                    slice_id=sid, task_id=tid, detail=detail)


def _slice_hint(change: ledger.CloudChange, sid: str) -> None:
    tasks = _tasks(change, sid)
    if any(commands._is_open(t) for t in tasks):
        return
    if any(t.done for t in tasks):
        if commands._present(change, "slice_uat", sid) and commands._present(change, "slice_summary", sid):
            print(f"NEED_SLICE_COMPLETE {sid}")
        else:
            print(f"NEED_SLICE_REPORTS {sid}")
        return
    print(f"NEED_DROP_SLICE {sid}")


def amend_begin(root: Path, name: str, decision: str) -> int:
    cli = _cli()
    change = commands._active(root, name)
    did = _decision(change, decision)
    if change.amend_lock:
        raise cli.W2CError(f"amend lock already held for {change.name}")
    if change.status in legacy.CLOSED:
        raise cli.W2CError(f"{change.name} is {change.status}; amendments are refused")
    meta = commands._meta(change)
    ledger.write_key(meta, "x-delivery-amend-lock", did)
    ledger.write_key(meta, "x-delivery-amend-prior-status", change.status)
    ledger.write_key(meta, "x-delivery-amend-decision", did)
    if change.status == "INPROGRESS":
        ledger.write_key(meta, "x-delivery-status", "PAUSED")
    _event(root, change, f"amend-begin {change.name} {did}")
    print(f"amend-begin {change.name}")
    return 0


def amend_end(root: Path, name: str) -> int:
    cli = _cli()
    change = commands._active(root, name)
    if not change.amend_lock:
        raise cli.W2CError(f"amend lock is not held for {change.name}")
    failing = [row for row in checks.smoke_rows(root, [change]) if row[1] == "FAIL"]
    if failing:
        for check, _status, detail in failing:
            print(f"FAIL {check}: {detail}")
        print(f"amend-end refused {change.name}")
        return 1
    design = _design(change)
    text = design.read_text(encoding="utf-8") if design.is_file() else ""
    prior = change.amend_prior_status
    desired = "PAUSED" if _count_decision(text, change.amend_decision) and prior == "INPROGRESS" else prior
    if desired not in ledger.STATUSES:
        raise cli.W2CError(f"saved status {prior!r} cannot be restored")
    meta = commands._meta(change)
    ledger.write_key(meta, "x-delivery-status", desired)
    for key in ("lock", "prior-status", "decision"):
        ledger.write_key(meta, f"x-delivery-amend-{key}", None)
    _event(root, change, f"amend-end {change.name} {desired}")
    print(f"amend-end {change.name} {desired}")
    return 0


def amendments(root: Path, name: str) -> int:
    change = commands._active(root, name)
    design = _design(change)
    text = _records(design.read_text(encoding="utf-8")) if design.is_file() else ""
    if not text.strip():
        print(f"amendments {change.name} none")
        return 0
    print(text.strip("\n"))
    return 0


def drop_task(root, name, sid, tid, reason, decision, follow_up="", ticket="") -> int:
    cli = _cli()
    sid, tid = legacy._sid(sid), legacy._tid(tid)
    change, did = _locked(root, name, decision)
    reason = legacy._one_line(reason, "reason")
    follow = _opt_line(follow_up, "follow-up")
    link = legacy._ticket(ticket)
    task = _find_task(change, sid, tid)
    if task.done:
        raise cli.W2CError(f"refusing to drop finished task {task.tid}")
    if task.dropped:
        raise cli.W2CError(f"{task.tid} is already dropped")
    _mark(task, "d")
    _append(change, "drop-task", _target(change.name, sid, task.tid), did, reason, follow, link)
    _event(root, change, f"drop-task {change.name} {sid} {task.tid}", sid, task.tid)
    print(f"drop-task {change.name} {sid} {task.tid}")
    _slice_hint(change, sid)
    return 0


def _mark(task, mark: str) -> None:
    cli = _cli()
    path = task.plan_path
    cli.atomic_write(path, osl.set_task_mark(cli.read_text(path), task.openspec_id, mark))


def drop_slice(root, name, sid, reason, decision, follow_up="", ticket="") -> int:
    cli = _cli()
    sid = legacy._sid(sid)
    change, did = _locked(root, name, decision)
    reason = legacy._one_line(reason, "reason")
    follow = _opt_line(follow_up, "follow-up")
    link = legacy._ticket(ticket)
    _group(change, sid)
    tasks = _tasks(change, sid)
    if tasks and all(t.dropped for t in tasks):
        raise cli.W2CError(f"{sid} is already dropped")
    finished = [t.tid for t in tasks if t.done]
    if finished:
        raise cli.W2CError(f"refusing to drop {sid}; finished tasks: {', '.join(finished)}")
    for task in tasks:
        _mark(task, "d")
    _append(change, "drop-slice", _target(change.name, sid), did, reason, follow, link)
    _event(root, change, f"drop-slice {change.name} {sid}", sid)
    print(f"drop-slice {change.name} {sid}")
    return 0


def _insert_task(text: str, major: int, minor: int, title: str, verify: str) -> str:
    block = [f"- [ ] {major}.{minor} {title}\n", f"  - Verify: {verify}\n"]
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if re.match(rf"^## {major}\.", line)), None)
    if start is None:
        raise _cli().W2CError(f"tasks.md group {major} missing")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    last = None
    for i in range(start + 1, end):
        if TASK_START_RE.match(lines[i]):
            last = i
    if last is None:
        at = end
        while at > start + 1 and not lines[at - 1].strip():
            at -= 1
        block.insert(0, "\n")
    else:
        at = last + 1
        while at < end and lines[at].strip() and not TASK_START_RE.match(lines[at]) and lines[at][:1].isspace():
            at += 1
    if at > 0 and not lines[at - 1].endswith("\n"):
        lines[at - 1] += "\n"
    return "".join(lines[:at] + block + lines[at:])


def task_add(root, name, sid, title, verify, reason, decision) -> int:
    cli = _cli()
    sid = legacy._sid(sid)
    change, did = _locked(root, name, decision)
    title = legacy._one_line(title, "title")
    verify = legacy._one_line(verify, "verify")
    reason = legacy._one_line(reason, "reason")
    number = _group(change, sid)
    tasks = _tasks(change, sid)
    if tasks and all(t.dropped for t in tasks):
        raise cli.W2CError(f"{sid} is dropped")
    minor = max((int(t.tid[1:]) for t in tasks), default=0) + 1
    tid = f"T{minor:02d}"
    path = commands._tasks_path(change)
    cli.atomic_write(path, _insert_task(cli.read_text(path), number, minor, title, verify))
    _append(change, "task-add", _target(change.name, sid, tid), did, reason)
    _event(root, change, f"task-add {change.name} {sid} {tid}", sid, tid)
    print(f"task-add {change.name} {sid} {tid}")
    return 0


def task_edit(root, name, sid, tid, title, verify, reason, decision) -> int:
    cli = _cli()
    sid, tid = legacy._sid(sid), legacy._tid(tid)
    change, did = _locked(root, name, decision)
    title = legacy._one_line(title, "title")
    verify = legacy._one_line(verify, "verify")
    reason = legacy._one_line(reason, "reason")
    task = _find_task(change, sid, tid)
    if task.done:
        raise cli.W2CError(f"refusing to edit finished task {task.tid}")
    if task.dropped:
        raise cli.W2CError(f"refusing to edit dropped task {task.tid}")
    major, minor = task.openspec_id.split(".", 1)
    header = re.compile(
        rf"^(\s*(?:[-*+]|\d{{1,9}}[.)])\s+\[[ xXdD]\]\s+{re.escape(major)}\.{re.escape(minor)})\b"
    )
    text = cli.read_text(task.plan_path)
    cli.atomic_write(task.plan_path, legacy._edit_task_text(text, header, title, verify))
    _append(change, "task-edit", _target(change.name, sid, task.tid), did, reason)
    _event(root, change, f"task-edit {change.name} {sid} {task.tid}", sid, task.tid)
    print(f"task-edit {change.name} {sid} {task.tid}")
    return 0


def slice_add(root, name, title, reason, decision) -> int:
    cli = _cli()
    change, did = _locked(root, name, decision)
    title = legacy._one_line(title, "title")
    reason = legacy._one_line(reason, "reason")
    path = commands._tasks_path(change)
    if not path.is_file():
        raise cli.W2CError(f"{change.name}: tasks.md missing")
    number = max(osl.group_numbers(path), default=0) + 1
    sid = f"S{number:02d}"
    body = cli.read_text(path)
    if not body.endswith("\n"):
        body += "\n"
    fields = "".join(f"**{field}:**\n" for field in layout.SLICE_FIELDS)
    cli.atomic_write(path, body + f"\n## {number}. {title}\n\n{fields}")
    _append(change, "slice-add", _target(change.name, sid), did, reason)
    _event(root, change, f"slice-add {change.name} {sid}", sid)
    print(f"slice-add {change.name} {sid}")
    return 0


def follow_up(root, name, sid, ticket, tid=None) -> int:
    cli = _cli()
    sid = legacy._sid(sid)
    task_id = legacy._tid(tid) if tid else None
    link = legacy._ticket(ticket)
    if not link:
        raise cli.W2CError("ticket link is empty")
    change = commands._active(root, name)
    path = _design(change)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    target = _target(change.name, sid, task_id)
    found = _matches(text, target)
    if not found:
        raise cli.W2CError(f"no amendment for {target}")
    last = found[-1]
    cli.atomic_write(path, text[: last.start(7)] + link + text[last.end(7):])
    _event(root, change, f"follow-up {target}", sid, task_id)
    print(f"follow-up {target}")
    return 0
