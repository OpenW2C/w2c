"""Smoke checks for cloud changes: rules in design.md, tasks.md, keys, reports.

Rows are `(name, "PASS" | "FAIL", detail)`. Standard library only; the CLI
package is imported lazily.
"""

from __future__ import annotations

import re
from pathlib import Path

from w2c import openspec_ledger as osl
from w2c.cloud import layout
from w2c.cloud.ledger import (
    CADENCES,
    INT_RE,
    PREFIX,
    STATUSES,
    CloudChange,
    delivery_dir,
    read_keys,
)

FIELD_RE = re.compile(r"^\*\*([^*\n]+?):\*\*[ \t]*(.*)$")
GROUP_LINE_RE = re.compile(r"^##\s+(\d+)\.")
INT_LIST_RE = re.compile(r"^\[\s*(?:-?\d+(?:\s*,\s*-?\d+)*)?\s*\]$")
PROHIBITION_RE = re.compile(r"\b(do not|don't|never|must not|forbidden)\b", re.I)
PRODUCT_CONTENT_RE = re.compile(r"openspec/`?\s+is product content and is never deny-listed", re.I)
CONVENTIONS_HEADING = layout.DESIGN_HEADINGS[2].removeprefix("## ")
PLAN_HEADING = layout.DESIGN_HEADINGS[0].removeprefix("## ")
MANUAL_HEADING = layout.DESIGN_HEADINGS[4].removeprefix("## ")


def _cli():
    from w2c import cli as w2c_cli

    return w2c_cli


def slice_fields(tasks_text: str) -> dict[int, dict[str, str]]:
    """Bold `**Field:**` values per `## N.` group. Task lines end a value."""
    groups: dict[int, dict[str, str]] = {}
    current: dict[str, str] | None = None
    field: str | None = None
    for line in tasks_text.splitlines():
        heading = GROUP_LINE_RE.match(line)
        if heading:
            current = groups.setdefault(int(heading.group(1)), {})
            field = None
            continue
        if line.startswith("## "):
            current, field = None, None
            continue
        if current is None:
            continue
        if osl.TASK_RE.match(line):
            field = None
            continue
        match = FIELD_RE.match(line)
        if match and match.group(1).strip() in layout.SLICE_FIELDS:
            field = match.group(1).strip()
            current[field] = match.group(2).strip()
            continue
        if field is not None and line.strip():
            current[field] = (current[field] + "\n" + line.strip()).strip()
    return groups


def validate_conventions(design_text: str) -> list[str]:
    """Problems with the Commit and PR Conventions section; empty means OK."""
    body = _cli().section_under_heading(design_text, CONVENTIONS_HEADING)
    if body is None or not body.strip():
        return [f"missing or empty ## {CONVENTIONS_HEADING} section"]
    problems: list[str] = []
    lines = body.splitlines()
    lower = [line.lower() for line in lines]
    if not any("co-authored-by" in low and PROHIBITION_RE.search(line) for low, line in zip(lower, lines)):
        # The ban may sit in the paragraph under a heading line.
        paragraphs = re.split(r"\n\s*\n", body)
        if not any("co-authored-by" in p.lower() and PROHIBITION_RE.search(p) for p in paragraphs):
            problems.append("conventions must forbid Co-authored-by trailers")
    if not re.search(r"\b(do not|don't|never)\s+stage\b", body, re.I):
        problems.append("conventions must forbid staging deny-listed paths")
    if not any(
        ".delivery/" in low and PROHIBITION_RE.search(line) and ("mention" in low or "name" in low)
        for low, line in zip(lower, lines)
    ) and not re.search(r"do not mention[^\n]*\n[^\n]*\.delivery/", body, re.I):
        problems.append("conventions must forbid mentioning .delivery/ paths in commit or PR text")
    if not PRODUCT_CONTENT_RE.search(body):
        problems.append("conventions must say openspec/ is product content and is never deny-listed")
    return problems


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def key_problems(change: CloudChange) -> list[str]:
    meta = change.path / ".openspec.yaml"
    try:
        keys = read_keys(meta)
    except Exception as exc:  # duplicate key or unreadable file
        return [str(exc)]

    def get(name: str) -> str:
        return keys.get(PREFIX + name, "")

    problems: list[str] = []
    status = get("status")
    if status not in STATUSES:
        problems.append(f"x-delivery-status {status!r} is not one of {', '.join(STATUSES)}")
    cadence = get("cadence")
    if cadence:
        if cadence not in CADENCES:
            problems.append(f"x-delivery-cadence {cadence!r} is not one of {', '.join(sorted(CADENCES))}")
    elif not change.archived:
        problems.append("x-delivery-cadence is required on an active change")
    order = get("order")
    if order and not INT_RE.fullmatch(order):
        problems.append(f"x-delivery-order {order!r} is not an integer")
    done = get("slices-done")
    if done and not INT_LIST_RE.fullmatch(done):
        problems.append(f"x-delivery-slices-done {done!r} is not a list like [1, 2]")
    archive = get("archive")
    if archive not in ("", "declined"):
        problems.append(f"x-delivery-archive {archive!r} must be empty or declined")
    if get("amend-lock"):
        if get("amend-prior-status") not in STATUSES:
            problems.append("x-delivery-amend-prior-status must be a valid status while amend-lock is set")
        if not get("amend-decision"):
            problems.append("x-delivery-amend-decision must not be empty while amend-lock is set")
    return problems


