#!/usr/bin/env python3
"""Text checks for the four shipped skills. No model call."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
sys.path.insert(0, str(SRC))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-skill-text-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from w2c.cloud import layout  # noqa: E402
from w2c.skills_install import install_skills  # noqa: E402
from w2c.trials import SKILL_NAMES, run_trials  # noqa: E402

SKILLS = REPO / "skills"
# Copies of the 2.2 skills at the planning commit (bee6a3c), so a shallow checkout can compare.
BASELINE = REPO / "tests" / "fixtures" / "baseline-2.2"
ROUTING = "  Not for cloud mode (use work-to-chores-cloud / do-chores-cloud)."
CLOUD_MOVED = "   If stdout contains `CLOUD_MOVED`, stop and tell the user to run do-chores-cloud. Do not implement that milestone."
ALLOWED = {
    "work-to-chores": (ROUTING,),
    "do-chores": (ROUTING, CLOUD_MOVED),
}


def _text(skill: str, name: str = "SKILL.md") -> str:
    return (SKILLS / skill / name).read_text(encoding="utf-8")


class CloudSkillTextTests(unittest.TestCase):
    def test_both_cloud_skills_require_w2c_3(self) -> None:
        for skill in ("work-to-chores-cloud", "do-chores-cloud"):
            text = _text(skill)
            self.assertIn("Requires: w2c >= 3.0.0", text, skill)
            self.assertIn("uvx --from git+https://github.com/OpenW2C/w2c@v3.0.0 w2c", text, skill)

    def test_do_chores_cloud_names_the_step_loop(self) -> None:
        text = _text("do-chores-cloud")
        for token in ("w2c cloud step", "--record", "no-answer", ".delivery/", "w2c cloud brief",
                      "--max-units", "ask-commit", "ask-push"):
            self.assertIn(token, text)
        self.assertNotIn(".w2c/plans/", text)

    def test_do_chores_cloud_closeout_and_recovery_rules(self) -> None:
        text = _text("do-chores-cloud")
        for token in ("before `ask-archive`", "`w2c cloud archive` removes `.delivery/`",
                      "archive-not-applied", "decline-not-applied", "--record isolate --result pass",
                      "go back to step 1 of the loop", "### Base dirt paths", "w2c cloud decide",
                      "none, because", "Any finding, in any class, fails the review",
                      "First run the Delivery Plan `Validation commands`"):
            self.assertIn(token, text)

    def test_reorder_trial_asks_before_moving(self) -> None:
        data = json.loads(_text("work-to-chores-cloud", "trials.json"))
        row = next(t for t in data["trials"] if t["id"] == "R13")
        self.assertEqual((row["group"], row["kind"]), ("reorder", "ordinary"))
        self.assertIn("placement question", row["must"][0])
        self.assertIn("before running any move", row["must"][0])

    def test_work_to_chores_cloud_names_design_sections_and_convert(self) -> None:
        text = _text("work-to-chores-cloud")
        for token in ("decisions-flush", "migrate --milestone", "--dry-run", "w2c cloud new",
                      "w2c cloud decide", "w2c cloud smoke", "w2c cloud env", "--cadence"):
            self.assertIn(token, text)
        self.assertIn("w2c cloud status --all", text)
        self.assertIn("ephemeral: true", text)
        self.assertIn("push the ticket branch to `origin/<Remote branch>`", text)
        self.assertIn("w2c cloud rules", text)
        self.assertIn("w2c worktree-add --branch <Remote branch> --create-from HEAD", text)
        self.assertNotIn("--branch <name>", text)
        self.assertLess(text.index("command -v w2c"), text.index("--stage prereq"))
        for heading in layout.DESIGN_HEADINGS:
            self.assertIn(heading, text)
        for field in layout.SLICE_FIELDS:
            self.assertIn(f"**{field}:**", text)

    def test_cloud_skills_have_a_written_fallback(self) -> None:
        for skill in ("work-to-chores-cloud", "do-chores-cloud"):
            text = _text(skill)
            self.assertIn("## Companion fallback", text, skill)
        self.assertIn("requesting-code-review", _text("do-chores-cloud"))

    def test_cloud_copilot_wrappers_match_the_2_2_shape(self) -> None:
        for old, new in (("work-to-chores", "work-to-chores-cloud"), ("do-chores", "do-chores-cloud")):
            self.assertEqual(_text(new, "SKILL.copilot.md"), _text(old, "SKILL.copilot.md"))

    def test_2_2_skills_differ_from_baseline_only_by_routing_lines(self) -> None:
        for skill, allowed in ALLOWED.items():
            old = (BASELINE / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
            new = _text(skill)
            for line in allowed:
                self.assertIn(line + "\n", new, f"{skill} lacks {line!r}")
            kept = [line for line in new.splitlines(keepends=True) if line.rstrip("\n") not in allowed]
            self.assertEqual("".join(kept), old, skill)

    def test_trials_pass_for_all_four_skills(self) -> None:
        self.assertEqual(
            SKILL_NAMES, ("work-to-chores", "do-chores", "work-to-chores-cloud", "do-chores-cloud")
        )
        rows, code = run_trials()
        self.assertEqual(code, 0, rows)
        self.assertEqual([(skill, status) for skill, status, _ in rows],
                         [(skill, "PASS") for skill in SKILL_NAMES])


class InstallSkillsTests(unittest.TestCase):
    def test_install_copies_all_four_skills(self) -> None:
        home = Path(tempfile.mkdtemp(prefix="w2c-install-home-"))
        self.addCleanup(shutil.rmtree, home, True)
        with mock.patch.object(Path, "home", return_value=home):
            code = install_skills(SKILLS, RuntimeError, cursor=False, claude=False)
        self.assertEqual(code, 0)
        for skill in SKILL_NAMES:
            for name in ("SKILL.md", "USAGE.md", "trials.json", "SKILL.copilot.md"):
                self.assertTrue((home / ".agents" / "skills" / skill / name).is_file(), f"{skill}/{name}")


if __name__ == "__main__":
    unittest.main()
