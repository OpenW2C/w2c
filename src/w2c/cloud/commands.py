"""Core cloud commands: run one OpenSpec change from committed files only.

State lives in `x-delivery-*` keys of `.openspec.yaml`, the change's own
`design.md` and `tasks.md`, and reports under `<change>/.delivery/`. No file
under `.w2c/` is created here. The CLI package is imported lazily.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from w2c import local as w2c_local
from w2c import openspec as osp
from w2c import openspec_ledger as osl
from w2c.cloud import checks, layout, ledger

KNOWLEDGE_PATH = "openspec/knowledge.md"
ATTRIBUTES_LINE = "openspec/knowledge.md merge=union"
KNOWLEDGE_BODY = """# Project Knowledge

Append-only register of project-specific rules, patterns, and lessons learned.
Agents read this before every unit. Add entries when you discover something worth remembering.

## Rules

| # | Scope | Rule | Why | Added |
|---|-------|------|-----|-------|

## Patterns

| # | Pattern | Where | Notes |
|---|---------|-------|-------|

## Lessons Learned

| # | What Happened | Root Cause | Fix | Scope |
|---|--------------|------------|-----|-------|
"""

FIRST_NEXT = frozenset({"INPROGRESS"})
THEN_NEXT = frozenset({"PLANNING", "TODO"})
START_FROM = frozenset({"PLANNING", "TODO", "PAUSED"})


def _cli():
    from w2c import cli as w2c_cli

    return w2c_cli


def _event(root: Path, **fields: str | None) -> None:
    """Runtime events stay local; never create `.w2c/` just to log one."""
    if (root / ".w2c").is_dir():
        _cli().append_event(root, skill="do-chores", **fields)  # type: ignore[arg-type]


def ensure_knowledge(root: Path) -> list[str]:
    """Create the shared knowledge file and its merge rule when missing."""
    created: list[str] = []
    knowledge = root / KNOWLEDGE_PATH
    if not knowledge.exists():
        _cli().atomic_write(knowledge, KNOWLEDGE_BODY)
        created.append(KNOWLEDGE_PATH)
    attrs = root / ".gitattributes"
    existing = attrs.read_text(encoding="utf-8") if attrs.is_file() else ""
    if ATTRIBUTES_LINE not in existing.splitlines():
        if existing and not existing.endswith("\n"):
            existing += "\n"
        _cli().atomic_write(attrs, existing + ATTRIBUTES_LINE + "\n")
        created.append(".gitattributes")
    return created


def _tasks_path(change: ledger.CloudChange) -> Path:
    return change.path / "tasks.md"


def _change_tasks(change: ledger.CloudChange) -> list:
    path = _tasks_path(change)
    return osl.parse_openspec_tasks(path, change.name) if path.is_file() else []


def cloud_tasks(root: Path) -> list:
    """Every task of every active cloud change, in change order."""
    tasks: list = []
    for change in ledger.list_changes(root):
        tasks += _change_tasks(change)
    return tasks


def _active(root: Path, ident: str) -> ledger.CloudChange:
    change = ledger.resolve(root, ident)
    if change.archived:
        raise _cli().W2CError(f"{change.name} is already archived")
    return change


def _refuse_if_locked(change: ledger.CloudChange) -> None:
    if change.amend_lock:
        raise _cli().W2CError(f"AMEND_LOCK {change.name}")


def _refuse_if_done(change: ledger.CloudChange) -> None:
    if change.status == "DONE":
        raise _cli().W2CError(f"{change.name} is already DONE")


def _meta(change: ledger.CloudChange) -> Path:
    return change.path / ".openspec.yaml"


def _report(change: ledger.CloudChange, name: str) -> Path:
    return ledger.delivery_dir(change) / name


def _require(change: ledger.CloudChange, name: str) -> None:
    _cli().require_report(_report(change, name), name)


def _is_open(task) -> bool:
    return not task.done and not task.dropped


def new(root: Path, slug: str, cadence: str | None) -> int:
    cli = _cli()
    slug = cli.slugify(slug)
    if cadence is not None and cadence not in ledger.CADENCES:
        raise cli.W2CError(f"invalid cadence {cadence}; use {', '.join(sorted(ledger.CADENCES))}")
    if cadence is None:
        cadence = w2c_local.load_repo_config(root).get("git_delivery")
    if not cadence:
        print("NEED_CADENCE")
        return 1
    if cadence not in ledger.CADENCES:
        raise cli.W2CError(f"invalid cadence {cadence}; use {', '.join(sorted(ledger.CADENCES))}")
    top = max((c.order or 0 for c in ledger.list_changes(root)), default=0)
    created = osp.new_change(root, slug, goal=slug.replace("-", " "))
    info = created.get("change") if isinstance(created, dict) else None
    meta = str(info.get("metadataPath") or "") if isinstance(info, dict) else ""
    if not meta:
        raise cli.W2CError("openspec new change did not return metadataPath")
    path = Path(meta)
    if not path.is_absolute():
        path = root / path
    ledger.write_key(path, "x-delivery-status", "PLANNING")
    ledger.write_key(path, "x-delivery-order", str(top + 1))
    ledger.write_key(path, "x-delivery-cadence", str(cadence))
    ensure_knowledge(root)
    from w2c import hooks as w2c_hooks

    w2c_hooks.ensure_openspec_archive(root)
    print(f"created openspec/changes/{slug} ({slug})")
    return 0


def next_task(
    root: Path,
    change: str | None,
    slice_id: str | None,
    task_id: str | None,
):
    narrowed = bool(change or slice_id or task_id)
    changes = ledger.list_changes(root)
    if change:
        wanted = ledger.resolve(root, change)
        changes = [c for c in changes if c.path == wanted.path]
    elif not narrowed:
        names = ledger.branch_names(root)
        if names is not None:
            changes = [c for c in changes if c.name in names]
    changes = [c for c in changes if not c.amend_lock]

    def pick(allowed: frozenset[str] | None):
        for item in changes:
            if allowed is not None and item.status not in allowed:
                continue
            for task in _change_tasks(item):
                if slice_id and task.sid != slice_id:
                    continue
                if task_id and task.tid != task_id and task.openspec_id != task_id:
                    continue
                if _is_open(task):
                    return task
        return None

    if narrowed:
        return pick(None)
    return pick(FIRST_NEXT) or pick(THEN_NEXT)


def next_cmd(root: Path, change: str | None, slice_id: str | None, task_id: str | None) -> int:
    if change:
        named = ledger.resolve(root, change)
        if named.amend_lock:
            print(f"AMEND_LOCK {named.name}")
            return 1
    task = next_task(root, change, slice_id, task_id)
    if task is None:
        print("NEXT none")
        print(json.dumps({"task": None}))
        return 0
    print(f"NEXT {task.mid} {task.sid} {task.tid} — {task.title}")
    print(json.dumps({"task": _cli().task_to_dict(task)}, indent=2))
    return 0


def status(root: Path, all_: bool = False) -> int:
    cli = _cli()
    changes = ledger.list_changes(root)
    names = ledger.branch_names(root)
    if names is not None:
        changes = [c for c in changes if c.name in names]
    for item in changes:
        tasks = [t for t in _change_tasks(item) if not t.dropped]
        done = sum(1 for t in tasks if t.done)
        emoji = cli.STATUS_EMOJI.get(item.status, "")
        print(f"{emoji} {item.name}: {done}/{len(tasks)} tasks")
    task = next_task(root, None, None, None)
    if task is None:
        print("Next: none")
    else:
        print(f"Next: {task.mid} {task.sid} {task.tid}: {task.title}")
    if all_:
        state = root / ".w2c" / "STATE.md"
        if state.is_file():
            print()
            print(cli.read_text(state).rstrip("\n"))
    return 0


def smoke(root: Path, change: str | None) -> int:
    cli = _cli()
    if change:
        changes = [ledger.resolve(root, change)]
    else:
        changes = ledger.list_changes(root, include_archived=True)
    report = cli.Report()
    for name, state, detail in checks.smoke_rows(root, changes):
        report.add(name, state, detail)
    report.print()
    return 1 if report.failed() else 0


def _groups(change: ledger.CloudChange) -> tuple[list[int], list[int]]:
    """(all group numbers, group numbers not yet finished).

    A group is finished when every task is done or dropped and it is either
    all dropped or listed in x-delivery-slices-done.
    """
    tasks = _change_tasks(change)
    numbers = osl.group_numbers(_tasks_path(change))
    open_groups: list[int] = []
    for number in numbers:
        in_group = [t for t in tasks if t.sid == f"S{number:02d}"]
        if not in_group or any(_is_open(t) for t in in_group):
            open_groups.append(number)
        elif not all(t.dropped for t in in_group) and number not in change.slices_done:
            open_groups.append(number)
    return numbers, open_groups


def complete(root: Path, change: str, sid: str, tid: str) -> int:
    cli = _cli()
    item = _active(root, change)
    _refuse_if_locked(item)
    _refuse_if_done(item)
    tasks = [t for t in _change_tasks(item) if t.sid == sid]
    match = [t for t in tasks if t.tid == tid or t.openspec_id == tid]
    if not match:
        raise cli.W2CError(f"unknown task {item.name} {sid} {tid}")
    task = match[0]
    tid = task.tid
    _require(item, checks.report_name("task_summary", sid, tid))
    if task.done:
        raise cli.W2CError(f"{tid} is already complete")
    if task.dropped:
        raise cli.W2CError(f"{tid} is dropped")
    path = task.plan_path
    cli.atomic_write(path, osl.set_task_checked(cli.read_text(path), task.openspec_id, True))
    if item.status in START_FROM:
        ledger.write_key(_meta(item), "x-delivery-status", "INPROGRESS")
    remaining = [t for t in _change_tasks(item) if t.sid == sid and _is_open(t)]
    _event(root, stage="complete", event="complete", milestone=item.name,
           slice_id=sid, task_id=tid, detail=f"complete {item.name} {sid} {tid}")
    print(f"complete {item.name} {sid} {tid}")
    if remaining:
        print(f"OPEN_IN_SLICE {len(remaining)}")
    elif _present(item, "slice_uat", sid) and _present(item, "slice_summary", sid):
        print(f"NEED_SLICE_COMPLETE {sid}")
    else:
        print(f"NEED_SLICE_REPORTS {sid}")
    return 0


def _present(item: ledger.CloudChange, key: str, sid: str = "") -> bool:
    return _cli().report_present(_report(item, checks.report_name(key, sid)))


def slice_complete(root: Path, change: str, sid: str) -> int:
    cli = _cli()
    item = _active(root, change)
    _refuse_if_locked(item)
    _refuse_if_done(item)
    tasks = [t for t in _change_tasks(item) if t.sid == sid]
    if not tasks:
        raise cli.W2CError(f"no tasks in {item.name} {sid}")
    open_tasks = [t.tid for t in tasks if _is_open(t)]
    if open_tasks:
        raise cli.W2CError(f"open tasks remain in {item.name} {sid}: {', '.join(open_tasks)}")
    if not any(t.done for t in tasks):
        raise cli.W2CError(f"{sid} has no finished task")
    for t in tasks:
        if t.done:
            _require(item, checks.report_name("task_summary", sid, t.tid))
    _require(item, checks.report_name("slice_uat", sid))
    _require(item, checks.report_name("slice_summary", sid))
    summary = cli.read_text(_report(item, checks.report_name("slice_summary", sid)))
    unnamed = [
        t.tid for t in tasks
        if t.dropped and re.search(rf"\b{re.escape(t.tid)}\b", summary) is None
    ]
    if unnamed:
        raise cli.W2CError(f"slice summary must name dropped tasks: {', '.join(unnamed)}")
    number = int(sid[1:])
    done = sorted(set(item.slices_done) | {number})
    ledger.write_key(_meta(item), "x-delivery-slices-done", "[" + ", ".join(map(str, done)) + "]")
    item = ledger.load_change(item.path) or item
    _numbers, open_groups = _groups(item)
    _event(root, stage="slice-complete", event="complete", milestone=item.name,
           slice_id=sid, detail=f"slice-complete {item.name} {sid}")
    print(f"slice-complete {item.name} {sid}")
    if open_groups:
        print(f"OPEN_SLICES {len(open_groups)}")
    elif _present(item, "validation") and _present(item, "summary"):
        print(f"NEED_MILESTONE_COMPLETE {item.name}")
    else:
        print(f"NEED_MILESTONE_REPORTS {item.name}")
    return 0


def _require_closeout(item: ledger.CloudChange) -> None:
    cli = _cli()
    numbers, open_groups = _groups(item)
    if not numbers:
        raise cli.W2CError(f"no task groups found in {item.name} tasks.md")
    if open_groups:
        names = ", ".join(f"S{n:02d}" for n in open_groups)
        raise cli.W2CError(f"slices still open in {item.name}: {names}")
    _require(item, checks.report_name("validation"))
    _require(item, checks.report_name("summary"))


def all_closed(change: ledger.CloudChange) -> bool:
    """Every task is done or dropped and every group is finished."""
    tasks = _change_tasks(change)
    numbers, open_groups = _groups(change)
    return bool(tasks) and bool(numbers) and not open_groups and not any(_is_open(t) for t in tasks)


def archive(root: Path, change: str) -> int:
    cli = _cli()
    item = _active(root, change)
    _refuse_if_locked(item)
    if item.status == "DONE" and item.archive != "declined":
        raise cli.W2CError(f"{item.name} is already DONE")
    _require_closeout(item)
    meta = _meta(item)
    reports = ledger.delivery_dir(item)
    backup = Path(tempfile.mkdtemp(prefix="cloud-delivery-"))
    saved = backup / reports.name
    try:
        if reports.exists():
            shutil.move(str(reports), str(saved))
        ledger.write_key(meta, "x-delivery-archive", None)
        ledger.write_key(meta, "x-delivery-status", "DONE")
        data = osp.archive(root, item.name)
    except BaseException as exc:
        if not item.path.is_dir():
            raise cli.W2CError(
                f"{exc}; the change was moved into the archive, its closeout reports are "
                f"kept in {backup}"
            ) from exc
        if saved.exists():
            if reports.exists():
                shutil.rmtree(reports)
            shutil.move(str(saved), str(reports))
        if meta.is_file():
            ledger.write_key(meta, "x-delivery-status", item.status)
            ledger.write_key(meta, "x-delivery-archive", item.archive or None)
        shutil.rmtree(backup, ignore_errors=True)
        raise
    shutil.rmtree(backup, ignore_errors=True)
    info = data.get("archive") if isinstance(data, dict) else None
    archived_as = str(info.get("archivedAs") or "") if isinstance(info, dict) else ""
    _event(root, stage="archive", event="complete", milestone=item.name,
           detail=f"archived {item.name}")
    print(f"archived {item.name} as {archived_as or item.name}")
    return 0


def milestone_complete(root: Path, change: str, archive_declined: bool) -> int:
    cli = _cli()
    item = ledger.resolve(root, change)
    if item.archived:
        if item.status != "DONE":
            ledger.write_key(_meta(item), "x-delivery-status", "DONE")
        print(f"{item.name} -> DONE")
        return 0
    _refuse_if_locked(item)
    if not archive_declined:
        raise cli.W2CError(f"run w2c cloud archive {item.name} or pass --archive-declined")
    _require_closeout(item)
    ledger.write_key(_meta(item), "x-delivery-status", "DONE")
    ledger.write_key(_meta(item), "x-delivery-archive", "declined")
    _event(root, stage="plan", event="status", milestone=item.name,
           detail=f"{item.name} -> DONE")
    print(f"{item.name} -> DONE")
    print(
        f"OPENSPEC_ARCHIVE_DECLINED {item.name} follow-up: archive the change with "
        f"w2c cloud archive {item.name}"
    )
    return 0


def status_set(root: Path, change: str, status_name: str) -> int:
    cli = _cli()
    value = status_name.upper()
    if value == "DONE":
        raise cli.W2CError(
            f"DONE is set by w2c cloud archive {change} or w2c cloud milestone-complete {change}"
        )
    if value not in ledger.STATUSES:
        raise cli.W2CError(f"invalid status {value}; use {', '.join(ledger.STATUSES)}")
    item = _active(root, change)
    _refuse_if_locked(item)
    ledger.write_key(_meta(item), "x-delivery-status", value)
    _event(root, stage="plan", event="status", milestone=item.name,
           detail=f"{item.name} -> {value}")
    print(f"{item.name} -> {value} {cli.STATUS_EMOJI[value]}")
    return 0


PENDING_DECISIONS = Path(".w2c/runtime/pending-decisions.jsonl")
DECISION_HEADER = (
    "| # | When | Scope | Decision | Choice | Rationale | Revisable? | Made By |\n"
    "|---|------|-------|----------|--------|-----------|------------|---------|\n"
)
ROW_FIELDS = ("when", "scope", "decision", "choice", "rationale", "revisable", "made_by")
DECISION_ID_RE = re.compile(r"^\|\s*D(\d+)\s*\|", re.M)
NEWLINES_RE = re.compile(r"\s*[\r\n]+\s*")


def _cell(value: str) -> str:
    return NEWLINES_RE.sub(" ", str(value)).replace("|", "\\|").strip()


def _decisions_span(text: str) -> tuple[int, int] | None:
    """Start and end offsets of the body of `## Decisions`, or None."""
    match = re.search(r"^## Decisions[ \t]*$", text, re.M)
    if not match:
        return None
    start = match.end()
    nxt = re.search(r"^## ", text[start:], re.M)
    return start, start + nxt.start() if nxt else len(text)


def _read_rows(path: Path) -> list[dict[str, str]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            row = None
        if not isinstance(row, dict):
            raise _cli().W2CError(f"{path.name} line {number} is not a decision row")
        rows.append(row)
    return rows


def _add_rows(text: str, rows: list[dict[str, str]]) -> tuple[str, list[str]] | None:
    """Append rows to the Decisions table; None when the section is missing."""
    span = _decisions_span(text)
    if span is None:
        return None
    start, end = span
    body = text[start:end]
    last = max((int(n) for n in DECISION_ID_RE.findall(body)), default=0)
    ids: list[str] = []
    lines: list[str] = []
    for row in rows:
        last += 1
        ids.append(f"D{last}")
        cells = [ids[-1]] + [_cell(row.get(field, "")) for field in ROW_FIELDS]
        lines.append("| " + " | ".join(cells) + " |\n")
    head = re.search(r"^\| # \| When \|.*$", body, re.M)
    if head:
        lines_in = body.splitlines(keepends=True)
        idx = body[: head.start()].count("\n")
        stop = idx + 1
        while stop < len(lines_in) and lines_in[stop].startswith("|"):
            stop += 1
        if not lines_in[stop - 1].endswith("\n"):
            lines_in[stop - 1] += "\n"
        new_body = "".join(lines_in[:stop]) + "".join(lines) + "".join(lines_in[stop:])
    else:
        new_body = body.rstrip() + "\n\n" + DECISION_HEADER + "".join(lines)
        if end < len(text):
            new_body += "\n"
    return text[:start] + new_body + text[end:], ids


def _design_with_decisions(change: ledger.CloudChange) -> tuple[Path, str] | None:
    design = change.path / "design.md"
    if not design.is_file():
        return None
    text = design.read_text(encoding="utf-8")
    return (design, text) if _decisions_span(text) else None


def decide(root: Path, change: str | None, row: dict[str, str]) -> int:
    cli = _cli()
    row = dict(row)
    if not row.get("when"):
        row["when"] = datetime.now().astimezone().strftime("%Y-%m-%d")
    found = _design_with_decisions(_active(root, change)) if change else None
    if found is None:
        path = root / PENDING_DECISIONS
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {field: str(row.get(field, "")) for field in ROW_FIELDS}
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        if path.is_file() and path.stat().st_size:
            with open(path, "rb") as probe:
                probe.seek(-1, 2)
                if probe.read(1) != b"\n":
                    line = "\n" + line
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
        print("PENDING")
        return 0
    design, text = found
    result = _add_rows(text, [row])
    assert result is not None
    cli.atomic_write(design, result[0])
    print(result[1][0])
    return 0


def decisions_flush(root: Path, change: str) -> int:
    cli = _cli()
    item = _active(root, change)
    found = _design_with_decisions(item)
    if found is None:
        raise cli.W2CError(f"{item.name} has no design.md with a ## Decisions section")
    pending = root / PENDING_DECISIONS
    flushing = pending.with_name("pending-decisions.flushing.jsonl")
    if flushing.exists():
        raise cli.W2CError(
            f"{flushing} exists: a previous flush was interrupted; check it by hand "
            "and remove it before flushing again"
        )
    if not pending.is_file():
        print("0 flushed")
        return 0
    pending.rename(flushing)

    def restore(rows_text: str) -> None:
        late = pending.read_text(encoding="utf-8") if pending.is_file() else ""
        cli.atomic_write(pending, rows_text + late)
        flushing.unlink(missing_ok=True)

    raw = flushing.read_text(encoding="utf-8")
    if raw and not raw.endswith("\n"):
        raw += "\n"
    try:
        rows = _read_rows(flushing)
    except cli.W2CError:
        restore(raw)
        raise
    if not rows:
        flushing.unlink(missing_ok=True)
        print("0 flushed")
        return 0
    design, text = found
    result = _add_rows(text, rows)
    assert result is not None
    try:
        cli.atomic_write(design, result[0])
    except BaseException:
        restore(raw)
        raise
    flushing.unlink(missing_ok=True)
    print(f"{len(rows)} flushed {' '.join(result[1])}")
    return 0


def _branch_changes(root: Path) -> list[ledger.CloudChange]:
    names = ledger.branch_names(root)
    return [c for c in ledger.list_changes(root) if names is None or c.name in names]


def _apply_order(root: Path, items: list[ledger.CloudChange], names: list[str]) -> None:
    cli = _cli()
    before = [
        cli.Milestone(mid=c.name, title=c.name, status=c.status, emoji=cli.STATUS_EMOJI.get(c.status, ""))
        for c in items
    ]
    after = [next(m for m in before if m.mid == n) for n in names]
    cli.assert_reorder_allowed(before, after)
    by_name = {c.name: c for c in items}
    changing = [(n, by_name[name]) for n, name in enumerate(names, start=1)
                if by_name[name].order != n]
    for _number, change in changing:
        _refuse_if_locked(change)
    for number, change in changing:
        ledger.write_key(_meta(change), "x-delivery-order", str(number))
    for number, name in enumerate(names, start=1):
        print(f"{number} {name}")


def _known(items: list[ledger.CloudChange], name: str) -> ledger.CloudChange:
    for c in items:
        if c.name == name:
            return c
    raise _cli().W2CError(f"{name} is not an active change on this branch")


def order(root: Path, names: list[str]) -> int:
    cli = _cli()
    items = _branch_changes(root)
    if len(names) != len(set(names)):
        raise cli.W2CError("duplicate change in order list")
    for name in names:
        _known(items, name)
    current = [c.name for c in items]
    slots = [i for i, n in enumerate(current) if n in set(names)]
    for slot, name in zip(slots, names):
        current[slot] = name
    _apply_order(root, items, current)
    return 0


def swap(root: Path, left: str, right: str) -> int:
    cli = _cli()
    items = _branch_changes(root)
    if left == right:
        raise cli.W2CError("cannot swap a change with itself")
    _known(items, left)
    _known(items, right)
    current = [c.name for c in items]
    i, j = current.index(left), current.index(right)
    current[i], current[j] = current[j], current[i]
    _apply_order(root, items, current)
    return 0


def move(root: Path, name: str, before: str | None, after: str | None) -> int:
    cli = _cli()
    if (before is None) == (after is None):
        raise cli.W2CError("pass exactly one of --before or --after")
    items = _branch_changes(root)
    other = before if before else after or ""
    if name == other:
        raise cli.W2CError("cannot move a change relative to itself")
    _known(items, name)
    _known(items, other)
    current = [c.name for c in items]
    current.remove(name)
    at = current.index(other)
    current.insert(at if before else at + 1, name)
    _apply_order(root, items, current)
    return 0
