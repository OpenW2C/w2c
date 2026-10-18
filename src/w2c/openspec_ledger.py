"""Map one W2C milestone onto one OpenSpec change folder.

The change folder stays a standard spec-driven change. Delivery rules stay
in the `.w2c/plans/` sidecar. This module does not import the CLI package
at import time.
"""

from __future__ import annotations

import re
from pathlib import Path

from w2c import openspec as osp
from w2c.local import PLANNING_CLASSIC, PLANNING_OPENSPEC, normalize_planning

GROUP_RE = re.compile(r"^##\s+(\d+)\.\s+(.*?)\s*$")
TASK_RE = re.compile(
    r"^(?P<indent>\s*)(?:[-*+]|\d{1,9}[.)])\s+\[(?P<mark>[ xX])\]\s+"
    r"(?P<major>\d+)\.(?P<minor>\d+)\s+(?P<title>.*)$"
)
APPLY_TASK_ID_RE = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)(?:\s|$)")
VERIFY_RE = re.compile(r"^\s+- Verify:\s*(.*)$")
LINK_RE = re.compile(r"(?m)^x-w2c-milestone\s*:\s*(\S+)\s*$")
SLICE_NUM_RE = re.compile(r"^S(\d+)$")


def _cli():
    from w2c import cli as w2c_cli

    return w2c_cli


def planning_mode(text: str) -> str:
    fields = _cli().parse_table_under_heading(text, "Delivery & Guardrails")
    raw = fields.get("Planning mode", "").strip()
    if not raw:
        return PLANNING_CLASSIC
    try:
        return normalize_planning(raw)
    except Exception:
        return PLANNING_CLASSIC


def guardrail(text: str, field: str) -> str:
    fields = _cli().parse_table_under_heading(text, "Delivery & Guardrails")
    return fields.get(field, "").strip()


def change_name(text: str) -> str:
    return guardrail(text, "OpenSpec change")


def archive_value(text: str) -> str:
    return guardrail(text, "OpenSpec archive")


def is_archived(text: str) -> bool:
    value = archive_value(text)
    return bool(value) and value != "declined"


def set_guardrail_field(text: str, field: str, value: str) -> str:
    pattern = re.compile(
        rf"^(\|\s*{re.escape(field)}\s*\|\s*)([^|\n]*)(\s*\|)\s*$",
        re.M,
    )
    updated, count = pattern.subn(
        lambda match: f"{match.group(1).rstrip()} {value} |",
        text,
        count=1,
    )
    if count != 1:
        raise _cli().W2CError(f"guardrail field {field!r} not found")
    return updated


