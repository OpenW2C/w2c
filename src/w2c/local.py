"""Local-first W2C paths: global config, repo config, gitignore, migrate."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

COPILOT_INSTRUCTION_RELPATHS = (
    Path(".github/instructions/work-to-chores.instructions.md"),
    Path(".github/instructions/do-chores.instructions.md"),
)
LEGACY_GITIGNORE_MARKERS = (
    ".w2c/scripts/",
    ".w2c/templates/",
    ".w2c/runtime/",
)
DEFAULT_GITIGNORE_MARKERS = (
    ".w2c/",
    ".github/instructions/work-to-chores.instructions.md",
    ".github/instructions/do-chores.instructions.md",
)
TRACK_GITIGNORE_MARKERS = (".w2c/runtime/",)
GITIGNORE_COMMENT = "# w2c (local planner unless track = true)"
UNTRACK_INDEX_PATHS = [
    ".w2c",
    ".github/instructions/work-to-chores.instructions.md",
    ".github/instructions/do-chores.instructions.md",
]


class LocalError(Exception):
    """User-facing local-config error."""


def global_config_path() -> Path:
    override = os.environ.get("W2C_CONFIG")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / ".w2c" / "config.toml"


def data_home() -> Path:
    override = os.environ.get("W2C_DATA_HOME")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "w2c"

def repo_config_path(root: Path) -> Path:
    return root / ".w2c" / "config.toml"


def parse_toml(text: str) -> dict:
    if tomllib is None:
        raise LocalError("Python 3.11+ is required to read W2C TOML config")
    return tomllib.loads(text) if text.strip() else {}


def load_global_config() -> dict:
    path = global_config_path()
    if not path.is_file():
        return {"projects": []}
    data = parse_toml(path.read_text(encoding="utf-8"))
    projects = data.get("projects") or []
    if not isinstance(projects, list):
        projects = []
    return {"projects": [str(p) for p in projects]}


def dump_global_config(data: dict) -> str:
    lines = ["# W2C global config", "projects = ["]
    for project in data.get("projects") or []:
        escaped = str(project).replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))
        lines.append(f"  {chr(34)}{escaped}{chr(34)},")
    lines.append("]")
    lines.append("")
    return chr(10).join(lines)


def save_global_config(data: dict) -> None:
    path = global_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(dump_global_config(data), encoding="utf-8")
    tmp.replace(path)


def register_project(root: Path) -> bool:
    resolved = str(root.resolve())
    data = load_global_config()
    projects = list(data.get("projects") or [])
    if resolved in projects:
        return False
    projects.append(resolved)
    save_global_config({"projects": projects})
    return True


def unregister_project(root: Path) -> bool:
    resolved = str(root.resolve())
    data = load_global_config()
    projects = list(data.get("projects") or [])
    if resolved not in projects:
        return False
    save_global_config({"projects": [p for p in projects if p != resolved]})
    return True

def load_repo_config(root: Path) -> dict:
    path = repo_config_path(root)
    if not path.is_file():
        return {"track": False, "worktree_ledger": "symlink"}
    data = parse_toml(path.read_text(encoding="utf-8"))
    ledger = str(data.get("worktree_ledger") or "symlink")
    if ledger not in {"symlink", "copy"}:
        ledger = "symlink"
    return {"track": bool(data.get("track", False)), "worktree_ledger": ledger}


def dump_repo_config(track: bool, worktree_ledger: str = "symlink") -> str:
    if worktree_ledger not in {"symlink", "copy"}:
        worktree_ledger = "symlink"
    flag = "true" if track else "false"
    q = chr(34)
    return (
        "# W2C project config (gitignored unless track = true)" + chr(10)
        + "track = " + flag + chr(10)
        + "worktree_ledger = " + q + worktree_ledger + q + chr(10)
    )



def write_repo_config(
    root: Path,
    *,
    track: bool | None = None,
    worktree_ledger: str | None = None,
) -> None:
    current = load_repo_config(root)
    if track is None:
        track = bool(current.get("track"))
    if worktree_ledger is None:
        worktree_ledger = str(current.get("worktree_ledger") or "symlink")
    path = repo_config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(dump_repo_config(bool(track), str(worktree_ledger)), encoding="utf-8")
    tmp.replace(path)


def is_track_enabled(root: Path) -> bool:
    return bool(load_repo_config(root).get("track"))


def gitignore_markers(track: bool) -> list[str]:
    return list(TRACK_GITIGNORE_MARKERS if track else DEFAULT_GITIGNORE_MARKERS)


def ensure_gitignore(root: Path, *, track: bool) -> list[str]:
    gi = root / ".gitignore"
    raw = gi.read_text(encoding="utf-8") if gi.is_file() else ""
    lines = raw.splitlines()
    if not track:
        lines = [ln for ln in lines if ln not in LEGACY_GITIGNORE_MARKERS]
    wanted = gitignore_markers(track)
    existing = set(lines)
    missing = [m for m in wanted if m not in existing]
    if not missing and gi.is_file() and raw.splitlines() == lines:
        return []
    if missing:
        if lines and lines[-1] != "":
            lines.append("")
        if GITIGNORE_COMMENT not in lines:
            lines.append(GITIGNORE_COMMENT)
        lines.extend(missing)
    body = chr(10).join(lines).rstrip() + chr(10)
    gi.parent.mkdir(parents=True, exist_ok=True)
    tmp = gi.with_suffix(gi.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(gi)
    return missing

def repo_fingerprint(root: Path) -> str:
    resolved = str(root.resolve())
    digest = hashlib.sha256(resolved.encode()).hexdigest()[:12]
    return f"{root.resolve().name}-{digest}"


def backup_dir_for(root: Path) -> Path:
    return data_home() / "backups" / repo_fingerprint(root)


def _copy_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, symlinks=True)


def backup_w2c_assets(root: Path) -> Path:
    dest = backup_dir_for(root)
    dest.mkdir(parents=True, exist_ok=True)
    wdir = root / ".w2c"
    if wdir.exists():
        _copy_tree(wdir, dest / ".w2c")
    for rel in COPILOT_INSTRUCTION_RELPATHS:
        src = root / rel
        if src.is_file():
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    (dest / "ROOT").write_text(str(root.resolve()) + chr(10), encoding="utf-8")
    return dest


def git_ls_tracked_w2c(root: Path) -> list[str]:
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--",
                ".w2c",
                ".github/instructions/work-to-chores.instructions.md",
                ".github/instructions/do-chores.instructions.md",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    if proc.returncode != 0:
        return []
    skip_prefixes = (".w2c/runtime/", ".w2c/scripts/", ".w2c/templates/")
    return [
        ln
        for ln in proc.stdout.splitlines()
        if ln and not ln.startswith(skip_prefixes)
    ]


def git_rm_cached(root: Path, paths: list[str]) -> None:
    subprocess.run(
        ["git", "-C", str(root), "rm", "-r", "--cached", "--ignore-unmatch", "--", *paths],
        check=True,
        capture_output=True,
        text=True,
    )


def git_restore_path(root: Path, rel: str) -> bool:
    dest = root / rel
    if dest.exists():
        return False
    for rev in ("ORIG_HEAD", "HEAD^", "HEAD"):
        proc = subprocess.run(
            ["git", "-C", str(root), "checkout", "-q", rev, "--", rel],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and dest.exists():
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "rm",
                    "-r",
                    "--cached",
                    "--ignore-unmatch",
                    "--",
                    rel,
                ],
                capture_output=True,
                text=True,
            )
            return True
    return False

def migrate_untrack(root: Path) -> Path:
    backup = backup_w2c_assets(root)
    write_repo_config(root, track=False)
    ensure_gitignore(root, track=False)
    tracked = git_ls_tracked_w2c(root)
    if tracked:
        git_rm_cached(root, UNTRACK_INDEX_PATHS)
    return backup


def migrate_adopt(root: Path) -> list[str]:
    backup = backup_dir_for(root)
    restored: list[str] = []
    wdir = root / ".w2c"
    if not (wdir / "STATE.md").is_file():
        src = backup / ".w2c"
        if src.is_dir():
            _copy_tree(src, wdir)
            restored.append(".w2c/")
        elif git_restore_path(root, ".w2c"):
            restored.append(".w2c/")
    for rel in COPILOT_INSTRUCTION_RELPATHS:
        dest = root / rel
        if dest.is_file():
            continue
        src = backup / rel
        if src.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            restored.append(str(rel))
        elif git_restore_path(root, str(rel)):
            restored.append(str(rel))
    write_repo_config(root, track=False)
    ensure_gitignore(root, track=False)
    register_project(root)
    return restored

