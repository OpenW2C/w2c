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


class LocalSkillSeedGuardTests(unittest.TestCase):
    def test_local_skills_require_w2c_32_and_seed_check(self) -> None:
        expected = {"work-to-chores": "Requires: w2c >= 3.3.1", "do-chores": "Requires: w2c >= 3.3.0"}
        for skill, req in expected.items():
            text = _text(skill)
            self.assertIn(req, text, skill)
            self.assertIn("w2c worktree-seed --check", text, skill)
            self.assertIn("w2c worktree-seed", text, skill)
            self.assertIn("STOP", text, skill)

    def test_cloud_skills_name_worktree_seed_guard(self) -> None:
        for skill in ("work-to-chores-cloud", "do-chores-cloud"):
            text = _text(skill)
            self.assertIn("w2c worktree-seed --check", text, skill)


class CloudSkillTextTests(unittest.TestCase):
    def test_both_cloud_skills_require_w2c_3(self) -> None:
        for skill in ("work-to-chores-cloud", "do-chores-cloud"):
            text = _text(skill)
            self.assertIn("Requires: w2c >= 3.3.0", text, skill)
            self.assertIn("uvx --from git+https://github.com/OpenW2C/w2c@v3.3.0 w2c", text, skill)

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

    def test_cloud_skills_ask_before_fallback(self) -> None:
        question = (
            "These companion skills are not installed here: <names>. "
            "Without them I use the written fallback in this skill.",
            "(a) Stop now so you can install them, then run this skill again. "
            "[recommended when agent is claude-code and ephemeral is false]",
            "(b) Continue with the written fallback. [recommended otherwise]",
        )
        for skill in ("work-to-chores-cloud", "do-chores-cloud"):
            text = _text(skill)
            self.assertIn("### Missing companion skills (ask first)", text, skill)
            for line in question:
                self.assertIn(line, text, skill)
            for token in ("w2c help companions", "agent:", '--event stop --detail "install <names>"',
                          "one question for every missing companion"):
                self.assertIn(token, text, skill)
            self.assertNotIn("Tell the user once which companion is missing", text, skill)
            self.assertNotIn("and tell the user once", text, skill)
            for event in ("stop", "retry"):
                self.assertIn(f"w2c event --skill {skill} --stage prereq --event {event}", text, skill)
            self.assertIn("`ephemeral:`", text.split("### Missing companion skills (ask first)", 1)[1].split("\n#", 1)[0], skill)
            trials = _text(skill, "trials.json")
            self.assertNotIn("instead of a stop", trials, skill)

    def test_cloud_copilot_wrappers_match_the_2_2_shape(self) -> None:
        for old, new in (("work-to-chores", "work-to-chores-cloud"), ("do-chores", "do-chores-cloud")):
            self.assertEqual(_text(new, "SKILL.copilot.md"), _text(old, "SKILL.copilot.md"))

    def test_2_2_skills_keep_routing_requires_and_seed_guard(self) -> None:
        for skill, allowed in ALLOWED.items():
            old = (BASELINE / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
            new = _text(skill)
            for line in allowed:
                self.assertIn(line + chr(10), new, f"{skill} lacks {line!r}")
            self.assertIn("Requires: w2c >= 3.3.", new, skill)
            self.assertIn("w2c worktree-seed --check", new, skill)
            self.assertIn("using-git-worktrees", new, skill)
            self.assertIn("w2c worktree-add", new, skill)
            self.assertIn("Requires: w2c >= 2.2.0", old, skill)

    def test_trials_pass_for_all_four_skills(self) -> None:
        self.assertEqual(
            SKILL_NAMES, ("work-to-chores", "do-chores", "work-to-chores-cloud", "do-chores-cloud")
        )
        rows, code = run_trials()
        self.assertEqual(code, 0, rows)
        self.assertEqual([(skill, status) for skill, status, _ in rows],
                         [(skill, "PASS") for skill in SKILL_NAMES])


TEMPLATE = (REPO / "templates" / "cloud" / "design-delivery.md").read_text(encoding="utf-8")


def _template_rows() -> dict[str, str]:
    rows = {}
    for line in TEMPLATE.split("## Guardrails")[0].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| ") and len(cells) == 2 and cells[0] not in ("Field", "---"):
            rows[cells[0]] = cells[1]
    return rows


def _conventions_as_the_skill_says(design: str) -> str:
    """Fill `## Commit and PR Conventions` exactly as work-to-chores-cloud instructs."""
    head, rest = design.split("## Commit and PR Conventions", 1)
    body, tail = rest.split("\n## Decisions", 1)
    out = []
    planner_lines = 0
    for line in body.splitlines():
        if line.startswith("Planner:"):
            planner_lines += 1
            if planner_lines == 1:
                continue  # delete the first Planner: line
            out.append("Never stage: local planner files, `.env*`, `.idea/`")
            continue
        for label, value in (("**Commit title:**", "Short imperative subject."),
                             ("**Commit body:**", "Optional, after a blank line."),
                             ("**Pull request:**", "One per change, with a test plan.")):
            if line == label:
                line = f"{label} {value}"
        out.append(line)
    return head + "## Commit and PR Conventions" + "\n".join(out) + "\n\n## Decisions" + tail


class CloudPlanRulesTests(unittest.TestCase):
    def test_new_writes_design_and_tasks_and_templates_are_named(self) -> None:
        text = _text("work-to-chores-cloud")
        self.assertIn("writes two files, each only when it is absent: `design.md`", text)
        self.assertIn("`tasks.md` (starting with the read-first block). It writes nothing else.", text)
        self.assertNotIn("from the cloud templates with", text)
        self.assertNotIn("keeps exactly these six sections", text)
        self.assertIn("must contain these six required sections", text)
        self.assertIn("after `## Amendments`. Never remove or rename the six", text)
        self.assertIn("append the output of `w2c cloud template slice-group`", text)
        self.assertNotIn("templates/cloud/", text)
        for name in ("task-summary", "slice-uat", "slice-summary", "validation", "summary"):
            self.assertIn(name, text)
            self.assertIn(f"w2c cloud template {name}", _text("do-chores-cloud"))
        self.assertIn("`## Guardrails` — the template's guardrails, verbatim", text)
        self.assertIn("the template text verbatim, with only the placeholders filled", text)

    def test_conventions_built_as_instructed_pass_validation(self) -> None:
        from w2c.cloud import checks

        text = _text("work-to-chores-cloud")
        for phrase in ("Keep every line of the section that does not start with `Planner:` exactly as written",
                       "Delete the first `Planner:` line",
                       "with one line: `Never stage: local planner files, `",
                       "Put the value on the same line after **Commit title:**, **Commit body:**, and "
                       "**Pull request:**"):
            self.assertIn(phrase, text)
        sentence = next(line for line in TEMPLATE.splitlines() if "is product content" in line)
        self.assertIn(f'"{sentence}"', text)
        self.assertEqual(checks.validate_conventions(TEMPLATE.replace("`openspec/` is product content", "x")),
                         ["conventions must say openspec/ is product content and is never deny-listed"])
        built = _conventions_as_the_skill_says(TEMPLATE)
        self.assertEqual(checks.validate_conventions(built), [])
        section = built.split("## Commit and PR Conventions", 1)[1].split("## Decisions", 1)[0]
        self.assertNotIn("w2c", section.lower())
        self.assertNotIn("Planner:", section)

    def test_do_not_stage_never_writes_w2c_into_committed_text(self) -> None:
        text = _text("work-to-chores-cloud")
        start = text.index("### Commit and PR conventions")
        block = text[start:text.index("### Manual test guide")]
        self.assertIn("never write `.w2c/` or the word \"w2c\" into committed text", block)
        self.assertNotIn("deny-list: local planner files, `.w2c/`", text)
        for skill in ("work-to-chores-cloud", "do-chores-cloud"):
            self.assertIn("Committed change files", _text(skill), skill)
            self.assertIn("and the `.delivery/` reports must never contain the word \"w2c\"", _text(skill), skill)

    def test_worktree_layout_exclude_and_delivery_plan_values(self) -> None:
        text = _text("work-to-chores-cloud")
        for phrase in ("Write `Worktree layout` and `Worktree dir` from that output",
                       "If `exclude` is `missing`, ask once whether to add the worktree directory",
                       "Record `exclude-yes`, `exclude-no`, or `already-set` with `w2c cloud decide`",
                       "A bare container prints `exclude: n/a`; do not ask.",
                       "| Worktree skill | `using-git-worktrees` if mode is `worktree`; `n/a` if `branch` |"):
            self.assertIn(phrase, text)
        table = text[text.index("### Delivery Plan values"):text.index("### Commit and PR conventions")]
        rows = {}
        for line in table.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if line.startswith("| ") and len(cells) == 2 and cells[0] not in ("Field", "---"):
                rows[cells[0]] = cells[1]
        template = _template_rows()
        self.assertNotIn("Plan commit", rows)
        self.assertTrue(set(rows) <= set(template), set(rows) - set(template))
        for field in ("Isolation mode", "Local branch", "Remote branch", "Isolation scope", "Setup when",
                      "Reuse policy", "Worktree skill", "Worktree layout", "Worktree dir", "Exclude line",
                      "Push rule", "Base dirt policy"):
            self.assertIn(field, rows)
        self.assertEqual(rows["Push rule"], template["Push rule"])
        self.assertEqual(rows["Setup when"], f"`{template['Setup when']}`")
        self.assertEqual(rows["Isolation scope"], f"`{template['Isolation scope']}`")

    def test_delivery_profile_sources_integration_rows(self) -> None:
        text = _text("work-to-chores-cloud")
        block = text[text.index("### Delivery profile"):text.index("### Delivery Plan values")]
        for phrase in ("read `.w2c/DELIVERY-PROFILE.md` if present",
                       "Copy **Integration strategy** and **Integration branch (day-to-day)**",
                       "(and **Production branch** when the strategy is `gitflow`)",
                       "Do **not** stop."):
            self.assertIn(phrase, block)

    def test_cloud_skills_name_the_closing_asks(self) -> None:
        do = _text("do-chores-cloud")
        for phrase in ("reason `pre-archive`", "reason `post-archive`", "push-blocked-until-archive",
                       "except the last slice's", "There is no `ask-push` and no `ask-pr`",
                       "REPORTS_UNCOMMITTED", "--keep-reports-backup", "REPORTS_KEPT <path>",
                       "Go back and commit the reports", "Archive anyway with a backup"):
            self.assertIn(phrase, do)
        plan = _text("work-to-chores-cloud")
        self.assertIn("except the last one", plan)
        self.assertIn("When the archive is declined, the change is committed but not pushed", plan)


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
