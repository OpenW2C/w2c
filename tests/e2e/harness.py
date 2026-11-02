"""Framework for the full-cycle suites: a dummy project, staged runs, stored outputs."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[2]
EXPECTED_DIR = Path(__file__).resolve().parent / "expected"

DATE_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
)
SHA_RE = re.compile(r"\b(?:[0-9a-f]{40}|(?=[0-9]*[a-f])[0-9a-f]{7,12})\b")


def package_version() -> str:
    text = (REPO / "src" / "w2c" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise RuntimeError("cannot read src/w2c/__init__.py version")
    return match.group(1)


@dataclass
class Project:
    root: Path
    remote: Path
    home: Path
    env: dict[str, str]
    tmp: Path | None = None
    suite: str = "legacy"
    state: dict[str, str] = field(default_factory=dict)

    def _cwd(self, cwd: Path | None) -> Path:
        return Path(cwd) if cwd is not None else self.root

    def w2c(
        self, *args: str, cwd: Path | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        exe = self.home / ".local" / "bin" / "w2c"
        proc = subprocess.run(
            [str(exe), *args],
            cwd=str(self._cwd(cwd)),
            env=self.env,
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise AssertionError(
                f"w2c {' '.join(args)} exited {proc.returncode}\n{proc.stdout}{proc.stderr}"
            )
        return proc

    def git(
        self, *args: str, cwd: Path | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            ["git", "-C", str(self._cwd(cwd)), *args],
            env=self.env,
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise AssertionError(
                f"git {' '.join(args)} exited {proc.returncode}\n{proc.stdout}{proc.stderr}"
            )
        return proc

    def run(
        self, argv: list[str], cwd: Path | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            argv, cwd=str(self._cwd(cwd)), env=self.env, capture_output=True, text=True
        )
        if check and proc.returncode != 0:
            raise AssertionError(
                f"{' '.join(argv)} exited {proc.returncode}\n{proc.stdout}{proc.stderr}"
            )
        return proc

    def write(self, rel: str | Path, text: str, cwd: Path | None = None) -> Path:
        path = Path(rel)
        if not path.is_absolute():
            path = self._cwd(cwd) / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        return path

    def read(self, rel: str | Path, cwd: Path | None = None) -> str:
        path = Path(rel)
        if not path.is_absolute():
            path = self._cwd(cwd) / path
        return path.read_text(encoding="utf-8")

    def expect_tokens(self, proc: subprocess.CompletedProcess[str] | str, *tokens: str) -> None:
        if isinstance(proc, str):
            text = proc
        else:
            text = (proc.stdout or "") + (proc.stderr or "")
        missing = [token for token in tokens if token not in text]
        if missing:
            raise AssertionError(f"missing tokens {missing} in output:\n{text}")

    def expect_files(self, *rels: str, cwd: Path | None = None) -> None:
        missing = [rel for rel in rels if not (self._cwd(cwd) / rel).exists()]
        if missing:
            raise AssertionError(f"missing files: {missing}")

    def mask(self, text: str) -> str:
        bases: set[str] = set()
        base = self.tmp if self.tmp is not None else self.root.parent
        bases.add(str(base))
        bases.add(str(Path(base).resolve()))
        # Longest first so a nested path is not half replaced.
        for base in sorted(bases, key=len, reverse=True):
            text = text.replace(base, "<ROOT>")
        text = text.replace(package_version(), "<VERSION>")
        text = DATE_RE.sub("<DATE>", text)
        text = SHA_RE.sub("<SHA>", text)
        return text

    def expect_matches(self, rel_output_name: str, text: str) -> None:
        masked = self.mask(text)
        if not masked.endswith("\n"):
            masked += "\n"
        path = EXPECTED_DIR / self.suite / rel_output_name
        if os.environ.get("W2C_E2E_UPDATE") == "1":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(masked, encoding="utf-8")
            return
        if not path.is_file():
            raise AssertionError(
                f"no stored output {path}; run with W2C_E2E_UPDATE=1 to create it"
            )
        stored = path.read_text(encoding="utf-8")
        if stored != masked:
            raise AssertionError(
                f"output differs from {path}\n--- stored\n{stored}\n--- actual\n{masked}"
            )


@dataclass
class Stage:
    id: str
    title: str
    run: Callable[[Project], None]


def _git_env(home: Path, base: dict[str, str]) -> dict[str, str]:
    env = dict(base)
    bin_dir = str(home / ".local" / "bin")
    env["PATH"] = bin_dir + os.pathsep + base.get("PATH", "")
    env["HOME"] = str(home)
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_CACHE_HOME"] = str(home / ".cache")
    env["W2C_DATA_HOME"] = str(home / ".local" / "share" / "w2c")
    env["W2C_BIN_DIR"] = bin_dir
    env["W2C_CONFIG_DIR"] = str(home / ".config" / ".w2c")
    env["W2C_CONFIG"] = str(home / ".config" / ".w2c" / "config.toml")
    env["GIT_CONFIG_GLOBAL"] = str(home / ".gitconfig")
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["OPENSPEC_TELEMETRY"] = "0"
    env["DO_NOT_TRACK"] = "1"
    env["NO_COLOR"] = "1"
    env["CI"] = "1"
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(key, None)
    return env


APP_CALC = '''"""Tiny calculator used as the dummy product."""


def add(a, b):
    return a + b
'''

APP_TEST = '''import unittest

from app.calc import add


class CalcTests(unittest.TestCase):
    def test_add(self) -> None:
        self.assertEqual(add(1, 2), 3)


if __name__ == "__main__":
    unittest.main()
'''


def make_project(tmp: Path, suite: str = "legacy") -> Project:
    tmp = Path(tmp)
    home = tmp / "home"
    root = tmp / "proj"
    remote = tmp / "remote.git"
    home.mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    env = _git_env(home, dict(os.environ))
    project = Project(root=root, remote=remote, home=home, env=env, tmp=tmp, suite=suite)
    (home / ".gitconfig").write_text(
        "[user]\n\tname = W2C E2E\n\temail = e2e@example.com\n"
        "[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n",
        encoding="utf-8",
    )
    project.write("app/__init__.py", "")
    project.write("tests/__init__.py", "")
    project.write("app/calc.py", APP_CALC)
    project.write("tests/test_calc.py", APP_TEST)
    project.write("README.md", "# Dummy calculator\n")
    project.git("init", "-q", "-b", "main")
    project.git("add", "-A")
    project.git("commit", "-q", "-m", "initial calculator")
    project.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], cwd=tmp)
    project.git("remote", "add", "origin", str(remote))
    project.git("push", "-q", "-u", "origin", "main")
    installer = subprocess.run(
        ["bash", str(REPO / "install.sh"), "--force", "--skip-skills"],
        cwd=str(tmp),
        env=env,
        capture_output=True,
        text=True,
    )
    if installer.returncode != 0:
        raise AssertionError(f"install.sh failed\n{installer.stdout}{installer.stderr}")
    return project


def run_suite(
    stages: list[Stage], project_factory: Callable[[], Project]
) -> list[tuple[Stage, bool, str]]:
    results: list[tuple[Stage, bool, str]] = []
    failed = False
    project: Project | None = None
    for stage in stages:
        if failed:
            results.append((stage, False, "not run"))
            continue
        try:
            if project is None:
                project = project_factory()
            stage.run(project)
        except Exception as exc:  # noqa: BLE001 - every failure is a stage verdict
            failed = True
            message = " ".join(str(exc).split()) or exc.__class__.__name__
            results.append((stage, False, message[:600]))
        else:
            results.append((stage, True, ""))
    return results


def write_report(results: list[tuple[Stage, bool, str]], path: Path) -> None:
    lines: list[str] = []
    for stage, ok, error in results:
        if ok:
            lines.append(f"- [x] {stage.id} {stage.title}")
        else:
            lines.append(f"- [ ] {stage.id} {stage.title} — {error}")
    verdict = "E2E: PASS" if results and all(ok for _s, ok, _e in results) else "E2E: FAIL"
    lines.append(verdict)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "Project",
    "Stage",
    "make_project",
    "run_suite",
    "write_report",
    "package_version",
    "EXPECTED_DIR",
]
