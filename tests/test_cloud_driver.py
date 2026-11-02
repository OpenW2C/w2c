#!/usr/bin/env python3
"""The cloud step driver: the command line picks each next step, and `brief`."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-cloud-driver-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from w2c import cli as w2c  # noqa: E402
from w2c import local as w2c_local  # noqa: E402
from w2c.cloud import driver  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "fake_openspec.py"
ORIGINAL_PATH = os.environ.get("PATH", "")
SLICE = w2c_local.GIT_DELIVERY_SLICE
MILESTONE = w2c_local.GIT_DELIVERY_MILESTONE
NAME = "add-export"
BRANCH = "DEMO-1"

DESIGN = """# Design

## Delivery Plan

| Field | Value |
| --- | --- |
| Remote branch | DEMO-1 |

## Guardrails

- Keep the exporter small.

## Commit and PR Conventions

- Never add a Co-authored-by trailer.

## Decisions

| # | When | Scope | Decision | Choice | Rationale | Revisable? | Made By |
|---|------|-------|----------|--------|-----------|------------|---------|

## Manual Test Guide

none

## Amendments

none
"""

FIELDS = "".join(
    f"**{field}:** {field.lower()} one\n"
    for field in ("Goal", "Demo", "Must-Haves", "Threat Surface", "Proof Level",
                  "Integration Closure", "Verification", "Files Likely Touched")
)

TASKS = f"""# Tasks

## 1. Export

{FIELDS}
- [ ] 1.1 Write exporter
  - Verify: python3 -m unittest tests.test_export
- [ ] 1.2 Wire exporter
  - Verify: true

## 2. Docs

{FIELDS.replace(" one", " two")}
- [ ] 2.1 Document it
  - Verify: true
