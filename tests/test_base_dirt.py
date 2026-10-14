#!/usr/bin/env python3
"""Classifier tests for w2c base-dirt."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
import sys

sys.path.insert(0, str(SRC))

from w2c.base_dirt import (  # noqa: E402
    TRACKED_NOTE,
    classify_entries,
    is_critical_path,
    is_excluded,
    parse_porcelain_line,
    scan_base_dirt,
)


def _git(repo: Path, *args: str) -> None:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "w2c-test"
    env["GIT_AUTHOR_EMAIL"] = "w2c-test@example.com"
    env["GIT_COMMITTER_NAME"] = "w2c-test"
    env["GIT_COMMITTER_EMAIL"] = "w2c-test@example.com"
    subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


class ClassifyTests(unittest.TestCase):
    def test_source_and_config_are_critical(self) -> None:
        self.assertTrue(is_critical_path("src/app.py"))
        self.assertTrue(is_critical_path("pkg/main.go"))
        self.assertTrue(is_critical_path("package.json"))
        self.assertTrue(is_critical_path("services/api/Dockerfile"))
        self.assertTrue(is_critical_path("config/.env"))
        self.assertTrue(is_critical_path(".env.local"))
        self.assertTrue(is_critical_path("application.yml"))

    def test_notes_are_not_critical_and_ledger_is_excluded(self) -> None:
        self.assertFalse(is_critical_path("NOTES.md"))
        self.assertFalse(is_critical_path("README.md"))
        self.assertTrue(is_excluded(".w2c/config.toml"))
        self.assertFalse(is_critical_path(".w2c/config.toml"))

    def test_quoted_and_rename_porcelain(self) -> None:
        self.assertEqual(parse_porcelain_line('?? "My Notes.md"'), ("??", "My Notes.md"))
        self.assertEqual(
            parse_porcelain_line("R  old.py -> src/new.py"),
            ("R ", "src/new.py"),
        )

    def test_status_buckets(self) -> None:
        report = classify_entries(
            [
                ("??", "src/app.py"),
                ("??", "package.json"),
                ("??", "NOTES.md"),
                ("??", ".w2c/STATE.md"),
                (" M", "README.md"),
            ]
        )
        self.assertEqual(report.status, "critical")
        self.assertEqual(report.critical, ["src/app.py", "package.json"])
        self.assertEqual(report.other, ["NOTES.md", "README.md"])
        self.assertEqual(report.tracked, ["README.md"])
        self.assertEqual(report.note, TRACKED_NOTE)

    def test_tracked_source_edit_is_critical(self) -> None:
        report = classify_entries([(" M", "src/app.py")])
        self.assertEqual(report.status, "critical")
        self.assertEqual(report.tracked, ["src/app.py"])

    def test_tracked_readme_is_noncritical(self) -> None:
        report = classify_entries([(" M", "README.md")])
        self.assertEqual(report.status, "noncritical")
        self.assertEqual(report.critical, [])
        self.assertEqual(report.tracked, ["README.md"])


class ScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="w2c-base-dirt-"))
        _git(self.tmp, "init", "-b", "main")
        (self.tmp / "src").mkdir()
        (self.tmp / "src" / "app.py").write_text("x\n", encoding="utf-8")
        (self.tmp / "README.md").write_text("hi\n", encoding="utf-8")
        (self.tmp / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        _git(self.tmp, "add", ".")
        _git(self.tmp, "commit", "-m", "init")

    def test_clean_tree(self) -> None:
        report = scan_base_dirt(str(self.tmp))
        self.assertEqual(report.status, "clean")
        self.assertEqual(report.critical, [])
        self.assertEqual(report.other, [])

    def test_scan_ignores_gitignored_and_ledger(self) -> None:
        (self.tmp / "src" / "app.py").write_text("y\n", encoding="utf-8")
        (self.tmp / "README.md").write_text("bye\n", encoding="utf-8")
        (self.tmp / "NOTES.md").write_text("n\n", encoding="utf-8")
        (self.tmp / "package.json").write_text("{}\n", encoding="utf-8")
        (self.tmp / "ignored.txt").write_text("secret\n", encoding="utf-8")
        (self.tmp / ".w2c").mkdir()
        (self.tmp / ".w2c" / "STATE.md").write_text("ledger\n", encoding="utf-8")
        report = scan_base_dirt(str(self.tmp))
        self.assertEqual(report.status, "critical")
        self.assertIn("src/app.py", report.critical)
        self.assertIn("package.json", report.critical)
        self.assertIn("NOTES.md", report.other)
        self.assertIn("README.md", report.other)
        joined = report.critical + report.other
        self.assertNotIn("ignored.txt", joined)
        self.assertFalse(any(path.startswith(".w2c/") for path in joined))
        self.assertIn("src/app.py", report.tracked)
        self.assertIn("README.md", report.tracked)
        self.assertNotIn("NOTES.md", report.tracked)

    def test_cli_prints_json(self) -> None:
        (self.tmp / "NOTES.md").write_text("n\n", encoding="utf-8")
        from w2c.cli import main

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--root", str(self.tmp), "base-dirt"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["status"], "noncritical")
        self.assertEqual(payload["other"], ["NOTES.md"])
        self.assertEqual(payload["critical"], [])


if __name__ == "__main__":
    unittest.main()
