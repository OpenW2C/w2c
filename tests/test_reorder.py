#!/usr/bin/env python3
"""Reorder pending milestones without renumbering ids."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

_TEST_HOME = Path(tempfile.mkdtemp(prefix="w2c-reorder-"))
os.environ["W2C_CONFIG"] = str(_TEST_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_TEST_HOME / "data")

from w2c import cli as w2c  # noqa: E402


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def slice_plan(mid: str) -> str:
    return f"""---
MILESTONE ID: {mid}
SLICE ID: S01
---

# S01: Foundation

<tasks>
- [ ] **T01**: First task.
  - Verify: python3 -c 'print(1)'
</tasks>
"""


def milestone_roadmap(mid: str) -> str:
    return f"""# {mid}: demo

## Slices

- [ ] **S01: Foundation** `risk:low` `depends:[]`
"""


class ReorderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="w2c-reorder-test-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        w2c.cmd_init(
            self.tmp,
            git_delivery="slice-commit-milestone-push-pr",
            planning="classic",
        )

    def _ids(self) -> list[str]:
        road = (self.tmp / ".w2c/ROADMAP.md").read_text(encoding="utf-8")
        return [m.mid for m in w2c.parse_milestones(road)]

    def _set_status(self, mid: str, status: str) -> None:
        road = self.tmp / ".w2c/ROADMAP.md"
        lines = []
        for line in road.read_text(encoding="utf-8").splitlines(keepends=True):
            parsed = w2c.parse_milestones(line)
            if parsed and parsed[0].mid == mid:
                line = line.replace(parsed[0].emoji, w2c.STATUS_EMOJI[status], 1)
            lines.append(line)
        road.write_text("".join(lines), encoding="utf-8")

    def _seed_three(self) -> None:
        for slug in ("ten", "eleven", "twelve"):
            w2c.cmd_milestone_new(self.tmp, slug)
        for mid, slug in (("M002", "eleven"), ("M003", "twelve")):
            d = self.tmp / ".w2c/plans" / f"{mid}-{slug}"
            write(d / f"{mid}-ROADMAP.md", milestone_roadmap(mid))
            write(d / f"{mid}-S01-PLAN.md", slice_plan(mid))
        self._set_status("M001", "INPROGRESS")
        w2c.rebuild_ledger(self.tmp)

    def _active(self) -> str:
        state = (self.tmp / ".w2c/STATE.md").read_text(encoding="utf-8")
        return w2c.parse_state_field(state, "Active Milestone")

    def test_move_before_reorders_queue_and_next_without_renumbering(self) -> None:
        self._seed_three()
        active = self._active()
        dirs_before = sorted(p.name for p in (self.tmp / ".w2c/plans").iterdir())
        nxt = w2c.next_open_task(self.tmp)
        assert nxt is not None
        self.assertEqual(nxt.mid, "M002")

        self.assertEqual(w2c.cmd_milestone_move(self.tmp, "M003", "M002", None), 0)
        self.assertEqual(self._ids(), ["M001", "M003", "M002"])
        queue = (self.tmp / ".w2c/QUEUE.md").read_text(encoding="utf-8")
        self.assertLess(queue.index("M003"), queue.index("M002"))
        nxt = w2c.next_open_task(self.tmp)
        assert nxt is not None
        self.assertEqual((nxt.mid, nxt.sid, nxt.tid), ("M003", "S01", "T01"))
        self.assertEqual(w2c.next_milestone_id(self.tmp), "M004")
        self.assertEqual(sorted(p.name for p in (self.tmp / ".w2c/plans").iterdir()), dirs_before)
        self.assertEqual(self._active(), active)
        recs = w2c.read_events(self.tmp)
        self.assertEqual(recs[-1]["stage"], "reorder")
        self.assertIn("move M003 before M002", recs[-1]["detail"])

        self.assertEqual(w2c.cmd_milestone_swap(self.tmp, "m003", "M002"), 0)
        self.assertEqual(self._ids(), ["M001", "M002", "M003"])

    def test_move_after_inprogress_stays_behind_it(self) -> None:
        self._seed_three()
        self.assertEqual(w2c.cmd_milestone_move(self.tmp, "M003", None, "M001"), 0)
        self.assertEqual(self._ids(), ["M001", "M003", "M002"])

    def test_relative_order_keeps_unnamed_milestones(self) -> None:
        self._seed_three()
        w2c.cmd_milestone_new(self.tmp, "thirteen")
        self._set_status("M001", "INPROGRESS")
        self.assertEqual(w2c.cmd_milestone_order(self.tmp, ["M004", "M002"]), 0)
        self.assertEqual(self._ids(), ["M001", "M004", "M003", "M002"])

    def test_refuse_taking_inprogress_or_done_place(self) -> None:
        self._seed_three()
        with self.assertRaises(w2c.W2CError):
            w2c.cmd_milestone_swap(self.tmp, "M003", "M001")
        with self.assertRaises(w2c.W2CError):
            w2c.cmd_milestone_move(self.tmp, "M003", "M001", None)
        with self.assertRaises(w2c.W2CError):
            w2c.cmd_milestone_order(self.tmp, ["M003", "M001"])
        with self.assertRaises(w2c.W2CError):
            w2c.cmd_milestone_swap(self.tmp, "M003", "M099")
        with self.assertRaises(w2c.W2CError):
            w2c.cmd_milestone_swap(self.tmp, "M002", "M002")
        self.assertEqual(self._ids(), ["M001", "M002", "M003"])

        self._set_status("M001", "DONE")
        with self.assertRaises(w2c.W2CError):
            w2c.cmd_milestone_move(self.tmp, "M003", "M001", None)
        self.assertEqual(self._ids(), ["M001", "M002", "M003"])

        # Paused milestone sits before an in-progress one. A later pending
        # milestone may not swap into that earlier place.
        self._set_status("M001", "PAUSED")
        self._set_status("M002", "INPROGRESS")
        with self.assertRaises(w2c.W2CError):
            w2c.cmd_milestone_swap(self.tmp, "M003", "M001")
        self.assertEqual(self._ids(), ["M001", "M002", "M003"])

    def test_allow_taking_paused_stop_or_error_place(self) -> None:
        for status in ("PAUSED", "STOP", "ERROR"):
            with self.subTest(status=status):
                shutil.rmtree(self.tmp / ".w2c", ignore_errors=True)
                w2c.cmd_init(
            self.tmp,
            git_delivery="slice-commit-milestone-push-pr",
            planning="classic",
        )
                w2c.cmd_milestone_new(self.tmp, "held")
                w2c.cmd_milestone_new(self.tmp, "pending")
                self._set_status("M001", status)
                self.assertEqual(w2c.cmd_milestone_swap(self.tmp, "M002", "M001"), 0)
                self.assertEqual(self._ids(), ["M002", "M001"])
                self.assertEqual(w2c.cmd_milestone_move(self.tmp, "M001", "M002", None), 0)
                self.assertEqual(self._ids(), ["M001", "M002"])

    def test_cli_move_before(self) -> None:
        self._seed_three()
        rc = w2c.main(
            ["--root", str(self.tmp), "milestone-move", "M003", "--before", "M002"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(self._ids(), ["M001", "M003", "M002"])
        rc_bad = w2c.main(
            ["--root", str(self.tmp), "milestone-move", "M003", "--before", "M001"]
        )
        self.assertEqual(rc_bad, 1)
        self.assertEqual(self._ids(), ["M001", "M003", "M002"])

    def test_smoke_fails_when_queue_order_drifts(self) -> None:
        self._seed_three()
        report = w2c.run_smoke(self.tmp)
        names = {c.name: c for c in report.checks}
        self.assertEqual(names["queue-order-matches-roadmap"].status, "PASS")

        queue = self.tmp / ".w2c/QUEUE.md"
        lines = queue.read_text(encoding="utf-8").splitlines(keepends=True)
        milestone_lines = [i for i, line in enumerate(lines) if line.startswith("- ")]
        self.assertGreaterEqual(len(milestone_lines), 2)
        a, b = milestone_lines[0], milestone_lines[1]
        lines[a], lines[b] = lines[b], lines[a]
        queue.write_text("".join(lines), encoding="utf-8")
        report = w2c.run_smoke(self.tmp)
        names = {c.name: c for c in report.checks}
        self.assertEqual(names["queue-order-matches-roadmap"].status, "FAIL")
        self.assertTrue(report.failed())


if __name__ == "__main__":
    unittest.main()
