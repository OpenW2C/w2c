"""Refuse a push when a finished OpenSpec milestone is not archived in that commit."""

from __future__ import annotations

from pathlib import Path

from w2c.local import PLANNING_OPENSPEC


def _cli():
    from w2c import cli as w2c_cli

    return w2c_cli


def _openspec():
    from w2c import openspec_ledger

    return openspec_ledger


def branch_from_ref(ref: str) -> str:
    prefix = "refs/heads/"
    if not ref.startswith(prefix):
        return ""
    return ref[len(prefix) :]


def _tree_has(root: Path, sha: str, path: str) -> bool:
    from w2c import ledger_store as store

    proc = store.git(root, "cat-file", "-e", f"{sha}:{path}", check=False)
    return proc.returncode == 0


def _archive_files(value: str) -> list[str]:
    value = value.strip().strip("/")
    if not value or value == "declined":
        return []
    paths = [value]
    if not value.startswith("openspec/"):
        paths.append(f"openspec/changes/archive/{value}")
    return [f"{path}/.openspec.yaml" for path in paths]


def milestone_ready(root: Path, mid: str) -> bool:
    cli = _cli()
    plan_dir = cli.plan_dir_for(root, mid)
    if plan_dir is None:
        return False
    road = plan_dir / f"{mid}-ROADMAP.md"
    if not road.is_file():
        return False
    slices = [item for item in cli.parse_slices(road.read_text(encoding="utf-8")) if not item.dropped]
    if not slices or not all(item.done for item in slices):
        return False
    tasks = [task for task in cli.all_tasks(root) if task.mid == mid and not task.dropped]
    if not tasks or not all(task.done for task in tasks):
        return False
    return True


def problems_for(root: Path, ref: str, sha: str) -> list[str]:
    """Return reasons this ref cannot be pushed. An empty list allows the push."""
    if not sha or set(sha) <= {"0"}:
        return []
    branch = branch_from_ref(ref)
    if not branch:
        return []
    cli = _cli()
    ledger = _openspec()
    found: list[str] = []
    milestones = cli.parse_milestones(cli.read_text(cli.w2c_dir(root) / "ROADMAP.md"))
    for milestone in milestones:
        plan_dir = cli.plan_dir_for(root, milestone.mid)
        if plan_dir is None:
            continue
        road = plan_dir / f"{milestone.mid}-ROADMAP.md"
        if not road.is_file():
            continue
        text = road.read_text(encoding="utf-8")
        if ledger.planning_mode(text) != PLANNING_OPENSPEC:
            continue
        fields = cli.parse_git_operation_fields(text)
        if fields.get("Remote branch", "").strip() != branch:
            continue
        if not milestone_ready(root, milestone.mid):
            continue
        archived = ledger.archive_value(text)
        files = _archive_files(archived)
        if not files:
            label = archived or "empty"
            found.append(
                f"{milestone.mid}: OpenSpec archive is {label}; "
                f"run `w2c spec-archive {milestone.mid}` before push"
            )
            continue
        if not any(_tree_has(root, sha, path) for path in files):
            found.append(
                f"{milestone.mid}: commit {sha[:12]} does not contain the archived change"
            )
    found.extend(_cloud_problems(root, branch, sha))
    return found


def _folder_branch(folder: Path) -> str:
    try:
        text = (folder / "design.md").read_text(encoding="utf-8")
        from w2c.cloud import ledger as cloud

        fields = cloud.delivery_plan_fields(text)
    except (OSError, UnicodeDecodeError):
        return ""
    return fields.get("Remote branch", "").strip()


def _cloud_folders(root: Path) -> list[Path]:
    base = root / "openspec" / "changes"
    found: list[Path] = []
    for parent in (base, base / "archive"):
        if parent.is_dir():
            found += [c for c in sorted(parent.iterdir()) if c.is_dir() and c.name != "archive"]
    return found


def _cloud_problems(root: Path, branch: str, sha: str) -> list[str]:
    from w2c.cloud import commands, ledger as cloud

    found: list[str] = []
    for folder in _cloud_folders(root):
        if _folder_branch(folder) != branch:
            continue
        try:
            change = cloud.load_change(folder)
        except (_cli().W2CError, UnicodeDecodeError, OSError) as exc:
            archived = folder.parent.name == "archive"
            name = cloud.ARCHIVE_PREFIX_RE.sub("", folder.name) if archived else folder.name
            found.append(f"{name}: cannot read .openspec.yaml: {exc}")
            continue
        if change is None:
            continue
        name = change.name
        if change.archived:
            meta = f"openspec/changes/archive/{change.path.name}/.openspec.yaml"
            if not _tree_has(root, sha, meta):
                found.append(f"{name}: commit {sha[:12]} does not contain the archived change")
        elif change.status == "DONE" and change.archive == "declined":
            found.append(
                f"{name}: archive is declined; run w2c cloud archive {name} before push"
            )
        elif commands.all_closed(change):
            found.append(f"{name}: archive the change with w2c cloud archive {name} before push")
    return found


def check_push(root: Path, pairs: list[tuple[str, str]]) -> list[str]:
    found: list[str] = []
    for ref, sha in pairs:
        found.extend(problems_for(root, ref, sha))
    return found
