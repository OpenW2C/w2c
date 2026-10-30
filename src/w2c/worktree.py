"""Create and remove ticket worktrees from the checkout that already exists.

W2C does not convert a repository to a bare container. It reads the current
layout and adds the worktree there.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from w2c import ledger_store as store

_INVALID_PARTS = frozenset({"", ".", ".."})


def list_worktrees(root: Path) -> list[tuple[Path, str]]:
    proc = store.git(root, "worktree", "list", "--porcelain", check=False)
    if proc.returncode != 0:
        raise store.LedgerError((proc.stderr or "git worktree list failed").strip())
    found: list[tuple[Path, str]] = []
    path: Path | None = None
    branch = ""
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            if path is not None:
                found.append((path, branch))
            path = Path(line.split(" ", 1)[1])
            branch = ""
        elif line.startswith("branch "):
            ref = line.split(" ", 1)[1]
            prefix = "refs/heads/"
            branch = ref[len(prefix) :] if ref.startswith(prefix) else ""
    if path is not None:
        found.append((path, branch))
    return found


def repo_layout(root: Path) -> tuple[str, Path]:
    if not store.is_git(root):
        raise store.LedgerError("not a git repository")
    return store.layout_kind(root)


def exclude_state(root: Path) -> str:
    kind, _base = repo_layout(root)
    if kind != "main-checkout":
        return "n/a"
    name = store.worktree_dirname(root).rstrip("/")
    text = _exclude_text(root)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in {name, name + "/"}:
            return "already-set"
    return "missing"


def layout_report(root: Path) -> str:
    kind, base = repo_layout(root)
    lines = [
        f"layout: {kind}",
        f"root: {base}",
        f"worktree_dir: {store.worktree_dirname(root)}",
        f"exclude: {exclude_state(root)}",
    ]
    return "\n".join(lines) + "\n"


def branch_dest(root: Path, branch: str) -> Path:
    parts = _branch_parts(branch)
    kind, base = repo_layout(root)
    if kind == "main-checkout":
        return base.joinpath(store.worktree_dirname(root), *parts)
    return base.joinpath(*parts)


def _branch_parts(branch: str) -> tuple[str, ...]:
    if branch.startswith("/") or branch.startswith("~"):
        raise store.LedgerError(f"branch name must not be an absolute path: {branch}")
    parts = tuple(branch.split("/"))
    if any(part in _INVALID_PARTS for part in parts):
        raise store.LedgerError(f"branch name is not a safe directory path: {branch}")
    return parts


def _exclude_path(root: Path) -> Path:
    return store.common_dir(root) / "info" / "exclude"


def _exclude_text(root: Path) -> str:
    path = _exclude_path(root)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def apply_exclude(root: Path, choice: str) -> str:
    """Append the worktree directory to ``info/exclude`` when the choice is yes."""
    state = exclude_state(root)
    if state in {"n/a", "already-set"}:
        return state
    if choice != "yes":
        return "exclude-no"
    path = _exclude_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = store.worktree_dirname(root).rstrip("/") + "/"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + name + "\n", encoding="utf-8")
    return "exclude-yes"


def _checkout(root: Path, branch: str) -> Path | None:
    for path, name in list_worktrees(root):
        if name == branch:
            return path
    return None


def _branch_exists(root: Path, branch: str) -> bool:
    proc = store.git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False)
    return proc.returncode == 0


def _assert_dest_outside_linked(root: Path, dest: Path) -> None:
    dest_resolved = dest.resolve()
    for path, _branch in list_worktrees(root):
        if not store.is_linked_worktree(path):
            continue
        try:
            relative = dest_resolved.relative_to(path.resolve())
        except ValueError:
            continue
        if relative == Path("."):
            continue
        raise store.LedgerError("refusing to create a worktree inside a linked worktree")


def add_worktree(root: Path, branch: str, create_from: str | None, exclude: str) -> Path:
    if not store.is_git(root):
        raise store.LedgerError("not a git repository")
    if exclude not in {"yes", "no"}:
        raise store.LedgerError("exclude must be yes or no")
    dest = branch_dest(root, branch)
    existing = _checkout(root, branch)
    if existing is not None and existing.resolve() == dest.resolve():
        store.project_into(existing)
        return existing
    _assert_dest_outside_linked(root, dest)
    if existing is not None:
        kind, base = repo_layout(root)
        if kind == "main-checkout" and existing.resolve() == base.resolve():
            raise store.LedgerError(
                f"branch {branch} is checked out in the main checkout; "
                "switch the main checkout to another branch before adding a worktree"
            )
        raise store.LedgerError(f"branch {branch} is already checked out at {existing}")
    if dest.exists():
        raise store.LedgerError(f"worktree path already exists: {dest}")
    kind, _base = repo_layout(root)
    if kind == "main-checkout":
        apply_exclude(root, exclude)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if create_from and not _branch_exists(root, branch):
        store.git(root, "worktree", "add", "-b", branch, str(dest), create_from)
    elif _branch_exists(root, branch):
        store.git(root, "worktree", "add", str(dest), branch)
    else:
        raise store.LedgerError(f"branch {branch} does not exist; pass --create-from")
    store.project_into(dest)
    return dest


def _status_paths(worktree: Path) -> list[str]:
    proc = store.git(worktree, "status", "--porcelain=v1", "--untracked-files=all", check=False)
    if proc.returncode != 0:
        raise store.LedgerError((proc.stderr or "git status failed").strip())
    dirty: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        body = line[3:]
        if " -> " in body:
            body = body.split(" -> ", 1)[1]
        path = body.strip().strip('"')
        if path == ".w2c" or path.startswith(".w2c/"):
            continue
        dirty.append(line)
    return dirty


def remove_worktree(root: Path, branch: str, assume_yes: bool) -> None:
    if not store.is_git(root):
        raise store.LedgerError("not a git repository")
    existing = _checkout(root, branch)
    if existing is None:
        raise store.LedgerError(f"no worktree is checked out on {branch}")
    kind, base = repo_layout(root)
    if kind == "main-checkout" and existing.resolve() == base.resolve():
        raise store.LedgerError("refusing to remove the main checkout")
    if not assume_yes:
        if not sys.stdin.isatty():
            raise store.LedgerError("pass --yes to remove the worktree")
        answer = input(f"Remove worktree for {branch}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            raise store.LedgerError("worktree left in place")
    store.adopt_store(existing)
    projection = existing / ".w2c"
    if (
        store.is_linked_worktree(existing)
        and not store.tracking(existing)
        and projection.is_dir()
        and not projection.is_symlink()
    ):
        store.sync_finish(existing)
    dirty = _status_paths(existing)
    if dirty:
        listed = "\n".join(dirty)
        raise store.LedgerError(f"worktree is not clean:\n{listed}")
    projection = existing / ".w2c"
    if not store.tracking(existing) and (projection.is_symlink() or projection.exists()):
        if projection.is_symlink() or projection.is_file():
            projection.unlink()
        else:
            shutil.rmtree(projection)
    _kind, base = repo_layout(root)
    proc = store.git(base, "worktree", "remove", str(existing), check=False, cwd=base)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "git worktree remove failed").strip()
        raise store.LedgerError(detail)
