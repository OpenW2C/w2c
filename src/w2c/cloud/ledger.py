"""Delivery state for cloud mode, kept in each OpenSpec change.

State lives in top-level `x-delivery-*` keys of `<change>/.openspec.yaml`.
Standard library only. The CLI package is imported lazily.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from w2c import local as w2c_local

STATUSES: tuple[str, ...] = ("PLANNING", "TODO", "INPROGRESS", "PAUSED", "STOP", "ERROR", "DONE")
CADENCES = w2c_local.GIT_DELIVERY_VALUES

PREFIX = "x-delivery-"
KEY_LINE_RE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*)\s*:(?:\s+(.*?))?\s*$")
ARCHIVE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
INT_RE = re.compile(r"-?\d+")


def _cli():
    from w2c import cli as w2c_cli

    return w2c_cli


@dataclass
class CloudChange:
    name: str
    path: Path
    status: str
    order: int | None
    cadence: str
    slices_done: list[int]
    legacy_id: str
    archived: bool
    archive: str
    amend_lock: str
    amend_prior_status: str
    amend_decision: str


def _clean_value(raw: str | None) -> str:
    value = (raw or "").strip()
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        if end != -1:
            return value[1:end]
        return value[1:]
    return re.sub(r"\s+#.*$", "", value).strip()


def _read_raw(meta: Path) -> str:
    return meta.read_bytes().decode("utf-8")


def read_keys(meta: Path) -> dict[str, str]:
    """Top-level `key: value` lines. Duplicate `x-delivery-*` keys are an error."""
    keys: dict[str, str] = {}
    for line in _read_raw(meta).splitlines():
        match = KEY_LINE_RE.match(line)
        if not match:
            continue
        key = match.group(1)
        if key.startswith(PREFIX) and key in keys:
            raise _cli().W2CError(f"{meta}: duplicate key {key!r}")
        keys[key] = _clean_value(match.group(2))
    return keys


def write_key(meta: Path, key: str, value: str | None) -> None:
    """Replace, append, or remove (value None) one top-level key. Atomic."""
    cli = _cli()
    text = _read_raw(meta)
    lines = text.splitlines(keepends=True)
    eol = "\r\n" if "\r\n" in text else "\n"
    out: list[str] = []
    found = False
    for line in lines:
        match = KEY_LINE_RE.match(line.rstrip("\r\n"))
        if match and match.group(1) == key:
            if found:
                raise cli.W2CError(f"{meta}: duplicate key {key!r}")
            found = True
            if value is not None:
                ending = line[len(line.rstrip("\r\n")) :]
                out.append(f"{key}: {value}{ending}")
            continue
        out.append(line)
    if not found and value is not None:
        if out and not out[-1].endswith(("\n", "\r")):
            out[-1] += eol
        out.append(f"{key}: {value}{eol}")
    cli.atomic_write(meta, "".join(out))


def _parse_int(raw: str) -> int | None:
    return int(raw) if INT_RE.fullmatch(raw.strip()) else None


def _parse_int_list(raw: str) -> list[int]:
    body = raw.strip()
    if body.startswith("["):
        body = body[1:]
    if body.endswith("]"):
        body = body[:-1]
    return [int(part) for part in body.split(",") if INT_RE.fullmatch(part.strip())]


def load_change(path: Path) -> CloudChange | None:
    meta = path / ".openspec.yaml"
    if not meta.is_file():
        return None
    keys = read_keys(meta)
    status = keys.get(PREFIX + "status", "")
    if not status:
        return None

    def get(name: str) -> str:
        return keys.get(PREFIX + name, "")

    archived = path.parent.name == "archive"
    name = ARCHIVE_PREFIX_RE.sub("", path.name) if archived else path.name
    return CloudChange(
        name=name,
        path=path,
        status=status,
        order=_parse_int(get("order")),
        cadence=get("cadence"),
        slices_done=_parse_int_list(get("slices-done")),
        legacy_id=get("legacy-id"),
        archived=archived,
        archive=get("archive"),
        amend_lock=get("amend-lock"),
        amend_prior_status=get("amend-prior-status"),
        amend_decision=get("amend-decision"),
    )


def _scan(folder: Path) -> list[CloudChange]:
    if not folder.is_dir():
        return []
    found: list[CloudChange] = []
    for child in sorted(folder.iterdir()):
        if not child.is_dir() or child.name == "archive":
            continue
        change = load_change(child)
        if change is not None:
            found.append(change)
    return found


def list_changes(root: Path, *, include_archived: bool = False) -> list[CloudChange]:
    base = root / "openspec" / "changes"
    changes = _scan(base)
    if include_archived:
        changes += _scan(base / "archive")
    changes.sort(key=lambda c: (c.order is None, c.order or 0, c.name))
    return changes


def resolve(root: Path, ident: str) -> CloudChange:
    cli = _cli()
    changes = list_changes(root, include_archived=True)
    active = [c for c in changes if not c.archived and c.name == ident]
    archived = [c for c in changes if c.archived and c.name == ident]
    legacy = [c for c in changes if c.legacy_id and c.legacy_id == ident]
    named = active or archived
    involved = named + [c for c in legacy if all(c.path != n.path for n in named)]
    if len(involved) > 1:
        names = ", ".join(sorted(f"{c.name} (archived)" if c.archived else c.name for c in involved))
        raise cli.W2CError(f"{ident!r} matches more than one change: {names}")
    if involved:
        return involved[0]
    raise cli.W2CError(f"no cloud change named {ident!r}")


def remote_branch(change: CloudChange) -> str:
    design = change.path / "design.md"
    if not design.is_file():
        return ""
    fields = _cli().parse_table_under_heading(
        design.read_text(encoding="utf-8"), "Delivery Plan"
    )
    return fields.get("Remote branch", "").strip()


def branch_names(root: Path) -> set[str] | None:
    from w2c import ledger_store

    branch = ledger_store.current_branch(root)
    if not branch:
        return None
    names = {c.name for c in list_changes(root) if remote_branch(c) == branch}
    return names or None


def delivery_dir(change: CloudChange) -> Path:
    return change.path / ".delivery"