def design_problems(design_text: str | None) -> dict[str, list[str]]:
    """Problems from design.md, keyed by the four design-based check names."""
    out: dict[str, list[str]] = {
        "design-sections": [],
        "git-operation-plan": [],
        "commit-pr-conventions": [],
        "manual-test-guide": [],
    }
    if design_text is None:
        for name in out:
            out[name].append("design.md missing")
        return out
    cli = _cli()
    present = {line.strip() for line in design_text.splitlines() if line.startswith("## ")}
    for heading in layout.DESIGN_HEADINGS:
        if heading not in present:
            out["design-sections"].append(f"missing {heading}")
    fields = cli.parse_table_under_heading(design_text, PLAN_HEADING)
    out["git-operation-plan"] = cli.validate_git_operation_plan(
        fields, plan_text=design_text, plan_heading=PLAN_HEADING
    )
    out["commit-pr-conventions"] = validate_conventions(design_text)
    manual = fields.get("Manual test guide", "").strip().lower()
    if manual not in ("yes", "no"):
        out["manual-test-guide"].append(f"Manual test guide must be yes or no (got {manual!r})")
    elif manual == "yes":
        body = cli.section_under_heading(design_text, MANUAL_HEADING)
        if body is None or not body.strip():
            out["manual-test-guide"].append("Manual test guide is yes but ## Manual Test Guide is empty")
    return out


def read_first_problems(tasks_text: str | None) -> list[str]:
    if tasks_text is None:
        return ["tasks.md missing"]
    head: list[str] = []
    for line in tasks_text.splitlines():
        if line.startswith("## "):
            break
        head.append(line)
    top = "\n".join(head)
    problems: list[str] = []
    if layout.READ_FIRST_MARKER not in top:
        problems.append("tasks.md lacks the read-first block before the first ## heading")
    if layout.STOP_SENTENCE not in top:
        problems.append("tasks.md read-first block lacks the stop sentence")
    return problems


def report_name(key: str, sid: str = "", tid: str = "") -> str:
    return layout.REPORT_FILES[key].replace("S##", sid).replace("T##", tid)


def _missing(change: CloudChange, names: list[str]) -> list[str]:
    folder = delivery_dir(change)
    return [f"{change.name}: missing {layout.REPORT_DIR}/{n}" for n in names if not (folder / n).is_file()]


def ticked_problems(change: CloudChange, tasks_path: Path) -> list[str]:
    if not tasks_path.is_file():
        return []
    names = [
        report_name("task_summary", task.sid, task.tid)
        for task in osl.parse_openspec_tasks(tasks_path, change.name)
        if task.done
    ]
    return _missing(change, names)


def closeout_problems(change: CloudChange) -> list[str]:
    names: list[str] = []
    for number in change.slices_done:
        sid = f"S{number:02d}"
        names += [report_name("slice_uat", sid), report_name("slice_summary", sid)]
    if change.status == "DONE" and change.archive == "declined" and not change.archived:
        names += [report_name("validation"), report_name("summary")]
    return _missing(change, names)


def neutral_problems(change: CloudChange) -> list[str]:
    found: list[str] = []
    for path in sorted(change.path.rglob("*")):
        rel = path.relative_to(change.path).as_posix()
        if "w2c" in rel.lower() or (path.is_file() and "w2c" in _read(path).lower()):
            found.append(f"{change.name}: {rel}")
    return found