"""


def run_main(root: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = w2c.main(["--root", str(root), *argv])
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=root, check=True, capture_output=True,
    )


class DriverBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        bindir = Path(self._tmp.name) / "bin"
        bindir.mkdir()
        dest = bindir / "openspec"
        shutil.copy(FIXTURE, dest)
        dest.chmod(0o755)
        os.environ["PATH"] = str(bindir) + os.pathsep + ORIGINAL_PATH
        self.addCleanup(lambda: os.environ.__setitem__("PATH", ORIGINAL_PATH))
        saved = os.environ.get("W2C_EPHEMERAL")
        os.environ["W2C_EPHEMERAL"] = "0"
        self.addCleanup(
            lambda: os.environ.pop("W2C_EPHEMERAL", None) if saved is None
            else os.environ.__setitem__("W2C_EPHEMERAL", saved)
        )
        git(self.root, "init", "-b", BRANCH)
        (self.root / "README.md").write_text("x\n", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "init")

    @property
    def change(self) -> Path:
        return self.root / "openspec" / "changes" / NAME

    @property
    def state_path(self) -> Path:
        return self.root / driver.STEP_STATE

    def make(self, cadence: str = SLICE, status: str = "TODO", extra: str = "") -> Path:
        folder = self.change
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ".openspec.yaml").write_text(
            f"schema: spec-driven\nx-delivery-status: {status}\n"
            f"x-delivery-cadence: {cadence}\nx-delivery-order: 1\n{extra}",
            encoding="utf-8",
        )
        (folder / "design.md").write_text(DESIGN, encoding="utf-8")
        (folder / "tasks.md").write_text(TASKS, encoding="utf-8")
        return folder

    def report(self, name: str) -> None:
        path = self.change / ".delivery" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("done\n", encoding="utf-8")

    def step(self, change: str | None = None) -> dict:
        return driver.next_action(self.root, change)

    def action(self) -> str:
        return self.step()["action"]

    def rec(self, action: str, result: str) -> None:
        driver.record(self.root, action, result)

    def ok(self, *argv: str) -> str:
        code, out, err = run_main(self.root, *argv)
        self.assertEqual(code, 0, out + err)
        return out

    def perform(self, step: dict, answers: dict[str, str] | None = None) -> None:
        """Do what a step asks with the real commands, then record it."""
        action = step["action"]
        answers = answers or {}
        sid, tid = step["slice"], step["task"]
        if action in ("smoke", "isolate", "implement", "verify", "review"):
            self.rec(action, "pass")
        elif action == "write-report":
            self.report(f"{sid}-{tid}-SUMMARY.md")
            self.rec(action, "pass")
        elif action == "complete":
            self.ok("cloud", "complete", "--change", NAME, "--slice", sid, "--task", tid)
            self.rec(action, "pass")
        elif action == "slice-reports":
            self.report(f"{sid}-UAT.md")
            self.report(f"{sid}-SUMMARY.md")
            self.rec(action, "pass")
        elif action == "slice-complete":
            self.ok("cloud", "slice-complete", "--change", NAME, "--slice", sid)
            self.rec(action, "pass")
        elif action == "milestone-reports":
            self.report("VALIDATION.md")
            self.report("SUMMARY.md")
            self.rec(action, "pass")
        elif action.startswith("ask-"):
            answer = answers.get(action, "yes")
            if action == "ask-archive":
                if answer == "yes":
                    self.ok("cloud", "archive", NAME)
                elif answer == "no":
                    self.ok("cloud", "milestone-complete", NAME, "--archive-declined")
            self.rec(action, answer)
        else:
            raise AssertionError(f"cannot perform {step}")

    def drive_to(self, wanted: str, answers: dict[str, str] | None = None, limit: int = 80) -> dict:
        seen: list[str] = []
        for _ in range(limit):
            step = self.step()
            if step["action"] == wanted:
                return step
            if step["action"] in ("done", "stop"):
                raise AssertionError(f"reached {step} before {wanted}; seen {seen}")
            seen.append(step["action"])
            self.perform(step, answers)
        raise AssertionError(f"never reached {wanted}; seen {seen}")

    def sequence(self, answers: dict[str, str] | None = None, limit: int = 80) -> list[str]:
        seen: list[str] = []
        for _ in range(limit):
            step = self.step()
            seen.append(step["action"])
            if step["action"] in ("done", "stop"):
                return seen
            self.perform(step, answers)
        raise AssertionError(f"no end after {limit}: {seen}")


class RuleTests(DriverBase):
    def test_rule1_no_active_change_is_done(self) -> None:
        step = self.step()
        self.assertEqual(step["action"], "done")
        self.assertEqual(set(step), {"action", "change", "slice", "task", "files", "reason"})
        self.make(status="PAUSED")
        self.assertEqual(self.action(), "done")

    def test_rule2_amend_lock_stops(self) -> None:
        self.make(status="PAUSED", extra="x-delivery-amend-lock: D1\nx-delivery-amend-prior-status: "
                                          "INPROGRESS\nx-delivery-amend-decision: D1\n")
        step = self.step()
        self.assertEqual((step["action"], step["reason"], step["change"]), ("stop", "AMEND_LOCK", NAME))

    def test_rule3_smoke_first_failed_smoke_stops_new_task_resmokes(self) -> None:
        self.make()
        step = self.step()
        self.assertEqual((step["action"], step["change"], step["slice"], step["task"]),
                         ("smoke", NAME, "S01", "T01"))
        self.rec("smoke", "fail")
        step = self.step()
        self.assertEqual((step["action"], step["reason"]), ("stop", "smoke"))
        self.rec("smoke", "pass")
        self.assertEqual(self.action(), "implement")
        self.drive_to("complete")
        self.perform(self.step())
        step = self.step()
        self.assertEqual((step["action"], step["task"]), ("smoke", "T02"))

    def test_rule4_wrong_branch_isolates(self) -> None:
        self.make()
        git(self.root, "switch", "-q", "-c", "other")
        self.rec("smoke", "pass")
        self.assertEqual(self.action(), "isolate")
        git(self.root, "switch", "-q", BRANCH)
        self.assertEqual(self.action(), "implement")

    def test_isolate_pass_while_still_on_wrong_branch_isolates_again(self) -> None:
        self.make()
        git(self.root, "switch", "-q", "-c", "other")
        self.rec("smoke", "pass")
        self.rec("isolate", "pass")
        self.assertEqual(self.action(), "isolate")

    def test_rule5_task_stages_and_failures_return_to_implement(self) -> None:
        self.make()
        self.rec("smoke", "pass")
        self.assertEqual(self.action(), "implement")
        self.rec("implement", "pass")
        self.assertEqual(self.action(), "verify")
        self.rec("verify", "fail")
        self.assertEqual(self.action(), "implement")
        self.rec("implement", "pass")
        self.rec("verify", "pass")
        self.assertEqual(self.action(), "review")
        self.rec("review", "fail")
        self.assertEqual(self.action(), "implement")
        self.rec("implement", "pass")
        self.rec("verify", "pass")
        self.rec("review", "pass")
        step = self.step()
        self.assertEqual(step["action"], "write-report")
        self.assertIn("openspec/changes/add-export/.delivery/S01-T01-SUMMARY.md", step["files"])
        self.rec("write-report", "pass")
        self.assertEqual(self.action(), "write-report", "a record without the file is not done")
        self.report("S01-T01-SUMMARY.md")
        self.rec("write-report", "pass")
        self.assertEqual(self.action(), "complete")
        self.rec("complete", "pass")
        self.assertEqual(self.action(), "complete", "a record without the tick is not done")
        self.ok("cloud", "complete", "--change", NAME, "--slice", "S01", "--task", "T01")
        step = self.step()
        self.assertEqual((step["action"], step["task"]), ("smoke", "T02"))

    def test_rule6_slice_reports_then_slice_complete(self) -> None:
        self.make()
        step = self.drive_to("slice-reports")
        self.assertEqual(step["slice"], "S01")
        self.assertIsNone(step["task"])
        self.rec("slice-reports", "pass")
        self.assertEqual(self.action(), "slice-reports", "reports are read from disk")
        self.report("S01-UAT.md")
        self.report("S01-SUMMARY.md")
        self.assertEqual(self.action(), "slice-complete")
        self.rec("slice-complete", "pass")
        self.assertEqual(self.action(), "slice-complete", "slices-done is read from the keys")

    def test_rule7_slice_commit_then_push_only_when_ephemeral(self) -> None:
        self.make(cadence=SLICE)
        self.drive_to("ask-commit")
        self.rec("ask-commit", "yes")
        self.assertEqual(self.step()["task"], "T01")
        self.assertEqual(self.step()["slice"], "S02")
        os.environ["W2C_EPHEMERAL"] = "1"
        step = self.step()
        self.assertEqual((step["action"], step["slice"]), ("ask-push", "S01"))
        self.rec("ask-push", "yes")
        self.assertEqual(self.step()["slice"], "S02")

    def test_rule7_commit_no_skips_push(self) -> None:
        os.environ["W2C_EPHEMERAL"] = "1"
        self.make(cadence=SLICE)
        self.drive_to("ask-commit")
        self.rec("ask-commit", "no")
        step = self.step()
        self.assertEqual((step["action"], step["slice"]), ("smoke", "S02"))

    def test_rule7_milestone_cadence_has_no_slice_asks(self) -> None:
        os.environ["W2C_EPHEMERAL"] = "1"
        self.make(cadence=MILESTONE)
        self.drive_to("slice-complete")
        self.perform(self.step())
        step = self.step()
        self.assertEqual((step["action"], step["slice"]), ("smoke", "S02"))

    def test_rule8_milestone_gates_in_order_milestone_cadence(self) -> None:
        self.make(cadence=MILESTONE)
        self.drive_to("milestone-reports")
        seen = self.sequence()
        self.assertEqual(seen, ["milestone-reports", "ask-archive", "ask-commit", "ask-push", "ask-pr", "done"])
        self.assertTrue(any((self.root / "openspec/changes/archive").glob(f"*-{NAME}")))

    def test_rule8_slice_cadence_skips_milestone_commit_and_push_no_skips_pr(self) -> None:
        self.make(cadence=SLICE)
        self.drive_to("milestone-reports")
        seen = self.sequence({"ask-push": "no"})
        self.assertEqual(seen, ["milestone-reports", "ask-archive", "ask-push", "done"])

    def test_rule9_no_answer_stops_with_gate_name(self) -> None:
        self.make(cadence=SLICE)
        self.drive_to("ask-commit")
        self.rec("ask-commit", "no-answer")
        step = self.step()
        self.assertEqual((step["action"], step["reason"]), ("stop", "approval-needed:ask-commit"))
        self.rec("ask-commit", "yes")
        self.assertEqual(self.step()["slice"], "S02")


class StateTests(DriverBase):
    def test_lost_state_restarts_at_implement(self) -> None:
        self.make()
        self.rec("smoke", "pass")
        self.rec("implement", "pass")
        self.rec("verify", "pass")
        self.assertEqual(self.action(), "review")
        self.state_path.unlink()
        self.assertEqual(self.action(), "smoke")
        self.rec("smoke", "pass")
        step = self.step()
        self.assertEqual((step["action"], step["task"]), ("implement", "T01"))

    def test_lost_state_after_next_group_progress_does_not_reask_slice(self) -> None:
        self.make(cadence=SLICE)
        self.drive_to("ask-commit")
        self.state_path.unlink()
        self.assertEqual(self.sequence_to("ask-commit"), ["smoke"], "nothing ticked in S02 yet")
        self.rec("ask-commit", "yes")
        self.drive_to("slice-reports")
        self.state_path.unlink()
        step = self.step()
        self.assertEqual((step["action"], step["slice"]), ("smoke", "S02"))
        self.rec("smoke", "pass")
        self.assertEqual(self.action(), "slice-reports", "S01 asks are not repeated once S02 has ticks")

    def sequence_to(self, wanted: str) -> list[str]:
        seen = []
        while (step := self.step())["action"] != wanted:
            seen.append(step["action"])
            self.perform(step)
        return seen

    def test_bad_json_state_starts_fresh(self) -> None:
        self.make()
        self.rec("smoke", "pass")
        self.rec("implement", "pass")
        for junk in ("{not json", "[1, 2]", json.dumps({"change": NAME, "task": 5, "smoke": "x"}), ""):
            self.state_path.write_text(junk, encoding="utf-8")
            self.assertEqual(self.action(), "smoke", junk)
        self.state_path.write_bytes(b"\xff\xfe")
        self.assertEqual(self.action(), "smoke")

    def test_foreign_change_state_starts_fresh(self) -> None:
        self.make()
        self.rec("smoke", "pass")
        self.rec("implement", "pass")
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        data["change"] = "other-change"
        data["smoke"]["change"] = "other-change"
        self.state_path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.action(), "smoke")
        self.rec("smoke", "pass")
        self.assertEqual(self.action(), "implement")

    def test_state_schema(self) -> None:
        self.make()
        self.rec("smoke", "pass")
        self.rec("implement", "pass")
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(data["change"], NAME)
        self.assertEqual(data["task"], "1.1")
        self.assertEqual((data["last_action"], data["last_result"]), ("implement", "pass"))
        self.assertEqual(data["smoke"], {"change": NAME, "task": "1.1", "result": "pass"})

    def test_post_archive_asks_still_returned(self) -> None:
        self.make(cadence=MILESTONE)
        self.drive_to("ask-archive")
        self.perform(self.step())
        self.assertFalse(self.change.exists())
        step = self.step()
        self.assertEqual((step["action"], step["change"]), ("ask-commit", NAME))
        self.rec("ask-commit", "yes")
        self.assertEqual(self.action(), "ask-push")
        self.rec("ask-push", "no-answer")
        self.assertEqual(self.step()["reason"], "approval-needed:ask-push")
        self.rec("ask-push", "yes")
        self.assertEqual(self.action(), "ask-pr")
        self.rec("ask-pr", "no")
        self.assertEqual(self.step(), {"action": "done", "change": NAME, "slice": None, "task": None,
                                       "files": [], "reason": None})

    def test_ask_archive_yes_without_archive_asks_again(self) -> None:
        self.make(cadence=MILESTONE)
        self.drive_to("ask-archive")
        self.rec("ask-archive", "yes")
        self.assertEqual(self.action(), "ask-archive")

    def test_invalid_record_exits_1_and_changes_nothing(self) -> None:
        self.make()
        self.rec("smoke", "pass")
        before = self.state_path.read_bytes()
        for argv in (
            ("--record", "implement", "--result", "yes"),
            ("--record", "verify", "--result", "pass"),
            ("--record", "ask-commit", "--result", "pass"),
            ("--record", "dance", "--result", "pass"),
            ("--record", "done", "--result", "pass"),
            ("--record", "implement"),
            ("--result", "pass"),
        ):
            code, out, err = run_main(self.root, "cloud", "step", *argv)
            self.assertEqual(code, 1, argv)
            self.assertTrue((out + err).strip(), argv)
            self.assertEqual(self.state_path.read_bytes(), before, argv)


class OutputTests(DriverBase):
    def test_step_json_and_text(self) -> None:
        self.make()
        code, out, _err = run_main(self.root, "cloud", "step", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data, {"action": "smoke", "change": NAME, "slice": "S01", "task": "T01",
                                "files": [], "reason": None})
        self.ok("cloud", "step", "--record", "smoke", "--result", "fail")
        out = self.ok("cloud", "step")
        self.assertEqual(out, f"STEP stop {NAME} S01 T01\nreason: smoke\n")
        out = self.ok("cloud", "step", "--record", "smoke", "--result", "pass")
        self.assertIn("recorded smoke pass", out)
        self.assertEqual(self.ok("cloud", "step"), f"STEP implement {NAME} S01 T01\n")

    def test_brief_prints_only_current_task_context(self) -> None:
        self.make()
        self.report("S01-T01-SUMMARY.md")
        self.ok("cloud", "complete", "--change", NAME, "--slice", "S01", "--task", "T01")
        out = self.ok("cloud", "brief")
        expected = (
            "## Delivery Plan\n\n| Field | Value |\n| --- | --- |\n| Remote branch | DEMO-1 |\n\n"
            "## Guardrails\n\n- Keep the exporter small.\n\n"
            "## Commit and PR Conventions\n\n- Never add a Co-authored-by trailer.\n\n"
            + FIELDS + "\n"
            "- [ ] 1.2 Wire exporter\n  - Verify: true\n"
        )
        self.assertEqual(out, expected)
        for absent in ("Decisions", "Manual Test Guide", "1.1", "2.1", "two", "# Tasks"):
            self.assertNotIn(absent, out)

    def test_brief_without_open_task(self) -> None:
        self.make()
        (self.change / "tasks.md").write_text(TASKS.replace("- [ ]", "- [x]"), encoding="utf-8")
        out = driver.brief(self.root, NAME)
        self.assertTrue(out.startswith("## Delivery Plan\n"))
        self.assertTrue(out.endswith("No open task.\n"))
        self.assertNotIn("**Goal:**", out)


if __name__ == "__main__":
    unittest.main()
