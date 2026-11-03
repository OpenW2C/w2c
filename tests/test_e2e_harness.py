#!/usr/bin/env python3
"""Tests for the full-cycle harness itself (not for the stages it runs)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.e2e import harness  # noqa: E402


class HarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="w2c-e2e-harness-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)], check=False))

    def test_report_lists_each_stage_and_verdict(self) -> None:
        def ok(_project: harness.Project) -> None:
            return None

        def boom(_project: harness.Project) -> None:
            raise AssertionError("token missing")

        called: list[str] = []

        def later(_project: harness.Project) -> None:
            called.append("S3")

        stages = [
            harness.Stage("S1", "first", ok),
            harness.Stage("S2", "second", boom),
            harness.Stage("S3", "third", later),
        ]
        results = harness.run_suite(stages, lambda: self._project())
        self.assertEqual([(r[0].id, r[1]) for r in results], [("S1", True), ("S2", False), ("S3", False)])
        report = self.tmp / "report.md"
        harness.write_report(results, report)
        lines = report.read_text(encoding="utf-8").splitlines()
        self.assertIn("- [x] S1 first", lines)
        self.assertTrue(any(l.startswith("- [ ] S2 second — ") and "token missing" in l for l in lines))
        self.assertEqual(called, [])
        self.assertIn("- [ ] S3 third — not run", lines)
        self.assertEqual(lines[-1], "E2E: FAIL")

    def test_report_passes_when_every_stage_passes(self) -> None:
        stages = [harness.Stage("S1", "first", lambda _p: None)]
        results = harness.run_suite(stages, lambda: self._project())
        report = self.tmp / "report.md"
        harness.write_report(results, report)
        self.assertEqual(report.read_text(encoding="utf-8").splitlines()[-1], "E2E: PASS")

    def test_each_suite_gets_its_own_project_and_a_failure_does_not_stop_the_next(self) -> None:
        made: list[tuple[Path, str]] = []
        seen: list[tuple[str, str]] = []

        def factory(path: Path, suite: str = "legacy") -> harness.Project:
            made.append((path, suite))
            path.mkdir(parents=True, exist_ok=True)
            return harness.Project(
                root=path, remote=path / "r.git", home=path / "h", env={}, tmp=path, suite=suite
            )

        def fail(_p: harness.Project) -> None:
            raise AssertionError("legacy broke")

        def record(p: harness.Project) -> None:
            seen.append((p.suite, str(p.root)))

        results = harness.run_suites(
            [
                ("legacy", [harness.Stage("L01", "one", fail), harness.Stage("L02", "two", record)]),
                ("cloud", [harness.Stage("C01", "one", record)]),
            ],
            self.tmp,
            factory,
        )
        self.assertEqual(made, [(self.tmp / "legacy", "legacy"), (self.tmp / "cloud", "cloud")])
        self.assertEqual(seen, [("cloud", str(self.tmp / "cloud"))])
        self.assertEqual(
            [(r[0].id, r[1]) for r in results], [("L01", False), ("L02", False), ("C01", True)]
        )
        old = harness.EXPECTED_DIR
        harness.EXPECTED_DIR = self.tmp / "expected"
        self.addCleanup(lambda: setattr(harness, "EXPECTED_DIR", old))
        os.environ["W2C_E2E_UPDATE"] = "1"
        self.addCleanup(lambda: os.environ.pop("W2C_E2E_UPDATE", None))
        for suite in ("legacy", "cloud"):
            proj = factory(self.tmp / suite, suite)
            proj.expect_matches("x.txt", suite)
        self.assertEqual((self.tmp / "expected" / "legacy" / "x.txt").read_text().strip(), "legacy")
        self.assertEqual((self.tmp / "expected" / "cloud" / "x.txt").read_text().strip(), "cloud")

    def test_missing_openspec_fails(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "w2c-e2e.py"), "--suite", "legacy"],
            env={"PATH": ""},
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("openspec not found", proc.stdout + proc.stderr)

    def test_expected_output_masks_paths_and_dates(self) -> None:
        expected = self.tmp / "expected"
        (expected / "legacy").mkdir(parents=True)
        old = harness.EXPECTED_DIR
        harness.EXPECTED_DIR = expected
        self.addCleanup(lambda: setattr(harness, "EXPECTED_DIR", old))
        project = self._project()
        sha = "0123456789abcdef0123456789abcdef01234567"
        text = (
            f"root {project.root}/app resolved {project.tmp.resolve()}\n"
            f"on 2026-11-02 and 2026-11-02T10:11:12Z at {sha[:4]}abc {sha}\n"
            f"archive 2026-11-02-add-calc w2c {harness.package_version()}\n"
        )
        (expected / "legacy" / "out.txt").write_text(
            "root <ROOT>/proj/app resolved <ROOT>\n"
            "on <DATE> and <DATE> at <SHA> <SHA>\n"
            "archive <DATE>-add-calc w2c <VERSION>\n",
            encoding="utf-8",
        )
        project.expect_matches("out.txt", text)
        with self.assertRaises(AssertionError):
            project.expect_matches("out.txt", text + "extra\n")
        os.environ["W2C_E2E_UPDATE"] = "1"
        self.addCleanup(lambda: os.environ.pop("W2C_E2E_UPDATE", None))
        project.expect_matches("fresh.txt", text)
        stored = (expected / "legacy" / "fresh.txt").read_text(encoding="utf-8")
        self.assertIn("<ROOT>/proj/app", stored)
        self.assertNotIn(str(self.tmp), stored)
        self.assertNotIn("2026-11-02", stored)

    def _project(self) -> "harness.Project":
        root = self.tmp / "proj"
        root.mkdir(exist_ok=True)
        return harness.Project(
            root=root,
            remote=self.tmp / "remote.git",
            home=self.tmp / "home",
            env=dict(os.environ),
            tmp=self.tmp,
        )


if __name__ == "__main__":
    unittest.main()
