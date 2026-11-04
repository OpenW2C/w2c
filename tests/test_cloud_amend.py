#!/usr/bin/env python3
"""Cloud amendments: lock keys, records in design.md, drops, adds, edits."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-cloud-amend-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from test_cloud_commands import NAME, CloudCommandBase, git  # noqa: E402
from test_cloud_checks import fill_design  # noqa: E402
from w2c import openspec_ledger as osl  # noqa: E402
from w2c.cloud import checks, layout, ledger  # noqa: E402

FIELDS = "".join(f"**{name}:** text for {name}\n" for name in layout.SLICE_FIELDS)
TASKS = (
    "# Tasks\n\n"
    "> Read first. Before you start, read design.md.\n\n"
    f"## 1. Export\n\n{FIELDS}\n"
    "- [ ] 1.1 Write exporter\n  - Verify: true\n"
    "- [ ] 1.2 Wire exporter\n  - Verify: true\n\n"
    f"## 2. Docs\n\n{FIELDS}\n"
    "- [ ] 2.1 Document it\n  - Verify: true\n"
)


def read_first() -> str:
    from test_cloud_checks import template

    return template("tasks-read-first.md")


class AmendBase(CloudCommandBase):
    def make(self, status: str = "TODO", **kw) -> Path:
        folder = super().make(status, **kw)
        (folder / "design.md").write_text(fill_design(), encoding="utf-8")
        (folder / "tasks.md").write_text(
            TASKS.replace("> Read first. Before you start, read design.md.\n", read_first()),
            encoding="utf-8",
        )
        (folder / "proposal.md").write_text("# Proposal\n\nWhy.\n", encoding="utf-8")
        spec = folder / "specs" / "export"
        spec.mkdir(parents=True, exist_ok=True)
        (spec / "spec.md").write_text("# Spec\n", encoding="utf-8")
        git(self.root, "add", "-A", "--", f"openspec/changes/{folder.name}")
        git(self.root, "commit", "-qm", "track openspec change")
        return folder

    def decision(self, name: str = NAME) -> str:
        return self.ok(
            "cloud", "decide", "--change", name, "--scope", "scope", "--decision", "Amend",
            "--choice", "yes", "--rationale", "why", "--when", "2026-01-01",
        ).strip()

    def design(self) -> str:
        return (self.change / "design.md").read_text(encoding="utf-8")

    def tasks(self) -> str:
        return (self.change / "tasks.md").read_text(encoding="utf-8")

    def begin(self, did: str) -> str:
        return self.ok("cloud", "amend-begin", "--change", NAME, "--decision", did)

    def end(self) -> str:
        return self.ok("cloud", "amend-end", "--change", NAME)

    def drop_task(self, did: str, tid: str, sid: str = "S01", reason: str = "not needed", *extra: str) -> str:
        return self.ok("cloud", "drop-task", "--change", NAME, "--slice", sid, "--task", tid,
                       "--reason", reason, "--decision", did, *extra)

    def finish(self, sid: str, tid: str) -> None:
        self.report(f"{sid}-{tid}-SUMMARY.md")
        self.ok("cloud", "complete", "--change", NAME, "--slice", sid, "--task", tid)

    def status_key(self) -> str:
        return re.search(r"x-delivery-status: (\w+)", self.meta()).group(1)


class LockTests(AmendBase):
    def test_begin_sets_three_keys_and_pauses_inprogress(self) -> None:
        self.make("INPROGRESS")
        did = self.decision()
        self.assertEqual(did, "D1")
        self.assertIn("amend-begin", self.begin(did))
        meta = self.meta()
        self.assertIn("x-delivery-amend-lock: D1", meta)
        self.assertIn("x-delivery-amend-prior-status: INPROGRESS", meta)
        self.assertIn("x-delivery-amend-decision: D1", meta)
        self.assertEqual(self.status_key(), "PAUSED")

    def test_begin_keeps_planning_and_todo(self) -> None:
        for status in ("PLANNING", "TODO"):
            self.make(status)
            did = self.decision()
            self.begin(did)
            self.assertEqual(self.status_key(), status)
            self.end()

    def test_begin_refuses_closed_states_and_second_lock(self) -> None:
        self.make("TODO")
        did = self.decision()
        for status in ("DONE", "STOP", "ERROR"):
            ledger.write_key(self.change / ".openspec.yaml", "x-delivery-status", status)
            self.assertIn(status, self.bad("cloud", "amend-begin", "--change", NAME, "--decision", did))
            self.assertNotIn("amend-lock", self.meta())
        ledger.write_key(self.change / ".openspec.yaml", "x-delivery-status", "TODO")
        self.begin(did)
        self.assertIn("already", self.bad("cloud", "amend-begin", "--change", NAME, "--decision", did))

    def test_unknown_decision_id_is_refused(self) -> None:
        self.make()
        did = self.decision()
        self.assertIn("D9", self.bad("cloud", "amend-begin", "--change", NAME, "--decision", "D9"))
        self.assertIn("invalid decision", self.bad("cloud", "amend-begin", "--change", NAME, "--decision", "x"))
        self.begin(did)
        self.assertIn("D9", self.bad("cloud", "drop-task", "--change", NAME, "--slice", "S01",
                                      "--task", "T01", "--reason", "r", "--decision", "D9"))
        self.assertIn("[ ] 1.1", self.tasks())

    def test_mutations_need_the_lock_and_the_same_decision(self) -> None:
        self.make()
        did = self.decision()
        self.decision()
        out = self.bad("cloud", "drop-task", "--change", NAME, "--slice", "S01", "--task", "T01",
                       "--reason", "r", "--decision", did)
        self.assertIn("lock is not held", out)
        self.begin(did)
        out = self.bad("cloud", "drop-task", "--change", NAME, "--slice", "S01", "--task", "T01",
                       "--reason", "r", "--decision", "D2")
        self.assertIn("does not match", out)
        self.assertIn("no cloud change", self.bad("cloud", "amend-end", "--change", "nope"))

    def test_locked_change_blocks_next_and_complete(self) -> None:
        self.make("INPROGRESS")
        did = self.decision()
        self.begin(did)
        code, out, _ = __import__("test_cloud_commands").run_main(self.root, "cloud", "next", "--change", NAME)
        self.assertEqual(code, 1)
        self.assertIn("AMEND_LOCK", out)
        self.report("S01-T01-SUMMARY.md")
        self.assertIn("AMEND_LOCK", self.bad("cloud", "complete", "--change", NAME, "--slice", "S01", "--task", "T01"))


class DropTests(AmendBase):
    def test_drop_skips_next_and_refuses_finished_work(self) -> None:
        self.make()
        did = self.decision()
        self.begin(did)
        out = self.drop_task(did, "T01")
        self.assertIn(f"drop-task {NAME} S01 T01", out)
        self.assertIn("[d] 1.1 Write exporter", self.tasks())
        self.end()
        self.assertIn("NEXT add-export S01 T02", self.ok("cloud", "next"))
        self.finish("S01", "T02")
        self.begin(did)
        self.assertIn("finished", self.bad("cloud", "drop-task", "--change", NAME, "--slice", "S01",
                                           "--task", "T02", "--reason", "no", "--decision", did))
        self.assertIn("finished", self.bad("cloud", "drop-slice", "--change", NAME, "--slice", "S01",
                                           "--reason", "no", "--decision", did))
        self.assertIn("[x] 1.2", self.tasks())
        self.end()

    def test_drop_task_twice_is_refused(self) -> None:
        self.make()
        did = self.decision()
        self.begin(did)
        self.drop_task(did, "T01")
        self.assertIn("already dropped", self.bad("cloud", "drop-task", "--change", NAME, "--slice", "S01",
                                                  "--task", "T01", "--reason", "r", "--decision", did))

    def test_dropped_slice_does_not_block_completion(self) -> None:
        self.make()
        did = self.decision()
        self.begin(did)
        out = self.ok("cloud", "drop-slice", "--change", NAME, "--slice", "S01",
                      "--reason", "slice is unnecessary", "--decision", did)
        self.assertIn(f"drop-slice {NAME} S01", out)
        text = self.tasks()
        self.assertIn("[d] 1.1", text)
        self.assertIn("[d] 1.2", text)
        self.assertIn("[ ] 2.1", text)
        self.end()
        self.finish("S02", "T01")
        self.report("S02-UAT.md")
        self.report("S02-SUMMARY.md")
        self.ok("cloud", "slice-complete", "--change", NAME, "--slice", "S02")
        self.report("VALIDATION.md")
        self.report("SUMMARY.md")
        self.ok("cloud", "milestone-complete", NAME, "--archive-declined")
        self.assertFalse((self.change / ".delivery" / "S01-UAT.md").exists())

    def test_mixed_slice_requires_reports_that_name_the_drop(self) -> None:
        self.make()
        self.finish("S01", "T01")
        did = self.decision()
        self.begin(did)
        self.drop_task(did, "T02", "S01", "later")
        self.end()
        self.assertIn("missing report", self.bad("cloud", "slice-complete", "--change", NAME, "--slice", "S01"))
        self.report("S01-UAT.md")
        self.report("S01-SUMMARY.md", "# S01\n\nshipped T01\n")
        self.assertIn("T02", self.bad("cloud", "slice-complete", "--change", NAME, "--slice", "S01"))
        self.report("S01-SUMMARY.md", "# S01\n\nshipped T01\ndropped T02\n")
        self.ok("cloud", "slice-complete", "--change", NAME, "--slice", "S01")


class RecordTests(AmendBase):
    def test_records_land_under_amendments_with_four_bullets(self) -> None:
        self.make()
        did = self.decision()
        self.begin(did)
        self.drop_task(did, "T01", "S01", "use case was wrong", "--follow-up", "later",
                       "--ticket", "https://example.com/t/0")
        self.ok("cloud", "task-add", "--change", NAME, "--slice", "S02", "--title", "Extra",
                "--verify", "true", "--reason", "need it", "--decision", did)
        design = self.design()
        body = design[design.index("## Amendments"):]
        self.assertIn(
            "### A001 drop-task add-export/S01/T01\n\n- decision: D1\n- reason: use case was wrong\n"
            "- follow-up: later\n- ticket: https://example.com/t/0\n", body)
        self.assertIn("### A002 task-add add-export/S02/T02\n\n- decision: D1\n- reason: need it\n"
                      "- follow-up: \n- ticket: \n", body)
        self.assertNotIn("Amendments", self.tasks())

    def test_section_created_at_end_when_missing_and_inserted_before_next_heading(self) -> None:
        self.make()
        did = self.decision()
        design = self.design().replace("## Amendments", "## Amendments Old")
        (self.change / "design.md").write_text(design, encoding="utf-8")
        self.begin(did)
        self.drop_task(did, "T01")
        text = self.design()
        self.assertTrue(text.rstrip("\n").splitlines()[-6].startswith("### A001"))
        self.assertEqual(text.count("\n## Amendments\n"), 1)
        # a section followed by another heading keeps the record inside the section
        (self.change / "design.md").write_text(
            text.replace("\n## Amendments\n", "\n## Amendments\n", 1) + "\n## Later\n\nx\n", encoding="utf-8")
        self.drop_task(did, "T02")
        text = self.design()
        self.assertLess(text.index("### A002"), text.index("## Later"))
        self.assertGreater(text.index("### A002"), text.index("### A001"))

    def test_follow_up_replaces_only_the_ticket_link(self) -> None:
        self.make()
        did = self.decision()
        self.begin(did)
        self.drop_task(did, "T02", "S01", "use case was wrong", "--follow-up", "pick up the export later")
        self.ok("cloud", "follow-up", "--change", NAME, "--slice", "S01", "--task", "T02",
                "--ticket", "https://example.com/t/1")
        text = self.design()
        self.assertIn("- reason: use case was wrong", text)
        self.assertIn("- follow-up: pick up the export later", text)
        self.assertIn("- ticket: https://example.com/t/1", text)
        self.ok("cloud", "follow-up", "--change", NAME, "--slice", "S01", "--task", "T02",
                "--ticket", "https://example.com/t/2")
        text = self.design()
        self.assertIn("- reason: use case was wrong", text)
        self.assertIn("- ticket: https://example.com/t/2", text)
        self.assertNotIn("t/1", text)
        self.assertIn("no amendment", self.bad("cloud", "follow-up", "--change", NAME, "--slice", "S02",
                                               "--ticket", "https://example.com/t/3"))

    def test_amendments_prints_the_records(self) -> None:
        self.make()
        self.assertIn(f"amendments {NAME} none", self.ok("cloud", "amendments", "--change", NAME))
        did = self.decision()
        self.begin(did)
        self.drop_task(did, "T01")
        out = self.ok("cloud", "amendments", "--change", NAME)
        self.assertIn("### A001 drop-task add-export/S01/T01", out)
        self.assertNotIn("## Decisions", out)


class EditTests(AmendBase):
    def test_task_edit_changes_only_title_and_verify(self) -> None:
        self.make()
        did = self.decision()
        self.begin(did)
        self.ok("cloud", "task-edit", "--change", NAME, "--slice", "S01", "--task", "T02",
                "--title", "Wire it better", "--verify", "echo ok", "--reason", "clearer", "--decision", did)
        text = self.tasks()
        self.assertIn("- [ ] 1.2 Wire it better\n  - Verify: echo ok\n", text)
        self.assertIn("- [ ] 1.1 Write exporter\n  - Verify: true\n", text)
        self.assertIn("### A001 task-edit add-export/S01/T02", self.design())

    def test_task_edit_refuses_a_finished_task(self) -> None:
        self.make()
        self.finish("S01", "T01")
        did = self.decision()
        self.begin(did)
        out = self.bad("cloud", "task-edit", "--change", NAME, "--slice", "S01", "--task", "T01",
                       "--title", "x", "--verify", "y", "--reason", "r", "--decision", did)
        self.assertIn("finished", out)
        self.assertIn("[x] 1.1 Write exporter", self.tasks())

    def test_task_add_goes_after_the_groups_last_task_with_next_number(self) -> None:
        self.make()
        did = self.decision()
        self.begin(did)
        out = self.ok("cloud", "task-add", "--change", NAME, "--slice", "S01", "--title", "Third",
                      "--verify", "true", "--reason", "need", "--decision", did)
        self.assertIn(f"task-add {NAME} S01 T03", out)
        text = self.tasks()
        self.assertIn("  - Verify: true\n- [ ] 1.3 Third\n  - Verify: true\n\n## 2. Docs", text)
        self.assertEqual([t.openspec_id for t in osl.parse_openspec_tasks(self.change / "tasks.md", "x")],
                         ["1.1", "1.2", "1.3", "2.1"])
        self.end()

    def test_slice_add_blocks_amend_end_until_fields_filled(self) -> None:
        self.make("INPROGRESS")
        did = self.decision()
        self.begin(did)
        out = self.ok("cloud", "slice-add", "--change", NAME, "--title", "Release",
                      "--reason", "ship it", "--decision", did)
        self.assertIn(f"slice-add {NAME} S03", out)
        text = self.tasks()
        self.assertTrue(text.rstrip("\n").endswith(
            "## 3. Release\n\n" + "".join(f"**{n}:**\n" for n in layout.SLICE_FIELDS).rstrip("\n")))
        self.assertIn("### A001 slice-add add-export/S03\n", self.design())
        code, out, err = __import__("test_cloud_commands").run_main(self.root, "cloud", "amend-end", "--change", NAME)
        self.assertEqual(code, 1, out + err)
        self.assertIn("slice-fields", out)
        self.assertIn("x-delivery-amend-lock: D1", self.meta())
        self.assertEqual(self.status_key(), "PAUSED")
        filled = re.sub(r"^(\*\*[^*]+:\*\*)$", r"\1 filled", text.split("## 3. Release")[1], flags=re.M)
        (self.change / "tasks.md").write_text(text.split("## 3. Release")[0] + "## 3. Release" + filled,
                                              encoding="utf-8")
        self.assertIn("amend-end", self.end())
        meta = self.meta()
        self.assertNotIn("amend-", meta)
        self.assertEqual(self.status_key(), "PAUSED")

    def test_empty_amend_restores_status_and_a_change_stays_paused(self) -> None:
        self.make("INPROGRESS")
        did = self.decision()
        self.begin(did)
        self.assertEqual(self.status_key(), "PAUSED")
        self.end()
        self.assertEqual(self.status_key(), "INPROGRESS")
        self.assertNotIn("amend-", self.meta())
        self.begin(did)
        self.drop_task(did, "T02", "S01", "defer")
        self.assertIn("PAUSED", self.end())
        self.assertEqual(self.status_key(), "PAUSED")
        self.assertNotIn("amend-", self.meta())

    def test_end_without_lock_is_refused(self) -> None:
        self.make()
        self.assertIn("lock is not held", self.bad("cloud", "amend-end", "--change", NAME))


class SliceFieldsTests(unittest.TestCase):
    def test_unknown_bold_label_ends_the_field(self) -> None:
        group = "## 1. A\n\n" + "".join(
            f"**{n}:** x\n" for n in layout.SLICE_FIELDS[:-1]
        ) + "**Files Likely Touched:**\n**Note:** text\n\n- [ ] 1.1 t\n"
        fields = checks.slice_fields(group)
        self.assertEqual(fields[1]["Files Likely Touched"], "")
        self.assertNotIn("Note", fields[1])


if __name__ == "__main__":
    unittest.main()
