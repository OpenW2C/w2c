"""Ledger files under the Git common directory, shared by every worktree.

The store is ``<git-common-dir>/w2c/ledger``. Git does not commit or push
paths inside the common directory. ``track = true`` keeps a normal ``.w2c``
directory in the checkout and does not use this store.
"""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from w2c import local as w2c_local

LEDGER_MODES = frozenset({"symlink", "copy", "materialize"})
SHARED_FILES = (
    "config.toml",
    "STATE.md",
    "QUEUE.md",
    "ROADMAP.md",
    "DECISIONS.md",
    "DELIVERY-PROFILE.md",
)
SHARED_DIRS = ("contexts", "runtime")
_REMOTE_RE = re.compile(r"^\|\s*Remote branch\s*\|\s*([^|]*)\|")
_PLAN_DIR_RE = re.compile(r"^M\d+")

NO_SESSION_CMDS = frozenset({"help", "trials", "install-skills"})
SESSION_WITHOUT_LEDGER = frozenset(
    {
        "init",
        "worktree-add",
        "worktree-remove",
        "ledger-bind",
        "hook",
        "openspec-push-check",
    }
)


class LedgerError(Exception):
    """User-facing ledger or worktree failure."""


def git(
    root: Path,
    *args: str,
    check: bool = True,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd is not None else None,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "git failed").strip()
        raise LedgerError(detail)
    return proc


def is_git(root: Path) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _abs_git_path(root: Path, raw: str) -> Path:
    path = Path(raw.strip())
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def common_dir(root: Path) -> Path:
    proc = git(root, "rev-parse", "--git-common-dir")
    return _abs_git_path(root, proc.stdout)


def git_dir(root: Path) -> Path:
    proc = git(root, "rev-parse", "--git-dir")
    return _abs_git_path(root, proc.stdout)


def is_linked_worktree(root: Path) -> bool:
    if not is_git(root):
        return False
    return git_dir(root) != common_dir(root)


def current_branch(root: Path) -> str:
    if not is_git(root):
        return ""
    proc = git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    if proc.returncode != 0:
        return ""
    name = proc.stdout.strip()
    if not name or name == "HEAD":
        return ""
    return name


def store_dir(root: Path) -> Path:
    return common_dir(root) / "w2c" / "ledger"


def _config_path(root: Path) -> Path | None:
    local = root / ".w2c" / "config.toml"
    if local.is_file():
        return local
    stored = store_dir(root) / "config.toml" if is_git(root) else None
    if stored is not None and stored.is_file():
        return stored
    return None


def tracking(root: Path) -> bool:
    path = _config_path(root)
    if path is None:
        return False
    if path.is_relative_to(root) or (root / ".w2c" / "config.toml").is_file():
        return w2c_local.is_track_enabled(root)
    data = w2c_local.parse_toml(path.read_text(encoding="utf-8"))
    return bool(data.get("track", False))


def ledger_mode(root: Path) -> str:
    path = _config_path(root)
    if path is None:
        return "materialize"
    data = w2c_local.parse_toml(path.read_text(encoding="utf-8"))
    mode = str(data.get("worktree_ledger") or "materialize")
    if mode not in LEDGER_MODES:
        return "materialize"
    return mode


def worktree_dirname(root: Path) -> str:
    path = _config_path(root)
    raw = ".worktrees"
    if path is not None:
        data = w2c_local.parse_toml(path.read_text(encoding="utf-8"))
        raw = str(data.get("worktree_dir") or ".worktrees").strip() or ".worktrees"
    parts = Path(raw).parts
    if not parts or raw.startswith("/") or any(part in {".", ".."} for part in parts):
        return ".worktrees"
    return raw


def remote_branch(plan_dir: Path) -> str:
    if not plan_dir.is_dir():
        return ""
    for road in sorted(plan_dir.glob("M*-ROADMAP.md")):
        for line in road.read_text(encoding="utf-8").splitlines():
            match = _REMOTE_RE.match(line)
            if match:
                return match.group(1).strip()
    return ""


def _plan_dirs(base: Path) -> list[Path]:
    plans = base / "plans"
    if not plans.is_dir():
        return []
    found = [path for path in plans.iterdir() if path.is_dir() and _PLAN_DIR_RE.match(path.name)]
    return sorted(found, key=lambda path: path.name)


def _owned(plan_dir: Path, branch: str, other: Path | None) -> bool:
    if not branch:
        return False
    remote = remote_branch(plan_dir)
    if remote:
        return remote == branch
    if other is not None and other.exists():
        other_remote = remote_branch(other)
        if other_remote and other_remote != branch:
            return False
    return True


def _replace_tree(src: Path, dst: Path) -> None:
    if dst.is_symlink() or dst.is_file():
        dst.unlink()
    elif dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=True)


def _copy_file(src: Path, dst: Path) -> None:
    if not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_dir() and not dst.is_symlink():
        shutil.rmtree(dst)
    shutil.copy2(src, dst)


def _copy_named(src_root: Path, dst_root: Path, names_files: tuple[str, ...], names_dirs: tuple[str, ...]) -> None:
    for name in names_files:
        _copy_file(src_root / name, dst_root / name)
    for name in names_dirs:
        src = src_root / name
        if src.is_dir():
            _replace_tree(src, dst_root / name)


