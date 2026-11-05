"""Create and remove ticket worktrees from the checkout that already exists.

W2C does not convert a repository to a bare container. It reads the current
layout and adds the worktree there.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from w2c import ledger_store as store
from w2c import local as w2c_local

_INVALID_PARTS = frozenset({"", ".", ".."})
_SEED_BASENAMES = frozenset({".env", ".env.local", ".envrc.local"})
_SEED_SKIP_DIRS = frozenset(
    {
        ".git",
        ".worktrees",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        "__pycache__",
        ".tox",
        ".yarn",
        "coverage",
    }
)


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



def seed_source_root(root: Path) -> Path:
    """Return the checkout that holds local seed files (usually the main checkout)."""
    kind, base = repo_layout(root)
    if kind == "main-checkout":
        return base.resolve()
    if not store.is_linked_worktree(root):
        return root.resolve()
    for path, _branch in list_worktrees(root):
        if not store.is_linked_worktree(path):
            return path.resolve()
    trees = list_worktrees(root)
    if trees:
        return trees[0][0].resolve()
    return root.resolve()


def suggest_worktree_seed(root: Path) -> list[str]:
    """List common gitignored env files under ``root`` for init / --suggest."""
    source = root.resolve()
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SEED_SKIP_DIRS and not d.startswith(".")
        )
        for name in filenames:
            if name not in _SEED_BASENAMES:
                continue
            rel = Path(dirpath, name).relative_to(source).as_posix()
            found.append(rel)
    return sorted(found)


def _seed_paths_for(root: Path, dest: Path) -> list[str]:
    source = seed_source_root(root)
    paths = list(w2c_local.load_repo_config(source).get("worktree_seed") or [])
    if not paths:
        paths = list(w2c_local.load_repo_config(dest).get("worktree_seed") or [])
    if not paths:
        paths = list(w2c_local.load_repo_config(root).get("worktree_seed") or [])
    return paths


def _rel_symlink(link: Path, target: Path) -> None:
    """Create a relative symlink. Prefer abspath over realpath (macOS /private)."""
    link.parent.mkdir(parents=True, exist_ok=True)
    abs_target = os.path.abspath(target)
    abs_parent = os.path.abspath(link.parent)
    link.symlink_to(os.path.relpath(abs_target, start=abs_parent))


def _same_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return os.path.abspath(left) == os.path.abspath(right) or (
            os.path.realpath(left) == os.path.realpath(right)
        )


def seed_local_files(source: Path, dest: Path, paths: list[str]) -> list[str]:
    """Symlink configured local files from ``source`` into ``dest``. Never overwrite."""
    lines: list[str] = []
    for rel in paths:
        src = source / rel
        dst = dest / rel
        if not src.exists():
            lines.append(f"seed-skip missing-source {rel}")
            continue
        if dst.is_symlink():
            if _same_file(dst, src):
                lines.append(f"seed-ok {rel}")
                continue
            lines.append(f"seed-conflict {rel}")
            continue
        if dst.exists():
            lines.append(f"seed-conflict {rel}")
            continue
        _rel_symlink(dst, src)
        lines.append(f"seed-linked {rel}")
    return lines


def check_seeded(source: Path, dest: Path, paths: list[str]) -> list[str]:
    """Return problem lines for configured paths (strict: missing source is a failure)."""
    problems: list[str] = []
    for rel in paths:
        src = source / rel
        if not src.exists():
            problems.append(f"seed-missing-source {rel}")
            continue
        dst = dest / rel
        if not dst.exists() and not dst.is_symlink():
            problems.append(f"seed-missing {rel}")
            continue
        if not dst.is_symlink():
            problems.append(f"seed-conflict {rel}")
            continue
        if not _same_file(dst, src):
            problems.append(f"seed-conflict {rel}")
    return problems


def _seed_policy_for(root: Path, dest: Path | None = None) -> str:
    source = seed_source_root(root)
    policy = str(
        w2c_local.load_repo_config(source).get("worktree_seed_policy")
        or w2c_local.WORKTREE_SEED_POLICY_UNSET
    )
    if policy == w2c_local.WORKTREE_SEED_POLICY_UNSET and dest is not None:
        policy = str(
            w2c_local.load_repo_config(dest).get("worktree_seed_policy")
            or w2c_local.WORKTREE_SEED_POLICY_UNSET
        )
    if policy == w2c_local.WORKTREE_SEED_POLICY_UNSET:
        policy = str(
            w2c_local.load_repo_config(root).get("worktree_seed_policy")
            or w2c_local.WORKTREE_SEED_POLICY_UNSET
        )
    try:
        return w2c_local.normalize_worktree_seed_policy(policy)
    except w2c_local.LocalError:
        return w2c_local.WORKTREE_SEED_POLICY_UNSET


def check_worktree_seed(root: Path, dest: Path) -> list[str]:
    """Policy-aware seed check for ``dest`` (usually the current worktree)."""
    policy = _seed_policy_for(root, dest)
    if policy == w2c_local.WORKTREE_SEED_POLICY_UNSET:
        return ["seed-policy-unset"]
    if policy == w2c_local.WORKTREE_SEED_POLICY_NONE:
        return []
    source = seed_source_root(root)
    return check_seeded(source, dest, _seed_paths_for(root, dest))


def seed_worktree(root: Path, dest: Path) -> list[str]:
    """Apply ``worktree_seed`` from config into ``dest``."""
    policy = _seed_policy_for(root, dest)
    if policy == w2c_local.WORKTREE_SEED_POLICY_UNSET:
        raise store.LedgerError(
            "worktree_seed_policy is unset; finish planning "
            "(set worktree_seed_policy to none or paths in .w2c/config.toml)"
        )
    if policy == w2c_local.WORKTREE_SEED_POLICY_NONE:
        return ["seed-policy-none"]
    source = seed_source_root(root)
    return seed_local_files(source, dest, _seed_paths_for(root, dest))


def add_worktree(root: Path, branch: str, create_from: str | None, exclude: str) -> Path:
    if not store.is_git(root):
        raise store.LedgerError("not a git repository")
    if exclude not in {"yes", "no"}:
        raise store.LedgerError("exclude must be yes or no")
    dest = branch_dest(root, branch)
    existing = _checkout(root, branch)
    if existing is not None and existing.resolve() == dest.resolve():
        store.project_into(existing)
        for line in seed_worktree(root, existing):
            print(line, file=sys.stderr)
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
    for line in seed_worktree(root, dest):
        print(line, file=sys.stderr)
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
