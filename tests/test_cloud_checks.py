#!/usr/bin/env python3
"""Cloud mode smoke rows: design sections, slice fields, reports, OpenSpec rows."""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-cloud-checks-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from w2c.cloud import checks, layout, ledger  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fake_openspec.py"
CLOUD = ROOT / "templates" / "cloud"
ORIGINAL_PATH = os.environ.get("PATH", "")
CADENCE = sorted(ledger.CADENCES)[0]

CHECK_NAMES = {
    "openspec-cli",
    "delivery-keys-valid",
    "design-sections",
    "git-operation-plan",
    "commit-pr-conventions",
    "manual-test-guide",
    "slice-fields",
    "read-first-present",
    "openspec-validate-strict",
    "openspec-artifacts-complete",
    "openspec-tasks-have-verify",
    "openspec-progress-agrees",
    "ticked-without-report",
    "closeout-reports",
    "neutral-artifacts",
    "unique-change-ids",
    "openspec-archived-when-done",
}


def template(*parts: str) -> str:
    return CLOUD.joinpath(*parts).read_text(encoding="utf-8")


def fill_design(**plan: str) -> str:
    """The real design template with every Delivery Plan row filled in."""
    values = {
        "Isolation mode": "branch",
        "Local branch": "DEMO-1",
        "Remote branch": "DEMO-1",
        "Worktree skill": "n/a",
        "Base dirt policy": "clean-at-plan",
        "Manual test guide": "no",
    }
    values.update({k.replace("_", " "): v for k, v in plan.items()})
    text = template("design-delivery.md")

    def fill(match: re.Match) -> str:
        field, current = match.group(1), match.group(2).strip()
        value = values.get(field, current or "none")
        return f"| {field} | {value} |"

    return re.sub(r"^\| ([^|]+?) \|([^|\n]*)\|$", lambda m: fill(m) if m.group(1) not in ("Field", "---") else m.group(0), text, flags=re.M)


def fill_tasks() -> str:
    read_first = template("tasks-read-first.md")
    group = template("slice-group.md").replace("N.", "1.").replace("N ", "1 ").replace("TITLE", "Export")
    group = group.replace("## N", "## 1")
    for name in layout.SLICE_FIELDS:
        group = re.sub(rf"^(\*\*{re.escape(name)}:\*\*)$", rf"\1 text for {name}", group, flags=re.M)
    group = group.replace("1.1 First task", "1.1 First task\n  - Verify: python3 -c 'print(1)'")
    return "# Tasks\n\n" + read_first + "\n" + group


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


class CloudChecksBase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="w2c-cc-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        bindir = self.root / "bin"
        bindir.mkdir()
        dest = bindir / "openspec"
        dest.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
        dest.chmod(0o755)
        os.environ["PATH"] = str(bindir) + os.pathsep + ORIGINAL_PATH
        self.addCleanup(lambda: os.environ.__setitem__("PATH", ORIGINAL_PATH))
        self.addCleanup(lambda: os.environ.pop("FAKE_OPENSPEC_VALIDATE", None))

    def make(self, name: str = "add-export", *, archived: str = "", keys: list[str] | None = None,
             design: str | None = None, tasks: str | None = None) -> Path:
        base = self.root / "openspec" / "changes"
        folder = base / "archive" / f"{archived}-{name}" if archived else base / name
        lines = ["schema: spec-driven", "x-delivery-status: TODO", f"x-delivery-cadence: {CADENCE}", "x-delivery-order: 1"]
        write(folder / ".openspec.yaml", "\n".join(keys if keys is not None else lines))
        write(folder / "proposal.md", "# Proposal\n\nWhy.\n")
        write(folder / "specs" / "export" / "spec.md", "# Spec\n")
        write(folder / "design.md", design if design is not None else fill_design())
        write(folder / "tasks.md", tasks if tasks is not None else fill_tasks())
        return folder

    def rows(self) -> dict[str, tuple[str, str]]:
        changes = ledger.list_changes(self.root, include_archived=True)
        out = {}
        for name, status, detail in checks.smoke_rows(self.root, changes):
            out[name] = (status, detail)
        return out

    def failing(self) -> set[str]:
        return {n for n, (s, _d) in self.rows().items() if s == "FAIL"}

    def set_key(self, folder: Path, key: str, value: str | None) -> None:
        ledger.write_key(folder / ".openspec.yaml", key, value)