def smoke_rows(root: Path, changes: list[CloudChange]) -> list[tuple[str, str, str]]:
    """The cloud smoke rows. Archived changes are history: they skip the live
    OpenSpec rows and the report, neutrality, and Verify checks."""
    if not changes:
        return []
    rows: list[tuple[str, str, str]] = []
    cli_row, cli_ok = osl.cli_check()
    rows.append(cli_row)

    problems: dict[str, list[str]] = {
        name: []
        for name in (
            "delivery-keys-valid",
            "design-sections",
            "git-operation-plan",
            "commit-pr-conventions",
            "manual-test-guide",
            "slice-fields",
            "read-first-present",
            "openspec-validate-strict",
            "openspec-artifacts-complete",
            "openspec-tasks-have-verify",
            "openspec-progress-agrees",
            "ticked-without-report",
            "closeout-reports",
            "neutral-artifacts",
            "unique-change-ids",
            "openspec-archived-when-done",
        )
    }

    def tag(change: CloudChange, items: list[str]) -> list[str]:
        return [f"{change.name}: {item}" for item in items]

    for change in changes:
        design = change.path / "design.md"
        tasks = change.path / "tasks.md"
        tasks_text = _read(tasks) if tasks.is_file() else None
        problems["delivery-keys-valid"] += tag(change, key_problems(change))
        for name, found in design_problems(_read(design) if design.is_file() else None).items():
            problems[name] += tag(change, found)
        if tasks_text is None:
            problems["slice-fields"].append(f"{change.name}: tasks.md missing")
        else:
            for number, fields in slice_fields(tasks_text).items():
                lacking = [f for f in layout.SLICE_FIELDS if f not in fields]
                empty = [f for f in layout.SLICE_FIELDS if f in fields and not fields[f].strip()]
                if lacking:
                    problems["slice-fields"].append(
                        f"{change.name} group {number}: lacks {', '.join(lacking)}"
                    )
                if empty:
                    problems["slice-fields"].append(
                        f"{change.name} group {number}: empty {', '.join(empty)}"
                    )
        problems["read-first-present"] += tag(change, read_first_problems(tasks_text))
        if (
            change.status == "DONE" and not change.archived and change.archive != "declined"
        ):
            problems["openspec-archived-when-done"].append(
                f"{change.name}: done without archive or declined"
            )
        if change.archived:
            continue
        problems["closeout-reports"] += closeout_problems(change)
        problems["ticked-without-report"] += ticked_problems(change, tasks)
        problems["neutral-artifacts"] += neutral_problems(change)
        if tasks.is_file():
            for task in osl.parse_openspec_tasks(tasks, change.name):
                if not task.verify:
                    problems["openspec-tasks-have-verify"].append(
                        f"{change.name} {task.openspec_id}: missing Verify line"
                    )
        if change.status == "DONE":
            continue
        if not cli_ok:
            for name in ("openspec-validate-strict", "openspec-artifacts-complete", "openspec-progress-agrees"):
                problems[name].append(f"{change.name}: openspec cli unavailable")
            continue
        validate, artifact, progress = osl.live_checks(root, change.name, tasks, change.name)
        problems["openspec-validate-strict"] += validate
        problems["openspec-artifacts-complete"] += artifact
        problems["openspec-progress-agrees"] += progress

    by_id: dict[str, list[str]] = {}
    for change in changes:
        if change.legacy_id:
            label = f"{change.name} (archived)" if change.archived else change.name
            by_id.setdefault(change.legacy_id, []).append(label)
    for legacy_id, names in sorted(by_id.items()):
        if len(names) > 1:
            problems["unique-change-ids"].append(f"{legacy_id}: {', '.join(sorted(names))}")

    for name, found in problems.items():
        rows.append((name, "FAIL" if found else "PASS", "; ".join(found[:8])))
    order = [
        "openspec-cli", "delivery-keys-valid", "design-sections", "git-operation-plan",
        "commit-pr-conventions", "manual-test-guide", "slice-fields", "read-first-present",
        "openspec-validate-strict", "openspec-artifacts-complete", "openspec-tasks-have-verify",
        "openspec-progress-agrees", "ticked-without-report", "closeout-reports",
        "neutral-artifacts", "unique-change-ids", "openspec-archived-when-done",
    ]
    rows.sort(key=lambda row: order.index(row[0]))
    return rows
