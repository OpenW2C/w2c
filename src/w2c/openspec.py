"""Subprocess adapter for the OpenSpec command-line program.

Calls use an argument list, never a shell. JSON is parsed from stdout.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Floor checked against the installed OpenSpec 1.14.x contract
# (status/instructions/archive --json, strict validate, x- metadata keys).
MIN_OPENSPEC_VERSION = (1, 14, 3)
RULE_MARKER = "W2C-OPENSPEC-RULES"
NEED_INSTALL = "NEED_OPENSPEC_INSTALL"
NEED_INIT = "NEED_OPENSPEC_INIT"

CONFIG_RULES_SNIPPET = (
    "rules:\n"
    "  tasks:\n"
    '    - "W2C-OPENSPEC-RULES: each ## N. heading is one slice. '
    "Each task checkbox is `- [ ] N.M` and the next indented line is "
    '`- Verify: <how to prove it>`."\n'
)


class OpenSpecError(Exception):
    """The openspec program is missing or returned an error."""


@dataclass
class OpenSpecResult:
    ok: bool
    code: int
    data: object
    stdout: str
    stderr: str


def executable() -> str | None:
    return shutil.which("openspec")


def parse_version(text: str) -> tuple[int, int, int]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        raise OpenSpecError(f"could not read an OpenSpec version from {text!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def version_ok(text: str) -> bool:
    try:
        return parse_version(text) >= MIN_OPENSPEC_VERSION
    except OpenSpecError:
        return False


def _parse_json(stdout: str) -> object:
    start = None
    for index, char in enumerate(stdout):
        if char in "{[":
            start = index
            break
    if start is None:
        return None
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError:
        return None


def run(root: Path, args: list[str], *, timeout: float = 60) -> OpenSpecResult:
    exe = executable()
    if not exe:
        raise OpenSpecError("openspec is not on PATH")
    try:
        proc = subprocess.run(
            [exe, *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OpenSpecError("openspec timed out") from exc
    except FileNotFoundError as exc:
        raise OpenSpecError("openspec is not on PATH") from exc
    data = _parse_json(proc.stdout) if "--json" in args else None
    return OpenSpecResult(
        ok=proc.returncode == 0,
        code=proc.returncode,
        data=data,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def version_text() -> str:
    exe = executable()
    if not exe:
        raise OpenSpecError("openspec is not on PATH")
    proc = subprocess.run(
        [exe, "--version"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "openspec --version failed").strip()
        raise OpenSpecError(detail)
    return (proc.stdout or "").strip()


def _fail(result: OpenSpecResult, what: str) -> None:
    detail = (result.stderr or result.stdout or "").strip()
    raise OpenSpecError(f"{what} failed ({result.code}): {detail}")


def new_change(root: Path, name: str, goal: str | None = None) -> dict:
    args = ["new", "change", name, "--json"]
    if goal:
        args.extend(["--goal", goal])
    result = run(root, args)
    if not result.ok or not isinstance(result.data, dict):
        _fail(result, "openspec new change")
    return result.data  # type: ignore[return-value]


def status(root: Path, change: str) -> dict:
    result = run(root, ["status", "--change", change, "--json"])
    if not result.ok or not isinstance(result.data, dict):
        _fail(result, "openspec status")
    return result.data  # type: ignore[return-value]


def validate(root: Path, change: str, *, strict: bool = True) -> OpenSpecResult:
    args = ["validate", change, "--type", "change", "--json", "--no-interactive"]
    if strict:
        args.append("--strict")
    return run(root, args)


def instructions(root: Path, artifact: str, change: str) -> dict:
    result = run(root, ["instructions", artifact, "--change", change, "--json"])
    if not result.ok or not isinstance(result.data, dict):
        _fail(result, f"openspec instructions {artifact}")
    return result.data  # type: ignore[return-value]


def apply_info(root: Path, change: str) -> dict:
    return instructions(root, "apply", change)


def archive(root: Path, change: str) -> dict:
    result = run(root, ["archive", change, "-y", "--json"])
    if not result.ok or not isinstance(result.data, dict):
        _fail(result, "openspec archive")
    return result.data  # type: ignore[return-value]


def link_milestone(metadata_path: Path, mid: str) -> None:
    text = metadata_path.read_text(encoding="utf-8")
    line = f"x-w2c-milestone: {mid}"
    if re.search(r"(?m)^x-w2c-milestone\s*:", text):
        text = re.sub(r"(?m)^x-w2c-milestone\s*:.*$", line, text, count=1)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    metadata_path.write_text(text, encoding="utf-8")


def _first_active_change(root: Path) -> str | None:
    changes = root / "openspec" / "changes"
    if not changes.is_dir():
        return None
    names = sorted(
        path.name
        for path in changes.iterdir()
        if path.is_dir() and path.name != "archive" and (path / ".openspec.yaml").is_file()
    )
    return names[0] if names else None


def _blob_has_marker(blob: object) -> bool:
    try:
        text = json.dumps(blob)
    except TypeError:
        text = str(blob)
    return RULE_MARKER in text


def check(root: Path) -> dict:
    """Report install state. Never raises. ``needs`` lists NEED_* tokens."""
    payload: dict = {
        "cli_found": False,
        "version": None,
        "version_ok": False,
        "min_version": ".".join(str(part) for part in MIN_OPENSPEC_VERSION),
        "root_present": (root / "openspec").is_dir(),
        "rules_present": False,
        "rules_checked_via": None,
        "needs": [],
    }
    if not executable():
        payload["needs"].append(NEED_INSTALL)
        return payload
    payload["cli_found"] = True
    try:
        text = version_text()
    except OpenSpecError as exc:
        payload["needs"].append(NEED_INSTALL)
        payload["version_error"] = str(exc)
        return payload
    payload["version"] = text
    payload["version_ok"] = version_ok(text)
    if not payload["version_ok"]:
        payload["needs"].append(NEED_INSTALL)
    if not payload["root_present"]:
        payload["needs"].append(NEED_INIT)
        return payload
    if not payload["version_ok"]:
        return payload
    change = _first_active_change(root)
    if change:
        try:
            data = instructions(root, "tasks", change)
        except OpenSpecError:
            data = None
        if data is not None and _blob_has_marker(data):
            payload["rules_present"] = True
            payload["rules_checked_via"] = "instructions"
            return payload
    config = root / "openspec" / "config.yaml"
    if not config.is_file():
        config = root / "openspec" / "config.yml"
    if config.is_file() and RULE_MARKER in config.read_text(encoding="utf-8"):
        payload["rules_present"] = True
        payload["rules_checked_via"] = "config-text"
    elif change:
        payload["rules_checked_via"] = "instructions"
    return payload
