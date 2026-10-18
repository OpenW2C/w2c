"""Classify working-tree dirt before a milestone branch is created.

Read-only. Exit status stays 0 after a successful scan; callers read ``status``.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

SOURCE_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyi",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".swift",
        ".m",
        ".mm",
        ".dart",
        ".rb",
        ".php",
        ".cs",
        ".cpp",
        ".c",
        ".h",
        ".hpp",
        ".cc",
        ".scala",
        ".ex",
        ".exs",
        ".vue",
        ".svelte",
    }
)

CONFIG_BASENAMES = frozenset(
    {
        "pyproject.toml",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "cargo.toml",
        "cargo.lock",
        "go.mod",
        "go.sum",
        "pubspec.yaml",
        "podfile",
        "gemfile",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle",
        "settings.gradle.kts",
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        "procfile",
        "appsettings.json",
        "application.yml",
        "application.yaml",
        "wrangler.toml",
        "fly.toml",
        "next.config.js",
        "next.config.ts",
        "nuxt.config.ts",
        "vite.config.ts",
        "tsconfig.json",
    }
)

TRACKED_NOTE = "Tracked edits will come along as uncommitted changes on the new branch."


class BaseDirtError(Exception):
    """git status could not be read."""


@dataclass(frozen=True)
class DirtReport:
    status: str
    critical: list[str]
    other: list[str]
    tracked: list[str]
    note: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "critical": self.critical,
            "other": self.other,
            "tracked": self.tracked,
            "note": self.note,
        }


def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def is_excluded(path: str, extra_prefixes: tuple[str, ...] | list[str] = ()) -> bool:
    """Ledger paths and an active change folder are expected plan dirt."""
    norm = _norm(path)
    if norm == ".w2c" or norm.startswith(".w2c/"):
        return True
    for prefix in extra_prefixes:
        cleaned = _norm(prefix).rstrip("/")
        if cleaned and (norm == cleaned or norm.startswith(cleaned + "/")):
            return True
    return False


def is_critical_path(path: str) -> bool:
    """Application source or service config. Ledger paths are never critical."""
    if is_excluded(path):
        return False
    name = _norm(path).rsplit("/", 1)[-1]
    lower = name.lower()
    if lower == ".env" or lower.startswith(".env."):
        return True
    if lower in CONFIG_BASENAMES:
        return True
    dot = lower.rfind(".")
    if dot >= 0 and lower[dot:] in SOURCE_EXTENSIONS:
        return True
    return False


def unquote_git_path(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            return text[1:-1]
        if isinstance(loaded, str):
            return loaded
    return text


def parse_porcelain_line(line: str) -> tuple[str, str] | None:
    """Return (XY, path) for one porcelain v1 line. Rename lines keep the destination."""
    if line.endswith("\r"):
        line = line[:-1]
    if len(line) < 4:
        return None
    xy = line[:2]
    raw = line[3:]
    if " -> " in raw:
        raw = raw.split(" -> ", 1)[1]
    path = unquote_git_path(raw)
    if not path:
        return None
    return xy, path


def classify_entries(
    entries: list[tuple[str, str]],
    extra_prefixes: tuple[str, ...] | list[str] = (),
) -> DirtReport:
    critical: list[str] = []
    other: list[str] = []
    tracked: list[str] = []
    seen_critical: set[str] = set()
    seen_other: set[str] = set()
    seen_tracked: set[str] = set()
    for xy, path in entries:
        if is_excluded(path, extra_prefixes):
            continue
        if is_critical_path(path):
            if path not in seen_critical:
                seen_critical.add(path)
                critical.append(path)
        elif path not in seen_other:
            seen_other.add(path)
            other.append(path)
        if xy not in ("??", "!!") and path not in seen_tracked:
            seen_tracked.add(path)
            tracked.append(path)
    if critical:
        status = "critical"
    elif other:
        status = "noncritical"
    else:
        status = "clean"
    note = TRACKED_NOTE if tracked else ""
    return DirtReport(status=status, critical=critical, other=other, tracked=tracked, note=note)


def git_porcelain(root: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain=v1", "-u"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise BaseDirtError("git is not on PATH") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "git status failed").strip()
        raise BaseDirtError(err)
    return proc.stdout


def scan_base_dirt(
    root: str,
    extra_prefixes: tuple[str, ...] | list[str] = (),
) -> DirtReport:
    entries: list[tuple[str, str]] = []
    for line in git_porcelain(root).splitlines():
        parsed = parse_porcelain_line(line)
        if parsed is not None:
            entries.append(parsed)
    return classify_entries(entries, extra_prefixes)


def cmd_base_dirt(
    root: str,
    extra_prefixes: tuple[str, ...] | list[str] = (),
) -> int:
    report = scan_base_dirt(root, extra_prefixes)
    print(json.dumps(report.to_dict(), indent=2))
    return 0
