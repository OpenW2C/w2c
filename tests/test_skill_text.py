#!/usr/bin/env python3
"""Text checks for the four shipped skills. No model call."""

from __future__ import annotations

import os
import shutil
import subprocess
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
TASK0 = "bee6a3c"
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

    def test_work_to_chores_cloud_names_design_sections_and_convert(self) -> None:
        text = _text("work-to-chores-cloud")
        for token in ("decisions-flush", "migrate --milestone", "--dry-run", "w2c cloud new",
                      "w2c cloud decide", "w2c cloud smoke", "w2c cloud env", "--cadence"):
            self.assertIn(token, text)
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

    def test_2_2_skills_differ_from_task0_only_by_routing_lines(self) -> None:
        for skill, allowed in ALLOWED.items():
            old = subprocess.run(
                ["git", "-C", str(REPO), "show", f"{TASK0}:skills/{skill}/SKILL.md"],
                capture_output=True, text=True, check=True,
            ).stdout
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
