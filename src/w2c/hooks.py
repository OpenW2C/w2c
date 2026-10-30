"""Named Git hooks installed into the common Git directory, never into the product tree."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

from w2c import ledger_store as store
from w2c import local as w2c_local

HOOKS = {
    "deny-ledger": {"git_hook": "pre-commit", "wrap_foreign": False},
    "openspec-archive": {"git_hook": "pre-push", "wrap_foreign": True},
}


def _script(name: str, filename: str) -> str:
    here = Path(__file__).resolve()
    candidates = [
        here.parent / "assets" / "hooks" / name / filename,
        w2c_local.data_home() / "hooks" / name / filename,
    ]
    if len(here.parents) >= 3:
        candidates.append(here.parents[2] / "hooks" / name / filename)
    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise store.LedgerError(f"missing hook script for {name}")


def hooks_dir(root: Path) -> Path:
    proc = store.git(root, "config", "--get", "core.hooksPath", check=False)
    raw = proc.stdout.strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = (root / path).resolve()
        return path
    return store.common_dir(root) / "hooks"


def _spec(name: str) -> dict[str, object]:
    if name not in HOOKS:
        raise store.LedgerError(f"unknown hook {name}")
    return HOOKS[name]


def _dest(root: Path, name: str) -> Path:
    spec = _spec(name)
    return hooks_dir(root) / str(spec["git_hook"])


def _is_ours(path: Path, name: str) -> bool:
    if not path.is_file():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()[:8]
    return any(line.strip() == f"# w2c-hook: {name}" for line in lines)


def status(root: Path) -> str:
    if not store.is_git(root):
        raise store.LedgerError("not a git repository")
    lines: list[str] = []
    for name, spec in HOOKS.items():
        dest = hooks_dir(root) / str(spec["git_hook"])
        if not _is_ours(dest, name):
            lines.append(f"{name}: not installed")
            continue
        backup = dest.with_name(f"{spec['git_hook']}.w2c-previous")
        if backup.exists():
            lines.append(f"{name}: installed (wrapped)")
        else:
            lines.append(f"{name}: installed")
    return "\n".join(lines) + "\n"


def add(root: Path, name: str) -> str:
    if not store.is_git(root):
        raise store.LedgerError("not a git repository")
    spec = _spec(name)
    dest = _dest(root, name)
    git_hook = str(spec["git_hook"])
    if _is_ours(dest, name):
        return f"{name}: already installed"
    if dest.exists() and not spec["wrap_foreign"]:
        raise store.LedgerError(
            f"{git_hook} already exists and is not a w2c hook; left it unchanged"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    backup = dest.with_name(f"{git_hook}.w2c-previous")
    if dest.exists():
        if backup.exists():
            raise store.LedgerError(f"{backup.name} already exists; left {git_hook} unchanged")
        backup.write_bytes(dest.read_bytes())
        backup.chmod(dest.stat().st_mode)
    text = _script(name, git_hook)
    dest.write_text(text, encoding="utf-8")
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if backup.exists():
        return f"{name}: installed (wrapped)"
    return f"{name}: installed"


def remove(root: Path, name: str) -> str:
    if not store.is_git(root):
        raise store.LedgerError("not a git repository")
    spec = _spec(name)
    dest = _dest(root, name)
    if not _is_ours(dest, name):
        raise store.LedgerError(f"{name} is not installed")
    backup = dest.with_name(f"{spec['git_hook']}.w2c-previous")
    if backup.exists():
        dest.write_bytes(backup.read_bytes())
        dest.chmod(backup.stat().st_mode)
        backup.unlink()
        return f"{name}: removed; previous {spec['git_hook']} restored"
    dest.unlink()
    return f"{name}: removed"


def ensure_openspec_archive(root: Path) -> None:
    if not store.is_git(root):
        return
    add(root, "openspec-archive")


def run(root: Path, name: str, stdin: str) -> int:
    if not store.is_git(root):
        raise store.LedgerError("not a git repository")
    _spec(name)
    if name == "deny-ledger":
        return _run_deny(root)
    if name == "openspec-archive":
        return _run_archive(root, stdin)
    raise store.LedgerError(f"unknown hook {name}")


def _run_deny(root: Path) -> int:
    if store.tracking(root):
        return 0
    proc = store.git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", check=False)
    if proc.returncode != 0:
        print(proc.stderr.strip() or "git diff failed", file=sys.stderr)
        return 1
    bad = [
        line
        for line in proc.stdout.splitlines()
        if line == ".w2c" or line.startswith(".w2c/")
    ]
    if not bad:
        return 0
    print("w2c deny-ledger: refusing to commit .w2c/ while track is false", file=sys.stderr)
    for line in bad:
        print(line, file=sys.stderr)
    return 1


def _run_archive(root: Path, stdin: str) -> int:
    from w2c import openspec_push

    pairs: list[tuple[str, str]] = []
    for line in stdin.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        pairs.append((parts[0], parts[1]))
    found = openspec_push.check_push(root, pairs)
    if not found:
        return 0
    for line in found:
        print(line, file=sys.stderr)
    return 1