def linked_milestone(metadata: Path) -> str | None:
    if not metadata.is_file():
        return None
    match = LINK_RE.search(metadata.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def change_dir(root: Path, name: str, archived: str) -> Path | None:
    if not name:
        return None
    active = root / "openspec" / "changes" / name
    if (active / ".openspec.yaml").is_file():
        return active
    if archived and archived != "declined":
        candidate = Path(archived)
        if not candidate.is_absolute():
            candidate = root / archived
        if (candidate / ".openspec.yaml").is_file():
            return candidate
        named = root / "openspec" / "changes" / "archive" / archived
        if (named / ".openspec.yaml").is_file():
            return named
    archive_root = root / "openspec" / "changes" / "archive"
    if archive_root.is_dir():
        matches = sorted(path for path in archive_root.glob(f"*-{name}") if path.is_dir())
        if matches:
            return matches[-1]
    return active if active.is_dir() else None


def roadmap_text(root: Path, mid: str) -> tuple[Path | None, str]:
    cli = _cli()
    plan_dir = cli.plan_dir_for(root, mid)
    if plan_dir is None:
        return None, ""
    path = plan_dir / f"{mid}-ROADMAP.md"
    if not path.is_file():
        return plan_dir, ""
    return plan_dir, path.read_text(encoding="utf-8")


def parse_openspec_tasks(tasks_path: Path, mid: str) -> list:
    cli = _cli()
    lines = tasks_path.read_text(encoding="utf-8").splitlines()
    tasks = []
    for index, line in enumerate(lines):
        match = TASK_RE.match(line)
        if not match:
            continue
        major = int(match.group("major"))
        minor = int(match.group("minor"))
        verify = ""
        for follow in lines[index + 1 : index + 8]:
            found = VERIFY_RE.match(follow)
            if found:
                verify = found.group(1).strip()
                break
            if TASK_RE.match(follow) or follow.startswith("## "):
                break
        tasks.append(
            cli.Task(
                mid=mid,
                sid=f"S{major:02d}",
                tid=f"T{minor:02d}",
                title=(match.group("title") or "").strip().rstrip("."),
                done=match.group("mark").lower() == "x",
                plan_path=tasks_path,
                verify=verify,
                openspec_id=f"{major}.{minor}",
            )
        )
    return tasks


def set_task_checked(text: str, openspec_id: str, checked: bool = True) -> str:
    major, minor = openspec_id.split(".", 1)
    mark = "x" if checked else " "
    pattern = re.compile(
        rf"^(\s*(?:[-*+]|\d{{1,9}}[.)])\s+\[)[ xX](\]\s+{re.escape(major)}\.{re.escape(minor)}(?:\s|$))",
        re.M,
    )
    updated, count = pattern.subn(rf"\g<1>{mark}\g<2>", text, count=1)
    if count != 1:
        raise _cli().W2CError(f"task {openspec_id} not found in tasks.md")
    return updated


def group_numbers(tasks_path: Path | None) -> list[int]:
    if tasks_path is None or not tasks_path.is_file():
        return []
    found: list[int] = []
    for line in tasks_path.read_text(encoding="utf-8").splitlines():
        match = GROUP_RE.match(line)
        if match:
            found.append(int(match.group(1)))
    return found


def tasks_in_slice(root: Path, mid: str, sid: str, plan_dir: Path) -> list:
    cli = _cli()
    roadmap = plan_dir / f"{mid}-ROADMAP.md"
    text = roadmap.read_text(encoding="utf-8") if roadmap.is_file() else ""
    if planning_mode(text) == PLANNING_OPENSPEC:
        folder = change_dir(root, change_name(text), archive_value(text))
        tasks_path = folder / "tasks.md" if folder is not None else None
        if tasks_path is None or not tasks_path.is_file():
            return []
        return [task for task in parse_openspec_tasks(tasks_path, mid) if task.sid == sid]
    plan = plan_dir / f"{mid}-{sid}-PLAN.md"
    if not plan.is_file():
        return []
    return cli.parse_tasks(plan, mid, sid)


def change_prefixes(root: Path) -> list[str]:
    cli = _cli()
    roadmap = cli.w2c_dir(root) / "ROADMAP.md"
    if not roadmap.is_file():
        return []
    prefixes: list[str] = []
    for milestone in cli.parse_milestones(roadmap.read_text(encoding="utf-8")):
        if milestone.status == "DONE":
            continue
        plan_dir = cli.plan_dir_for(root, milestone.mid)
        if plan_dir is None:
            continue
        path = plan_dir / f"{milestone.mid}-ROADMAP.md"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if planning_mode(text) != PLANNING_OPENSPEC:
            continue
        name = change_name(text)
        if name:
            prefixes.append(f"openspec/changes/{name}")
    return prefixes


def require_archive_for_done(root: Path, mid: str, plan_dir: Path, archive_declined: bool) -> None:
    cli = _cli()
    path = plan_dir / f"{mid}-ROADMAP.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if planning_mode(text) != PLANNING_OPENSPEC:
        return
    if archive_value(text):
        return
    if not archive_declined:
        raise cli.W2CError(
            f"OpenSpec milestone {mid} is not archived; run `w2c spec-archive {mid}` "
            "or pass --archive-declined"
        )
    cli.atomic_write(path, set_guardrail_field(text, "OpenSpec archive", "declined"))
    print(
        f"OPENSPEC_ARCHIVE_DECLINED {mid} follow-up: archive the change with "
        f"`w2c spec-archive {mid}` so the main specs can merge"
    )


def apply_checkbox_progress(tasks: object) -> dict[str, bool] | None:
    """Map each apply task's leading major.minor checkbox id to its done flag.

    Returns None when ``tasks`` is not a list, an item is not an object, a
    description does not start with that id, or the same id appears twice.
    """
    if tasks is None:
        tasks = []
    if not isinstance(tasks, list):
        return None
    progress: dict[str, bool] = {}
    for item in tasks:
        if not isinstance(item, dict):
            return None
        description = item.get("description")
        if not isinstance(description, str):
            return None
        match = APPLY_TASK_ID_RE.match(description)
        if match is None:
            return None
        openspec_id = f"{int(match.group('major'))}.{int(match.group('minor'))}"
        if openspec_id in progress:
            return None
        progress[openspec_id] = bool(item.get("done"))
    return progress


def _slice_numbers(text: str) -> list[int]:
    numbers: list[int] = []
    for sid, _done, _title in _cli().parse_slices(text):
        match = SLICE_NUM_RE.match(sid)
        if match:
            numbers.append(int(match.group(1)))
    return numbers


def _conventions_problems(text: str, label: str) -> list[str]:
    body = _cli().section_under_heading(text, "Commit and PR conventions")
    if body is None:
        return [f"{label}: missing Commit and PR conventions"]
    lower = body.lower()
    if "openspec/" not in lower or "product content" not in lower or "never deny-listed" not in lower:
        return [
            f"{label}: conventions must say openspec/ is product content and is never deny-listed"
        ]
    return []


def smoke_checks(root: Path, milestones: list) -> list[tuple[str, str, str]]:
    """Extra smoke rows. Empty when no milestone uses OpenSpec mode."""
    selected: list[tuple] = []
    for milestone in milestones:
        plan_dir, text = roadmap_text(root, milestone.mid)
        if plan_dir is None or planning_mode(text) != PLANNING_OPENSPEC:
            continue
        selected.append((milestone, plan_dir, text))
    if not selected:
        return []

    rows: list[tuple[str, str, str]] = []
    cli_ok = False
    try:
        if not osp.executable():
            raise osp.OpenSpecError("openspec is not on PATH")
        version = osp.version_text()
        if not osp.version_ok(version):
            rows.append(
                (
                    "openspec-cli",
                    "FAIL",
                    f"{version} is older than {'.'.join(str(p) for p in osp.MIN_OPENSPEC_VERSION)}",
                )
            )
        else:
            rows.append(("openspec-cli", "PASS", version))
            cli_ok = True
    except osp.OpenSpecError as exc:
        rows.append(("openspec-cli", "FAIL", str(exc)))

    link_problems: list[str] = []
    validate_problems: list[str] = []
    artifact_problems: list[str] = []
    slice_problems: list[str] = []
    verify_problems: list[str] = []
    progress_problems: list[str] = []
    slice_task_problems: list[str] = []
    archive_problems: list[str] = []
    convention_problems: list[str] = []

    for milestone, plan_dir, text in selected:
        name = change_name(text)
        archived = archive_value(text)
        folder = change_dir(root, name, archived)
        metadata = folder / ".openspec.yaml" if folder is not None else None
        linked = linked_milestone(metadata) if metadata is not None else None
        if not name:
            link_problems.append(f"{milestone.mid}: OpenSpec change is empty")
        elif linked != milestone.mid:
            link_problems.append(
                f"{milestone.mid}: x-w2c-milestone is {linked!r}, expected {milestone.mid}"
            )
        tasks_path = folder / "tasks.md" if folder is not None else None
        groups = group_numbers(tasks_path)
        slices = _slice_numbers(text)
        if groups != slices:
            slice_problems.append(
                f"{milestone.mid}: tasks.md groups {groups} != slices {slices}"
            )
        if tasks_path is not None and tasks_path.is_file():
            for task in parse_openspec_tasks(tasks_path, milestone.mid):
                if not task.verify:
                    verify_problems.append(f"{milestone.mid} {task.openspec_id}: missing Verify line")
        elif slices:
            verify_problems.append(f"{milestone.mid}: tasks.md missing")

        for plan in sorted(plan_dir.glob(f"{milestone.mid}-S*-PLAN.md")):
            body = plan.read_text(encoding="utf-8")
            for line in body.splitlines():
                if _cli().TASK_LINE_RE.match(line) or TASK_RE.match(line):
                    slice_task_problems.append(f"{plan.name}: task checkbox belongs in tasks.md")
                    break
            convention_problems.extend(_conventions_problems(body, plan.name))
        convention_problems.extend(_conventions_problems(text, f"{milestone.mid}-ROADMAP.md"))

        if milestone.status == "DONE" and not archived:
            archive_problems.append(f"{milestone.mid}: done without archive or declined")

        skip_live = milestone.status == "DONE" or is_archived(text)
        if skip_live:
            continue
        if not cli_ok:
            validate_problems.append(f"{milestone.mid}: openspec cli unavailable")
            artifact_problems.append(f"{milestone.mid}: openspec cli unavailable")
            progress_problems.append(f"{milestone.mid}: openspec cli unavailable")
            continue
        if not name:
            validate_problems.append(f"{milestone.mid}: no change name")
            continue
        validated = osp.validate(root, name, strict=True)
        if not validated.ok:
            detail = (validated.stderr or validated.stdout or "validate failed").strip()
            validate_problems.append(f"{milestone.mid}: {detail[:240]}")
        try:
            report = osp.status(root, name)
        except osp.OpenSpecError as exc:
            artifact_problems.append(f"{milestone.mid}: {exc}")
            report = {}
        if report and not report.get("isComplete"):
            waiting = [
                item.get("id", "?")
                for item in report.get("artifacts") or []
                if item.get("status") != "done"
            ]
            artifact_problems.append(f"{milestone.mid}: not complete ({', '.join(waiting)})")
        try:
            apply = osp.apply_info(root, name)
        except osp.OpenSpecError as exc:
            progress_problems.append(f"{milestone.mid}: {exc}")
            apply = None
        if apply is not None and tasks_path is not None and tasks_path.is_file():
            ours = {
                task.openspec_id: task.done
                for task in parse_openspec_tasks(tasks_path, milestone.mid)
            }
            theirs = apply_checkbox_progress(apply.get("tasks"))
            if theirs is None or ours != theirs:
                progress_problems.append(
                    f"{milestone.mid}: tasks.md checkboxes disagree with openspec instructions apply"
                )

    def add(name: str, problems: list[str]) -> None:
        rows.append((name, "FAIL" if problems else "PASS", "; ".join(problems[:8])))

    add("openspec-change-link", link_problems)
    add("openspec-validate-strict", validate_problems)
    add("openspec-artifacts-complete", artifact_problems)
    add("openspec-slices-match-groups", slice_problems)
    add("openspec-tasks-have-verify", verify_problems)
    add("openspec-progress-agrees", progress_problems)
    add("openspec-no-slice-tasks", slice_task_problems)
    add("openspec-archived-when-done", archive_problems)
    add("openspec-conventions", convention_problems)
    return rows