def _rel_symlink(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.is_file():
        link.unlink()
    elif link.exists():
        raise LedgerError(f"refusing to replace {link}")
    link.symlink_to(os.path.relpath(target, link.parent))


def _worktree_paths(root: Path) -> list[Path]:
    proc = git(root, "worktree", "list", "--porcelain", check=False)
    if proc.returncode != 0:
        return []
    found: list[Path] = []
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            found.append(Path(line.split(" ", 1)[1]))
    return found


def layout_kind(root: Path) -> tuple[str, Path]:
    """Return ``main-checkout`` or ``bare-container`` and the container directory."""
    common = common_dir(root)
    base = common.parent
    for path in _worktree_paths(root):
        if path.resolve() == base.resolve():
            return "main-checkout", base
    return "bare-container", base


def is_main_checkout(root: Path) -> bool:
    if not is_git(root) or is_linked_worktree(root):
        return False
    kind, base = layout_kind(root)
    return kind == "main-checkout" and root.resolve() == base.resolve()


def logical_rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        pass
    if is_git(root):
        store = store_dir(root)
        try:
            return str(Path(".w2c") / path.resolve().relative_to(store.resolve()))
        except ValueError:
            pass
    return str(path)


def _exclude_ledger_symlink(root: Path) -> None:
    """Ignore the main ``.w2c`` symlink locally. Do not change a committed gitignore."""
    path = common_dir(root) / "info" / "exclude"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if any(line.strip() == ".w2c" for line in existing.splitlines()):
        return
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + ".w2c\n", encoding="utf-8")


def adopt_store(root: Path) -> None:
    """Move a real main-checkout ``.w2c`` into the store when ``track`` is false."""
    if not is_git(root) or tracking(root):
        return
    store = store_dir(root)
    link = root / ".w2c"
    if is_main_checkout(root):
        if link.is_symlink():
            _exclude_ledger_symlink(root)
            return
        if link.is_dir():
            if store.exists():
                print(
                    "w2c: left existing .w2c in place because the git-dir ledger already exists",
                    file=sys.stderr,
                )
                return
            store.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(link), str(store))
            _rel_symlink(link, store)
            _exclude_ledger_symlink(root)
            return
        if store.is_dir() and not link.exists():
            _rel_symlink(link, store)
            _exclude_ledger_symlink(root)
        return
    if is_linked_worktree(root) and link.is_dir() and not link.is_symlink() and not store.exists():
        store.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(link), str(store))


def sync_start(root: Path) -> None:
    """Copy this worktree's milestone folder up, then shared files down."""
    proj = root / ".w2c"
    store = store_dir(root)
    if not proj.is_dir() or proj.is_symlink() or not store.is_dir():
        return
    branch = current_branch(root)
    for plan in _plan_dirs(proj):
        dest = store / "plans" / plan.name
        if _owned(plan, branch, dest if dest.exists() else None):
            _replace_tree(plan, dest)
    _copy_named(store, proj, SHARED_FILES, SHARED_DIRS)
    for plan in _plan_dirs(store):
        dest = proj / "plans" / plan.name
        owned = _owned(plan, branch, dest if dest.exists() else None)
        if owned and not dest.exists():
            _replace_tree(plan, dest)
        elif not owned:
            _replace_tree(plan, dest)


def sync_finish(root: Path) -> None:
    """Copy this worktree's milestone folder and shared files back to the store."""
    proj = root / ".w2c"
    store = store_dir(root)
    if not proj.is_dir() or proj.is_symlink():
        return
    store.mkdir(parents=True, exist_ok=True)
    branch = current_branch(root)
    _copy_named(proj, store, SHARED_FILES, SHARED_DIRS)
    for plan in _plan_dirs(proj):
        dest = store / "plans" / plan.name
        if _owned(plan, branch, dest if dest.exists() else None):
            _replace_tree(plan, dest)


def refresh_projection(root: Path) -> None:
    """Give a linked worktree a ``.w2c`` it can read."""
    if not is_linked_worktree(root) or tracking(root):
        return
    mode = ledger_mode(root)
    store = store_dir(root)
    proj = root / ".w2c"
    if mode == "symlink":
        if not proj.exists() and store.is_dir():
            _rel_symlink(proj, store)
        return
    if proj.is_symlink() and mode == "materialize":
        proj.unlink()
    if mode == "copy":
        if not proj.exists() and store.is_dir():
            shutil.copytree(store, proj, symlinks=True)
        return
    if not proj.exists() and store.is_dir():
        shutil.copytree(store, proj, symlinks=True)
        return
    if proj.is_dir():
        sync_start(root)


def project_into(worktree: Path) -> None:
    """Create the ledger projection in a worktree this command just added."""
    if tracking(worktree):
        return
    refresh_projection(worktree)


def needs_session(root: Path, cmd: str | None) -> bool:
    if not cmd or cmd in NO_SESSION_CMDS or not is_git(root):
        return False
    if cmd in SESSION_WITHOUT_LEDGER:
        return True
    if (root / ".w2c").exists():
        return True
    try:
        return store_dir(root).is_dir()
    except LedgerError:
        return False


class LedgerSession:
    """Hold the ledger lock for one CLI command."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._fh = None

    def start(self) -> None:
        if tracking(self.root) and (self.root / ".w2c").exists():
            return
        gate = common_dir(self.root) / "w2c"
        gate.mkdir(parents=True, exist_ok=True)
        self._fh = open(gate / "ledger.lock", "a+")
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        adopt_store(self.root)
        refresh_projection(self.root)

    def finish(self) -> None:
        if self._fh is None:
            return
        try:
            link = self.root / ".w2c"
            moved = (
                is_linked_worktree(self.root)
                and link.is_dir()
                and not link.is_symlink()
                and not store_dir(self.root).exists()
            )
            adopt_store(self.root)
            if not tracking(self.root) and is_linked_worktree(self.root) and ledger_mode(self.root) == "materialize":
                if moved:
                    refresh_projection(self.root)
                elif link.is_dir() and not link.is_symlink():
                    sync_finish(self.root)
        finally:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None
