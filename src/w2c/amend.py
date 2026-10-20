"""In-place milestone amendments. The CLI is the only writer of these records."""
from __future__ import annotations

import re
from pathlib import Path

from w2c import local as w2c_local
from w2c import openspec_ledger

CLOSED = frozenset({"DONE", "STOP", "ERROR"})
AMENDABLE = frozenset({"PLANNING", "TODO", "PAUSED", "INPROGRESS"})
HEADER = (
    "# Amendments\n\n"
    "The w2c command is the only writer of this file.\n"
)
BLOCK_RE = re.compile(
    r"^## (A\d+) (\S+) (\S+)\n\n"
    r"- decision: (\S+)\n"
    r"- reason: (.*)\n"
    r"- follow-up: (.*)\n"
    r"- ticket: (.*)\n",
    re.M,
)


def _cli():
    from w2c import cli as w2c_cli

    return w2c_cli


def _one_line(value: str, label: str) -> str:
    text = " ".join(value.split())
    if not text:
        raise _cli().W2CError(f"{label} is empty")
    return text


def _ticket(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if any(ch.isspace() for ch in text):
        raise _cli().W2CError("ticket link must be one token")
    return text


def _sid(raw: str) -> str:
    text = raw.strip().upper()
    if not re.fullmatch(r"S\d+", text):
        raise _cli().W2CError(f"invalid slice id {raw}")
    return text


def _tid(raw: str) -> str:
    text = raw.strip().upper()
    if not re.fullmatch(r"T\d+", text):
        raise _cli().W2CError(f"invalid task id {raw}")
    return text


def _milestone(root: Path, mid: str):
    cli = _cli()
    mils = cli.parse_milestones(cli.read_text(cli.w2c_dir(root) / "ROADMAP.md"))
    mil = next((item for item in mils if item.mid == mid), None)
    if mil is None:
        raise cli.W2CError(f"milestone {mid} not found")
    return mil


def _plan(root: Path, mid: str) -> Path:
    cli = _cli()
    plan = cli.plan_dir_for(root, mid)
    if plan is None:
        raise cli.W2CError(f"plan folder not found for {mid}")
    return plan


def _decision(root: Path, decision: str) -> str:
    did = decision.strip().upper()
    if not re.fullmatch(r"D\d+", did):
        raise _cli().W2CError(f"invalid decision id {decision}")
    text = _cli().read_text(_cli().w2c_dir(root) / "DECISIONS.md")
    if not re.search(rf"^\| {re.escape(did)} \|", text, re.M):
        raise _cli().W2CError(f"decision {did} not found")
    return did


def _held(root: Path, mid: str, decision: str) -> dict:
    cfg = w2c_local.load_repo_config(root)
    if str(cfg.get("amend_lock") or "") != mid:
        raise _cli().W2CError(f"amend lock is not held for {mid}")
    if str(cfg.get("amend_decision") or "") != decision:
        raise _cli().W2CError(f"decision {decision} does not match the amendment lock")
    return cfg


def _amendments_path(plan: Path, mid: str) -> Path:
    return plan / f"{mid}-AMENDMENTS.md"


def _next_amend_id(text: str) -> str:
    nums = [int(item) for item in re.findall(r"^## A(\d+)\b", text, re.M)]
    return f"A{(max(nums) + 1) if nums else 1:03d}"


def _append(
    root: Path,
    mid: str,
    kind: str,
    target: str,
    decision: str,
    reason: str,
    follow_up: str = "",
    ticket: str = "",
) -> None:
    cli = _cli()
    path = _amendments_path(_plan(root, mid), mid)
    text = cli.read_text(path)
    if not text.strip():
        text = HEADER
    if not text.endswith("\n"):
        text += "\n"
    block = (
        f"\n## {_next_amend_id(text)} {kind} {target}\n\n"
        f"- decision: {decision}\n"
        f"- reason: {reason}\n"
        f"- follow-up: {follow_up}\n"
        f"- ticket: {ticket}\n"
    )
    cli.atomic_write(path, text + block)


def _count_decision(text: str, decision: str) -> int:
    return len(re.findall(rf"^- decision: {re.escape(decision)}$", text, re.M))


def _set_ticket(text: str, target: str, ticket: str) -> str:
    matches = [item for item in BLOCK_RE.finditer(text) if item.group(3) == target]
    if not matches:
        raise _cli().W2CError(f"no amendment for {target}")
    found = matches[-1]
    return text[: found.start(7)] + ticket + text[found.end(7) :]


def _tasks(root: Path, mid: str, sid: str) -> list:
    return openspec_ledger.tasks_in_slice(root, mid, sid, _plan(root, mid))


def _find_task(root: Path, mid: str, sid: str, tid: str):
    match = [task for task in _tasks(root, mid, sid) if task.tid == tid or task.openspec_id == tid]
    if not match:
        raise _cli().W2CError(f"unknown task {mid} {sid} {tid}")
    return match[0]


def _slice(root: Path, mid: str, sid: str):
    cli = _cli()
    text = cli.read_text(_plan(root, mid) / f"{mid}-ROADMAP.md")
    found = next((item for item in cli.parse_slices(text) if item.sid == sid), None)
    if found is None:
        raise cli.W2CError(f"unknown slice {mid} {sid}")
    return found


def _write_task_mark(task, mark: str) -> None:
    cli = _cli()
    text = cli.read_text(task.plan_path)
    if task.openspec_id:
        updated = openspec_ledger.set_task_mark(text, task.openspec_id, mark)
    else:
        updated = cli.set_task_mark(text, task.tid, mark)
    cli.atomic_write(task.plan_path, updated)


def _write_slice_mark(root: Path, mid: str, sid: str, mark: str) -> None:
    cli = _cli()
    path = _plan(root, mid) / f"{mid}-ROADMAP.md"
    cli.atomic_write(path, cli.set_slice_mark(cli.read_text(path), sid, mark))


def _roadmap_text(root: Path, mid: str) -> str:
    cli = _cli()
    return cli.read_text(_plan(root, mid) / f"{mid}-ROADMAP.md")


def _openspec(root: Path, mid: str) -> bool:
    return openspec_ledger.planning_mode(_roadmap_text(root, mid)) == w2c_local.PLANNING_OPENSPEC


def _tasks_path(root: Path, mid: str) -> Path | None:
    if not _openspec(root, mid):
        return None
    text = _roadmap_text(root, mid)
    folder = openspec_ledger.change_dir(
        root, openspec_ledger.change_name(text), openspec_ledger.archive_value(text)
    )
    path = folder / "tasks.md" if folder is not None else None
    if path is None or not path.is_file():
        raise _cli().W2CError(f"{mid}: tasks.md missing")
    return path


def _event(root: Path, mid: str, detail: str, sid: str | None = None, tid: str | None = None) -> None:
    _cli().append_event(
        root,
        skill="w2c",
        stage="amend",
        event="complete",
        milestone=mid,
        slice_id=sid,
        task_id=tid,
        detail=detail,
    )


def _slice_hint(root: Path, mid: str, sid: str) -> None:
    cli = _cli()
    tasks = _tasks(root, mid, sid)
    if any(cli.task_is_open(task) for task in tasks):
        return
    if any(task.done for task in tasks):
        plan = _plan(root, mid)
        if cli.report_present(cli.slice_uat_path(plan, sid)) and cli.report_present(
            cli.slice_summary_path(plan, sid)
        ):
            print(f"NEED_SLICE_COMPLETE {sid}")
        else:
            print(f"NEED_SLICE_REPORTS {sid}")
        return
    print(f"NEED_DROP_SLICE {sid}")


def _target(mid: str, sid: str, tid: str | None = None) -> str:
    if tid:
        return f"{mid}/{sid}/{tid}"
    return f"{mid}/{sid}"


def cmd_amend_begin(root: Path, mid: str, decision: str) -> int:
    cli = _cli()
    mid = cli.canonical_mid(mid)
    decision = _decision(root, decision)
    cfg = w2c_local.load_repo_config(root)
    if str(cfg.get("amend_lock") or ""):
        raise cli.W2CError(f"amend lock already held for {cfg['amend_lock']}")
    mil = _milestone(root, mid)
    if mil.status not in AMENDABLE:
        raise cli.W2CError(f"{mid} is {mil.status}; amendments are refused")
    _plan(root, mid)
    w2c_local.write_repo_config(
        root,
        schema_version=3,
        amend_update={
            "amend_lock": mid,
            "amend_prior_status": mil.status,
            "amend_decision": decision,
        },
    )
    if mil.status == "INPROGRESS":
        road = cli.w2c_dir(root) / "ROADMAP.md"
        cli.atomic_write(
            road,
            cli.set_milestone_status_in_roadmap(cli.read_text(road), mid, "PAUSED"),
        )
        cli.rebuild_ledger(root)
    _event(root, mid, f"amend-begin {mid} {decision}")
    print(f"amend-begin {mid}")
    return 0


def cmd_amend_end(root: Path, mid: str) -> int:
    cli = _cli()
    mid = cli.canonical_mid(mid)
    cfg = w2c_local.load_repo_config(root)
    if str(cfg.get("amend_lock") or "") != mid:
        raise cli.W2CError(f"amend lock is not held for {mid}")
    if cli.cmd_smoke(root) != 0:
        print(f"amend-end refused {mid}")
        return 1
    text = cli.read_text(_amendments_path(_plan(root, mid), mid))
    count = _count_decision(text, str(cfg.get("amend_decision") or ""))
    prior = str(cfg.get("amend_prior_status") or "")
    desired = "PAUSED" if count and prior == "INPROGRESS" else prior
    if desired not in cli.STATUS_EMOJI:
        raise cli.W2CError(f"saved status {prior!r} cannot be restored")
    road = cli.w2c_dir(root) / "ROADMAP.md"
    cli.atomic_write(
        road, cli.set_milestone_status_in_roadmap(cli.read_text(road), mid, desired)
    )
    w2c_local.write_repo_config(root, schema_version=3, amend_update={})
    cli.rebuild_ledger(root)
    _event(root, mid, f"amend-end {mid} {desired}")
    print(f"amend-end {mid} {desired}")
    return 0


def cmd_drop_task(
    root: Path,
    mid: str,
    sid: str,
    tid: str,
    reason: str,
    decision: str,
    follow_up: str = "",
    ticket: str = "",
) -> int:
    cli = _cli()
    mid = cli.canonical_mid(mid)
    sid = _sid(sid)
    tid = _tid(tid)
    decision = _decision(root, decision)
    _held(root, mid, decision)
    reason = _one_line(reason, "reason")
    follow = _one_line(follow_up, "follow-up") if follow_up.strip() else ""
    link = _ticket(ticket)
    task = _find_task(root, mid, sid, tid)
    if task.done:
        raise cli.W2CError(f"refusing to drop finished task {task.tid}")
    if task.dropped:
        raise cli.W2CError(f"{task.tid} is already dropped")
    _write_task_mark(task, "d")
    _append(
        root,
        mid,
        "drop-task",
        _target(mid, sid, task.tid),
        decision,
        reason,
        follow,
        link,
    )
    _event(root, mid, f"drop-task {mid} {sid} {task.tid}", sid, task.tid)
    print(f"drop-task {mid} {sid} {task.tid}")
    _slice_hint(root, mid, sid)
    return 0


def cmd_drop_slice(
    root: Path,
    mid: str,
    sid: str,
    reason: str,
    decision: str,
    follow_up: str = "",
    ticket: str = "",
) -> int:
    cli = _cli()
    mid = cli.canonical_mid(mid)
    sid = _sid(sid)
    decision = _decision(root, decision)
    _held(root, mid, decision)
    reason = _one_line(reason, "reason")
    follow = _one_line(follow_up, "follow-up") if follow_up.strip() else ""
    link = _ticket(ticket)
    sl = _slice(root, mid, sid)
    if sl.dropped:
        raise cli.W2CError(f"{sid} is already dropped")
    tasks = _tasks(root, mid, sid)
    finished = [task.tid for task in tasks if task.done]
    if finished:
        raise cli.W2CError(
            f"refusing to drop {sid}; finished tasks: {', '.join(finished)}"
        )
    for task in tasks:
        if not task.dropped:
            _write_task_mark(task, "d")
    _write_slice_mark(root, mid, sid, "d")
    _append(root, mid, "drop-slice", _target(mid, sid), decision, reason, follow, link)
    _event(root, mid, f"drop-slice {mid} {sid}", sid)
    print(f"drop-slice {mid} {sid}")
    return 0


def _next_numbers(tasks: list) -> tuple[str, int]:
    nums = [int(task.tid[1:]) for task in tasks]
    minor = (max(nums) + 1) if nums else 1
    return f"T{minor:02d}", minor


def cmd_task_add(
    root: Path,
    mid: str,
    sid: str,
    title: str,
    verify: str,
    reason: str,
    decision: str,
) -> int:
    cli = _cli()
    mid = cli.canonical_mid(mid)
    sid = _sid(sid)
    decision = _decision(root, decision)
    _held(root, mid, decision)
    title = _one_line(title, "title")
    verify = _one_line(verify, "verify")
    reason = _one_line(reason, "reason")
    _slice(root, mid, sid)
    if _slice(root, mid, sid).dropped:
        raise cli.W2CError(f"{sid} is dropped")
    tasks = _tasks(root, mid, sid)
    tid, minor = _next_numbers(tasks)
    if _openspec(root, mid):
        path = _tasks_path(root, mid)
        assert path is not None
        major = int(sid[1:])
        cli.atomic_write(
            path,
            _insert_openspec_task(cli.read_text(path), major, minor, title, verify),
        )
    else:
        path = cli.slice_plan_path(root, mid, sid)
        if path is None:
            raise cli.W2CError(f"slice plan not found for {mid} {sid}")
        cli.atomic_write(path, _insert_classic_task(cli.read_text(path), tid, title, verify))
    _append(root, mid, "task-add", _target(mid, sid, tid), decision, reason)
    _event(root, mid, f"task-add {mid} {sid} {tid}", sid, tid)
    print(f"task-add {mid} {sid} {tid}")
    return 0


def cmd_task_edit(
    root: Path,
    mid: str,
    sid: str,
    tid: str,
    title: str,
    verify: str,
    reason: str,
    decision: str,
) -> int:
    cli = _cli()
    mid = cli.canonical_mid(mid)
    sid = _sid(sid)
    tid = _tid(tid)
    decision = _decision(root, decision)
    _held(root, mid, decision)
    title = _one_line(title, "title")
    verify = _one_line(verify, "verify")
    reason = _one_line(reason, "reason")
    task = _find_task(root, mid, sid, tid)
    if task.done:
        raise cli.W2CError(f"refusing to edit finished task {task.tid}")
    if task.dropped:
        raise cli.W2CError(f"refusing to edit dropped task {task.tid}")
    text = cli.read_text(task.plan_path)
    if task.openspec_id:
        major, minor = task.openspec_id.split(".", 1)
        header = re.compile(
            rf"^(\s*(?:[-*+]|\d{{1,9}}[.)])\s+\[[ xXdD]\]\s+{re.escape(major)}\.{re.escape(minor)})\b"
        )
    else:
        header = re.compile(rf"^(- \[[ xXdD]\] \*\*{re.escape(task.tid)}\*\*:)")
    cli.atomic_write(task.plan_path, _edit_task_text(text, header, title, verify))
    _append(root, mid, "task-edit", _target(mid, sid, task.tid), decision, reason)
    _event(root, mid, f"task-edit {mid} {sid} {task.tid}", sid, task.tid)
    print(f"task-edit {mid} {sid} {task.tid}")
    return 0


def cmd_slice_add(root: Path, mid: str, title: str, reason: str, decision: str) -> int:
    cli = _cli()
    mid = cli.canonical_mid(mid)
    decision = _decision(root, decision)
    _held(root, mid, decision)
    title = _one_line(title, "title")
    reason = _one_line(reason, "reason")
    plan = _plan(root, mid)
    road_path = plan / f"{mid}-ROADMAP.md"
    road = cli.read_text(road_path)
    nums = [int(item.sid[1:]) for item in cli.parse_slices(road)]
    number = (max(nums) + 1) if nums else 1
    sid = f"S{number:02d}"
    cli.atomic_write(road_path, _insert_slice_line(road, sid, title))
    cli.atomic_write(plan / f"{mid}-{sid}-PLAN.md", _slice_plan(mid, sid, title, road, _openspec(root, mid)))
    if _openspec(root, mid):
        tasks = _tasks_path(root, mid)
        assert tasks is not None
        body = cli.read_text(tasks)
        if not body.endswith("\n"):
            body += "\n"
        cli.atomic_write(tasks, body + f"\n## {number}. {title}\n")
    _append(root, mid, "slice-add", _target(mid, sid), decision, reason)
    _event(root, mid, f"slice-add {mid} {sid}", sid)
    print(f"slice-add {mid} {sid}")
    return 0


def cmd_follow_up(root: Path, mid: str, sid: str, ticket: str, tid: str | None = None) -> int:
    cli = _cli()
    mid = cli.canonical_mid(mid)
    sid = _sid(sid)
    task_id = _tid(tid) if tid else None
    link = _ticket(ticket)
    if not link:
        raise cli.W2CError("ticket link is empty")
    path = _amendments_path(_plan(root, mid), mid)
    text = cli.read_text(path)
    target = _target(mid, sid, task_id)
    updated = _set_ticket(text, target, link)
    if _reason_of(text, target) != _reason_of(updated, target):
        raise cli.W2CError("follow-up changed the reason")
    cli.atomic_write(path, updated)
    _event(root, mid, f"follow-up {target}", sid, task_id)
    print(f"follow-up {target}")
    return 0


def cmd_amendments(root: Path, mid: str) -> int:
    cli = _cli()
    mid = cli.canonical_mid(mid)
    text = cli.read_text(_amendments_path(_plan(root, mid), mid))
    if not text.strip():
        print(f"amendments {mid} none")
        return 0
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


def _reason_of(text: str, target: str) -> str:
    matches = [item for item in BLOCK_RE.finditer(text) if item.group(3) == target]
    if not matches:
        raise _cli().W2CError(f"no amendment for {target}")
    return matches[-1].group(5)


def _insert_classic_task(text: str, tid: str, title: str, verify: str) -> str:
    block = f"- [ ] **{tid}**: {title}\n  - Verify: {verify}\n"
    token = "</tasks>"
    if token not in text:
        raise _cli().W2CError("tasks block missing")
    return text.replace(token, block + token, 1)


def _insert_openspec_task(text: str, major: int, minor: int, title: str, verify: str) -> str:
    block = f"- [ ] {major}.{minor} {title}\n  - Verify: {verify}\n"
    match = re.search(rf"^## {major}\. .*$", text, re.M)
    if match is None:
        raise _cli().W2CError(f"tasks.md group {major} missing")
    rest = text[match.end() :]
    nxt = re.search(r"^## ", rest, re.M)
    if nxt:
        at = match.end() + nxt.start()
        return text[:at] + block + text[at:]
    if not text.endswith("\n"):
        text += "\n"
    return text + block


def _insert_slice_line(text: str, sid: str, title: str) -> str:
    line = f"- [ ] **{sid}: {title}**\n"
    matches = list(re.finditer(r"^- \[[ xXdD]\] \*\*S\d+:", text, re.M))
    if matches:
        end = text.find("\n", matches[-1].start())
        if end == -1:
            return text + "\n" + line
        return text[: end + 1] + line + text[end + 1 :]
    heading = re.search(r"^## Slices\s*$", text, re.M)
    if heading is None:
        raise _cli().W2CError("## Slices section missing")
    return text[: heading.end()] + "\n\n" + line + text[heading.end() :]


def _slice_plan(mid: str, sid: str, title: str, roadmap: str, openspec: bool) -> str:
    cli = _cli()
    git = cli.section_under_heading(roadmap, "Git Operation Plan")
    conv = cli.section_under_heading(roadmap, "Commit and PR conventions")
    git_block = "## Git Operation Plan\n" + (git if git is not None else "\n")
    conv_block = "## Commit and PR conventions\n" + (conv if conv is not None else "\n")
    note = (
        "This slice is delivery context only. Task checkboxes live in tasks.md.\n\n"
        if openspec
        else "<tasks>\n</tasks>\n\n"
    )
    return (
        f"---\nMILESTONE ID: {mid}\nSLICE ID: {sid}\n---\n\n"
        f"# {sid}: {title}\n\n**Goal:**\n\n{note}{git_block}\n{conv_block}"
    )


def _edit_task_text(text: str, header: re.Pattern[str], title: str, verify: str) -> str:
    lines = text.splitlines(keepends=True)
    index = None
    matched = None
    for i, line in enumerate(lines):
        found = header.match(line.rstrip("\n"))
        if found:
            index = i
            matched = found
            break
    if index is None or matched is None:
        raise _cli().W2CError("task line not found")
    newline = "\n" if lines[index].endswith("\n") else ""
    lines[index] = matched.group(1) + " " + title + newline
    for follow in range(index + 1, min(index + 8, len(lines))):
        body = lines[follow].rstrip("\n")
        if body.lstrip().startswith("- [") or body.startswith("## "):
            break
        verify_match = re.match(r"^(\s+)- Verify:.*$", body)
        if verify_match:
            end = "\n" if lines[follow].endswith("\n") else ""
            lines[follow] = f"{verify_match.group(1)}- Verify: {verify}{end}"
            return "".join(lines)
    raise _cli().W2CError("Verify line not found")
