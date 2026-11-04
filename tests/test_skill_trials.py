#!/usr/bin/env python3
"""Shape checks for skill trials. No model call."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-trials-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from w2c import trials as w2c_trials  # noqa: E402
from w2c.trials import check_trials, cmd_trials, load_trials, locate_trials, shared_group_problems  # noqa: E402


def _valid(skill: str) -> dict:
    path = locate_trials(skill)
    assert path is not None
    data = load_trials(path)
    assert isinstance(data, dict)
    return data


def _problems(skill: str, mutate) -> list[str]:
    data = copy.deepcopy(_valid(skill))
    mutate(data)
    return check_trials(data, skill)


class SkillTrialTests(unittest.TestCase):
    def test_shipped_trials_pass(self) -> None:
        self.assertEqual(cmd_trials(), 0)

    def test_skill_field_must_match_directory(self) -> None:
        problems = _problems("work-to-chores", lambda data: data.__setitem__("skill", "other"))
        self.assertTrue(any("skill field" in item for item in problems))

    def test_missing_group_fails(self) -> None:
        def drop(data: dict) -> None:
            data["trials"] = [
                trial
                for trial in data["trials"]
                if not (trial["mode"] == "openspec" and trial["group"] == "isolation")
            ]

        problems = _problems("work-to-chores", drop)
        self.assertTrue(any("missing openspec group isolation" in item for item in problems))

    def test_unknown_group_fails(self) -> None:
        problems = _problems(
            "do-chores",
            lambda data: data["trials"][0].__setitem__("group", "nope"),
        )
        self.assertTrue(any("unknown group" in item for item in problems))

    def test_exclusive_group_on_wrong_mode_fails(self) -> None:
        def move(data: dict) -> None:
            for trial in data["trials"]:
                if trial["group"] == "install-ask":
                    trial["mode"] = "classic"

        problems = _problems("work-to-chores", move)
        self.assertTrue(any("only for mode openspec" in item for item in problems))

    def test_each_mode_needs_a_hostile_trial(self) -> None:
        def calm(data: dict) -> None:
            for trial in data["trials"]:
                if trial["mode"] == "classic":
                    trial["kind"] = "ordinary"

        problems = _problems("do-chores", calm)
        self.assertTrue(any("no hostile trial for mode classic" in item for item in problems))

    def test_id_shape_and_duplicates(self) -> None:
        bad_id = _problems(
            "work-to-chores",
            lambda data: data["trials"][0].__setitem__("id", "R1"),
        )
        self.assertTrue(any("id must look like R01" in item for item in bad_id))
        duplicate = _problems(
            "work-to-chores",
            lambda data: data["trials"][1].__setitem__("id", data["trials"][0]["id"]),
        )
        self.assertTrue(any("duplicate id" in item for item in duplicate))

    def test_legacy_ask_must_be_classic_interview(self) -> None:
        wrong_mode = _problems(
            "work-to-chores",
            lambda data: data["trials"][0].__setitem__("ask", "please use legacy mode"),
        )
        self.assertTrue(any("legacy must be classic interview" in item for item in wrong_mode))

        def wrong_group(data: dict) -> None:
            for trial in data["trials"]:
                if trial["mode"] == "classic" and trial["group"] == "isolation":
                    trial["ask"] = "use legacy isolation"

        problems = _problems("work-to-chores", wrong_group)
        self.assertTrue(any("legacy must be classic interview" in item for item in problems))

    def test_empty_ask_passes_when_and_must(self) -> None:
        empty_ask = _problems(
            "do-chores",
            lambda data: data["trials"][0].__setitem__("ask", "  "),
        )
        self.assertTrue(any("ask is empty" in item for item in empty_ask))
        empty_passes = _problems(
            "do-chores",
            lambda data: data["trials"][0].__setitem__("passes_when", ""),
        )
        self.assertTrue(any("passes_when is empty" in item for item in empty_passes))
        empty_must = _problems(
            "do-chores",
            lambda data: data["trials"][0].__setitem__("must", ["keeps the openspec branch", " "]),
        )
        self.assertTrue(any("empty must line" in item for item in empty_must))
        short_must = _problems(
            "do-chores",
            lambda data: data["trials"][0].__setitem__("must", ["keeps the openspec branch"]),
        )
        self.assertTrue(any("need at least 2 must lines" in item for item in short_must))

    def test_vague_must_line_fails(self) -> None:
        problems = _problems(
            "do-chores",
            lambda data: data["trials"][0].__setitem__(
                "must",
                ["follows the process", "handles it appropriately"],
            ),
        )
        self.assertTrue(any("vague must line" in item for item in problems))

    def test_broken_temp_file_is_what_the_checker_reads(self) -> None:
        raw = _valid("work-to-chores")
        raw["trials"][0]["id"] = "nope"
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        path = Path(handle.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        json.dump(raw, handle)
        handle.close()
        problems = check_trials(load_trials(path), "work-to-chores")
        self.assertTrue(any("id must look like R01" in item for item in problems))

    def test_shared_groups_exist_for_both_pairs(self) -> None:
        self.assertEqual(shared_group_problems(), [])
        for skill in ("work-to-chores", "do-chores", "work-to-chores-cloud", "do-chores-cloud"):
            for group in w2c_trials.SHARED_GROUPS:
                self.assertIn(group, w2c_trials.GROUPS_BOTH[skill], skill)

    def test_shared_group_missing_from_a_cloud_skill_fails_parity(self) -> None:
        groups = dict(w2c_trials.GROUPS_BOTH)
        groups["do-chores-cloud"] = tuple(g for g in groups["do-chores-cloud"] if g != "base-dirt")
        with unittest.mock.patch.object(w2c_trials, "GROUPS_BOTH", groups):
            problems = shared_group_problems()
            self.assertTrue(any("do-chores-cloud" in item and "base-dirt" in item for item in problems))
            rows, code = w2c_trials.run_trials()
        self.assertEqual(code, 1)
        self.assertTrue(any(status == "FAIL" and "base-dirt" in detail for _, status, detail in rows))

    def test_cloud_groups_are_the_brief_groups(self) -> None:
        shared = w2c_trials.SHARED_GROUPS
        self.assertEqual(
            w2c_trials.GROUPS_BOTH["work-to-chores-cloud"],
            shared + ("interview", "plan-write", "reorder", "amend", "design-sections", "convert",
                      "companion-ask"),
        )
        self.assertEqual(
            w2c_trials.GROUPS_BOTH["do-chores-cloud"],
            shared + ("step-loop", "closeout", "blocker", "ephemeral-push", "read-first", "no-answer", "off-plan",
                      "companion-ask"),
        )
        for token in ("design.md", ".delivery", "ephemeral", "step"):
            self.assertIn(token, w2c_trials.CLOUD_CONCRETE_TOKENS)
            self.assertNotIn(token, w2c_trials.CONCRETE_TOKENS)

    def test_cloud_only_tokens_do_not_rescue_a_vague_2_2_line(self) -> None:
        line = "The agent follows the step conventions correctly."
        self.assertIsNotNone(w2c_trials._vague_problem(line, "do-chores"))
        self.assertIsNotNone(w2c_trials._vague_problem(line, "work-to-chores"))
        self.assertIsNone(w2c_trials._vague_problem(line, "do-chores-cloud"))
        self.assertEqual(w2c_trials.concrete_tokens("do-chores"), w2c_trials.CONCRETE_TOKENS)
        for skill in ("do-chores", "work-to-chores"):
            problems = _problems(skill, lambda data: data["trials"][0]["must"].__setitem__(0, line))
            self.assertTrue(any("vague must line" in item for item in problems), problems)

    def test_cloud_trials_use_openspec_mode_only(self) -> None:
        problems = _problems(
            "do-chores-cloud",
            lambda data: data["trials"][0].__setitem__("mode", "classic"),
        )
        self.assertTrue(any("mode must be openspec" in item for item in problems))

    def test_each_cloud_group_has_an_ordinary_and_a_hostile_row(self) -> None:
        for skill in ("work-to-chores-cloud", "do-chores-cloud"):
            data = _valid(skill)
            for group in w2c_trials.GROUPS_BOTH[skill]:
                kinds = {t["kind"] for t in data["trials"] if t["group"] == group}
                self.assertEqual(kinds, {"ordinary", "hostile"}, f"{skill} {group}")
            calm = _problems(skill, lambda d, g=w2c_trials.GROUPS_BOTH[skill][-1]: [
                t.__setitem__("kind", "ordinary") for t in d["trials"] if t["group"] == g])
            self.assertTrue(any("needs an ordinary and a hostile row" in item for item in calm), calm)


if __name__ == "__main__":
    unittest.main()