class ValidFixtureTests(CloudChecksBase):
    def test_valid_change_passes_every_row(self) -> None:
        self.make()
        rows = self.rows()
        self.assertEqual(set(rows), CHECK_NAMES)
        self.assertEqual(self.failing(), set(), rows)

    def test_conventions_pass_on_the_real_template_text(self) -> None:
        self.assertEqual(checks.validate_conventions(template("design-delivery.md")), [])
        self.assertNotIn(".w2c", template("design-delivery.md"))

    def test_no_changes_no_rows(self) -> None:
        self.assertEqual(checks.smoke_rows(self.root, []), [])


class MutationTests(CloudChecksBase):
    def flips(self, expected: set[str]) -> None:
        self.assertEqual(self.failing(), expected, self.rows())

    def test_bad_status_flips_keys(self) -> None:
        folder = self.make()
        self.set_key(folder, "x-delivery-status", "BOGUS")
        self.flips({"delivery-keys-valid"})

    def test_key_value_problems(self) -> None:
        cases = [
            ("x-delivery-cadence", None),
            ("x-delivery-cadence", "hourly"),
            ("x-delivery-order", "first"),
            ("x-delivery-slices-done", "[a]"),
            ("x-delivery-archive", "yes"),
            ("x-delivery-amend-lock", "yes"),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                shutil.rmtree(self.root / "openspec", ignore_errors=True)
                folder = self.make()
                self.set_key(folder, key, value)
                self.flips({"delivery-keys-valid"})

    def test_good_optional_keys_pass(self) -> None:
        folder = self.make()
        self.set_key(folder, "x-delivery-slices-done", "[]")
        self.set_key(folder, "x-delivery-amend-lock", "set")
        self.set_key(folder, "x-delivery-amend-prior-status", "INPROGRESS")
        self.set_key(folder, "x-delivery-amend-decision", "keep scope")
        self.flips(set())

    def test_amend_lock_needs_status_and_decision(self) -> None:
        folder = self.make()
        self.set_key(folder, "x-delivery-amend-lock", "set")
        self.set_key(folder, "x-delivery-amend-prior-status", "NOPE")
        self.set_key(folder, "x-delivery-amend-decision", "keep scope")
        self.flips({"delivery-keys-valid"})

    def test_missing_design_section(self) -> None:
        self.make(design=fill_design().replace("## Amendments\n", ""))
        self.flips({"design-sections"})

    def test_git_operation_plan_breaks(self) -> None:
        self.make(design=fill_design(Remote_branch="OTHER-2"))
        self.flips({"git-operation-plan"})

    def test_leave_untouched_needs_base_dirt_paths(self) -> None:
        self.make(design=fill_design(Base_dirt_policy="leave-untouched"))
        self.flips({"git-operation-plan"})
        folder = self.root / "openspec/changes/add-export"
        text = fill_design(Base_dirt_policy="leave-untouched").replace(
            "\n## Guardrails", "\n### Base dirt paths\n\n- notes.txt\n\n## Guardrails", 1
        )
        write(folder / "design.md", text)
        self.flips(set())

    def test_conventions_each_rule(self) -> None:
        base = fill_design()
        cases = {
            "co-author ban": base.replace("Co-authored-by", "co author"),
            "stage ban": base.replace("Do not stage / commit", "Staging notes").replace("never stage", "may stage"),
            "mention ban names .delivery/": base.replace("Never name any `.delivery/` path", "Never name any path"),
            "product content": base.replace("is product content and is never deny-listed", "is ordinary"),
        }
        for label, design in cases.items():
            with self.subTest(label):
                self.assertNotEqual(design, base)
                shutil.rmtree(self.root / "openspec", ignore_errors=True)
                self.make(design=design)
                self.flips({"commit-pr-conventions"})

    def test_conventions_never_require_dot_w2c(self) -> None:
        self.assertFalse(any(".w2c" in p for p in checks.validate_conventions(fill_design())))

    def test_manual_test_guide(self) -> None:
        self.make(design=fill_design(Manual_test_guide="maybe"))
        self.flips({"manual-test-guide"})
        shutil.rmtree(self.root / "openspec")
        self.make(design=fill_design(Manual_test_guide="yes"))
        self.flips({"manual-test-guide"})
        shutil.rmtree(self.root / "openspec")
        self.make(design=fill_design(Manual_test_guide="yes").replace("## Manual Test Guide\n", "## Manual Test Guide\n\nOpen the page and click export.\n"))
        self.flips(set())

    def test_slice_field_missing(self) -> None:
        tasks = re.sub(r"^\*\*Threat Surface:\*\*.*\n", "", fill_tasks(), flags=re.M)
        self.make(tasks=tasks)
        self.flips({"slice-fields"})

    def test_read_first_missing_or_without_stop_sentence(self) -> None:
        tasks = fill_tasks()
        no_block = tasks.replace(template("tasks-read-first.md"), "")
        self.assertNotEqual(no_block, tasks)
        self.make(tasks=no_block)
        self.flips({"read-first-present"})
        shutil.rmtree(self.root / "openspec")
        self.make(tasks=tasks.replace(layout.STOP_SENTENCE, "Be careful."))
        self.flips({"read-first-present"})

    def test_read_first_template_is_a_quote_block(self) -> None:
        text = template("tasks-read-first.md")
        lines = [l for l in text.splitlines() if l.strip()]
        self.assertTrue(all(l.startswith(">") for l in lines))
        self.assertNotIn("\n## ", "\n" + text)
        self.assertTrue(lines[0].startswith("> **" + layout.READ_FIRST_MARKER + ":**"))
        for part in ("Delivery Plan", "Guardrails", "Commit and PR Conventions", "openspec/knowledge.md", "## N."):
            self.assertIn(part, text)
        self.assertIn(layout.STOP_SENTENCE, text.replace("\n> ", " "))
        self.assertNotIn("w2c", text.lower())

    def test_read_first_is_literal(self) -> None:
        tasks = fill_tasks().replace(layout.READ_FIRST_MARKER, "Read First")
        self.make(tasks=tasks)
        self.flips({"read-first-present"})

    def test_empty_slice_field_fails(self) -> None:
        tasks = fill_tasks().replace("**Demo:** text for Demo", "**Demo:**   ")
        self.assertNotEqual(tasks, fill_tasks())
        self.make(tasks=tasks)
        self.flips({"slice-fields"})

    def test_read_first_text_after_first_group_does_not_count(self) -> None:
        tasks = fill_tasks().replace(template("tasks-read-first.md"), "")
        tasks += "\n" + template("tasks-read-first.md")
        self.make(tasks=tasks)
        self.flips({"read-first-present"})

    def test_ticked_without_report(self) -> None:
        folder = self.make(tasks=fill_tasks().replace("- [ ] 1.1", "- [x] 1.1"))
        self.flips({"ticked-without-report"})
        write(folder / ".delivery" / "S01-T01-SUMMARY.md", "# T01\n")
        self.flips(set())

    def test_closeout_reports_for_finished_slice(self) -> None:
        folder = self.make()
        self.set_key(folder, "x-delivery-slices-done", "[1]")
        self.flips({"closeout-reports"})
        write(folder / ".delivery" / "S01-UAT.md", "# UAT\n")
        self.flips({"closeout-reports"})
        write(folder / ".delivery" / "S01-SUMMARY.md", "# S01\n")
        self.flips(set())

    def test_closeout_reports_for_declined_archive(self) -> None:
        folder = self.make()
        self.set_key(folder, "x-delivery-status", "DONE")
        self.set_key(folder, "x-delivery-archive", "declined")
        self.flips({"closeout-reports"})
        write(folder / ".delivery" / "VALIDATION.md", "# V\n")
        self.flips({"closeout-reports"})
        write(folder / ".delivery" / "SUMMARY.md", "# S\n")
        self.flips(set())

    def test_w2c_anywhere_in_active_change(self) -> None:
        for rel in ("notes.md", ".delivery/S01-UAT.md", "specs/export/extra.md"):
            with self.subTest(rel):
                shutil.rmtree(self.root / "openspec", ignore_errors=True)
                folder = self.make()
                write(folder / rel, "Run W2C first.")
                self.flips({"neutral-artifacts"})
        shutil.rmtree(self.root / "openspec")
        folder = self.make()
        self.set_key(folder, "x-w2c-milestone", "M001")
        self.flips({"neutral-artifacts"})

    def test_shared_legacy_id(self) -> None:
        a = self.make("alpha")
        b = self.make("beta", keys=[
            "schema: spec-driven", "x-delivery-status: TODO",
            f"x-delivery-cadence: {CADENCE}", "x-delivery-order: 2",
        ])
        self.set_key(a, "x-delivery-legacy-id", "M001")
        self.set_key(b, "x-delivery-legacy-id", "M001")
        self.flips({"unique-change-ids"})
        self.set_key(b, "x-delivery-legacy-id", "M002")
        self.flips(set())

    def test_archived_twin_counts_for_unique_ids(self) -> None:
        a = self.make("alpha")
        self.set_key(a, "x-delivery-legacy-id", "M001")
        old = self.make("beta", archived="2026-01-01", keys=[
            "schema: spec-driven", "x-delivery-status: DONE", "x-delivery-legacy-id: M001",
        ])
        self.assertTrue(old.is_dir())
        self.flips({"unique-change-ids"})

    def test_done_unarchived_without_decision(self) -> None:
        folder = self.make()
        self.set_key(folder, "x-delivery-status", "DONE")
        self.flips({"openspec-archived-when-done"})
        self.set_key(folder, "x-delivery-archive", "declined")
        write(folder / ".delivery" / "VALIDATION.md", "# V\n")
        write(folder / ".delivery" / "SUMMARY.md", "# S\n")
        self.flips(set())

    def test_validate_strict_failure(self) -> None:
        self.make()
        os.environ["FAKE_OPENSPEC_VALIDATE"] = "fail"
        self.flips({"openspec-validate-strict"})

    def test_missing_verify_line(self) -> None:
        self.make(tasks=fill_tasks().replace("\n  - Verify: python3 -c 'print(1)'", ""))
        self.flips({"openspec-tasks-have-verify"})

    def test_progress_disagreement(self) -> None:
        self.make()
        os.environ["FAKE_OPENSPEC_APPLY_DONE"] = "1"
        self.addCleanup(lambda: os.environ.pop("FAKE_OPENSPEC_APPLY_DONE", None))
        self.flips({"openspec-progress-agrees"})

    def test_missing_artifact_fails_completeness(self) -> None:
        folder = self.make()
        (folder / "proposal.md").unlink()
        self.flips({"openspec-artifacts-complete"})


class ArchivedChangeTests(CloudChecksBase):
    def test_archived_change_is_history(self) -> None:
        folder = self.make(
            "old-work",
            archived="2026-01-01",
            keys=["schema: spec-driven", "x-delivery-status: DONE", "x-delivery-slices-done: [1]"],
        )
        write(folder / "notes.md", "legacy W2C text")
        os.environ["FAKE_OPENSPEC_VALIDATE"] = "fail"
        os.environ["FAKE_OPENSPEC_APPLY_DONE"] = "1"
        self.addCleanup(lambda: os.environ.pop("FAKE_OPENSPEC_APPLY_DONE", None))
        self.assertEqual(self.failing(), set(), self.rows())

    STRUCTURAL = {"design-sections", "git-operation-plan", "commit-pr-conventions", "manual-test-guide",
                  "slice-fields", "read-first-present"}

    def test_native_archived_change_keeps_structural_rows(self) -> None:
        self.make("old-work", archived="2026-01-01", design="# Design\n", tasks="# Tasks\n\n## 1. Old\n",
                  keys=["schema: spec-driven", "x-delivery-status: DONE"])
        self.assertTrue(self.STRUCTURAL <= self.failing(), self.rows())

    def test_converted_archived_done_is_history(self) -> None:
        self.make("old-work", archived="2026-01-01", design="# Design\n", tasks="# Tasks\n\n## 1. Old\n",
                  keys=["schema: spec-driven", "x-delivery-status: DONE", "x-delivery-legacy-id: M001",
                        "x-delivery-slices-done: [1]"])
        self.assertEqual(self.failing(), set(), self.rows())

    def test_converted_declined_done_is_history(self) -> None:
        tasks = "# Tasks\n\n## 1. Old\n\n- [x] 1.1 Done work\n  - Verify: true\n"
        self.make("old-work", design="# Design\n", tasks=tasks,
                  keys=["schema: spec-driven", "x-delivery-status: DONE", "x-delivery-archive: declined",
                        f"x-delivery-cadence: {CADENCE}", "x-delivery-legacy-id: M001", "x-delivery-slices-done: [1]"])
        self.assertEqual(self.failing(), set(), self.rows())

    def test_native_declined_done_keeps_closeout_and_structure(self) -> None:
        self.make("old-work", design="# Design\n",
                  keys=["schema: spec-driven", "x-delivery-status: DONE", "x-delivery-archive: declined",
                        f"x-delivery-cadence: {CADENCE}"])
        failing = self.failing()
        self.assertIn("closeout-reports", failing)
        self.assertIn("design-sections", failing)

    def test_unknown_bold_label_after_an_empty_field_fails_slice_fields(self) -> None:
        text = fill_tasks().replace(
            "**Files Likely Touched:** text for Files Likely Touched",
            "**Files Likely Touched:**\n**Note:** text",
        )
        self.make(tasks=text)
        self.assertEqual(self.failing(), {"slice-fields"})
        self.assertIn("empty Files Likely Touched", self.rows()["slice-fields"][1])


class GroupTextTests(unittest.TestCase):
    def test_group_text_is_not_a_task(self) -> None:
        from w2c import openspec_ledger as osl

        tmp = Path(tempfile.mkdtemp(prefix="w2c-cc-grp-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        text = fill_tasks().replace(
            "**Files Likely Touched:** text for Files Likely Touched",
            "**Files Likely Touched:** src/a.py\n- see 1.9 notes\n[ ] 1.8 not a task",
        )
        path = tmp / "tasks.md"
        write(path, text)
        tasks = osl.parse_openspec_tasks(path, "demo")
        self.assertEqual([t.openspec_id for t in tasks], ["1.1"])
        fields = checks.slice_fields(text)
        self.assertEqual(sorted(fields), [1])
        self.assertEqual(list(fields[1]), list(layout.SLICE_FIELDS))
        self.assertEqual(fields[1]["Goal"], "text for Goal")
        self.assertIn("see 1.9 notes", fields[1]["Files Likely Touched"])
        self.assertNotIn("First task", fields[1]["Files Likely Touched"])
        self.assertNotIn("Verify", fields[1]["Files Likely Touched"])

    def test_slice_fields_splits_groups(self) -> None:
        text = "## 1. A\n\n**Goal:** one\n\n- [ ] 1.1 x\n\n## 2. B\n\n**Demo:** two\n"
        self.assertEqual(checks.slice_fields(text), {1: {"Goal": "one"}, 2: {"Demo": "two"}})


if __name__ == "__main__":
    unittest.main()
