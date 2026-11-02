#!/usr/bin/env python3
"""Cloud mode layout constants and neutral templates."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-cloud-tpl-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from w2c.cloud import layout  # noqa: E402

TPL = ROOT / "templates"
CLOUD = TPL / "cloud"
PLANNING_COMMIT = "bee6a3c"


def section(text: str, heading: str, level: str) -> str:
    """Body under `heading` up to the next heading of the same or higher level."""
    m = re.search(rf"^{re.escape(heading)}\s*$", text, re.M)
    assert m, heading
    rest = text[m.end():]
    n = re.search(rf"^#{{1,{len(level)}}} ", rest, re.M)
    return rest[: n.start()] if n else rest


def table_rows(body: str) -> list[str]:
    rows = []
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] not in ("Field", "---") and not set(cells[0]) <= {"-"}:
            rows.append(cells[0])
    return rows


class CloudTemplateTests(unittest.TestCase):
    def test_cloud_templates_never_name_the_tool(self) -> None:
        files = [p for p in CLOUD.rglob("*") if p.is_file()]
        self.assertGreaterEqual(len(files), 8)
        for p in files:
            self.assertNotIn("w2c", p.read_text(encoding="utf-8").lower(), str(p))
        for text in (layout.CONFIG_RULES_SNIPPET, layout.STOP_SENTENCE):
            self.assertNotIn("w2c", text.lower())

    def test_design_headings_in_order(self) -> None:
        text = (CLOUD / "design-delivery.md").read_text(encoding="utf-8")
        found = re.findall(r"^## .*$", text, re.M)
        self.assertEqual(found, list(layout.DESIGN_HEADINGS))

    def test_guardrail_parity_with_legacy_roadmap(self) -> None:
        legacy = (TPL / "openspec" / "M-ROADMAP.md").read_text(encoding="utf-8")
        labels = re.findall(r"^- \*\*(.+?)\*\*", section(legacy, "### Guardrails", "###"), re.M)
        self.assertGreater(len(labels), 5)
        new = section((CLOUD / "design-delivery.md").read_text(encoding="utf-8"), "## Guardrails", "##")
        new_labels = re.findall(r"^- \*\*(.+?)\*\*", new, re.M)
        for label in labels:
            if label in layout.LEGACY_DROPPED_GUARDRAILS:
                self.assertTrue(layout.LEGACY_DROPPED_GUARDRAILS[label])
                self.assertNotIn(label, new_labels)
            else:
                self.assertIn(label, new_labels)

    def test_commit_conventions_keep_legacy_parts(self) -> None:
        new = section((CLOUD / "design-delivery.md").read_text(encoding="utf-8"), "## Commit and PR Conventions", "##")
        for part in ("Commit title", "Commit body", "Pull request", "Do not stage / commit",
                     "Do not mention", "AI attribution — forbidden"):
            self.assertIn(f"**{part}:**", new)
        self.assertIn("`openspec/` is product content and is never deny-listed.", new)
        self.assertIn("`Co-authored-by:`", new)
        self.assertIn(".delivery/", new)
        self.assertIn("local planner files", new)

    def test_field_parity_with_legacy_tables(self) -> None:
        legacy = (TPL / "openspec" / "M-ROADMAP.md").read_text(encoding="utf-8")
        legacy_rows = table_rows(section(legacy, "## Delivery & Guardrails", "##"))
        legacy_rows += table_rows(section(legacy, "## Git Operation Plan", "##"))
        self.assertGreater(len(legacy_rows), 20)
        new_rows = table_rows(section((CLOUD / "design-delivery.md").read_text(encoding="utf-8"), "## Delivery Plan", "##"))
        self.assertEqual(new_rows, list(layout.DELIVERY_PLAN_FIELDS))
        self.assertEqual(sorted(layout.LEGACY_DROPPED_FIELDS), sorted([
            "Milestone / planning ID", "Human-readable scope slug", "Planning mode", "OpenSpec change",
            "OpenSpec archive", "Workstream name", "Commit cadence", "Review unit",
            "Git/PR checkpoint mode", "Branch name", "Plan commit"]))
        for row in legacy_rows:
            if row in new_rows:
                continue
            self.assertTrue(layout.LEGACY_DROPPED_FIELDS.get(row), row)

    def test_slice_field_parity(self) -> None:
        legacy = (TPL / "openspec" / "M-S-PLAN.md").read_text(encoding="utf-8")
        headings = re.findall(r"^## (.+)$", legacy, re.M)
        start, end = headings.index("Must-Haves"), headings.index("Files Likely Touched")
        wanted = headings[start : end + 1] + ["Goal", "Demo"]
        for name in wanted:
            self.assertIn(name, layout.SLICE_FIELDS)
        group = (CLOUD / "slice-group.md").read_text(encoding="utf-8")
        for name in layout.SLICE_FIELDS:
            self.assertIn(f"**{name}:**", group)

    def test_every_cloud_rule_is_conditional(self) -> None:
        snippet = layout.CONFIG_RULES_SNIPPET
        items = [l.strip()[2:].strip('"') for l in snippet.splitlines() if l.strip().startswith("- ")]
        self.assertGreaterEqual(len(items), 4)
        for item in items:
            self.assertTrue(item.startswith(layout.RULE_PREFIX), item)
        self.assertIn(layout.STOP_SENTENCE, snippet)
        self.assertIn("openspec/knowledge.md", snippet)
        for marker in (layout.SLICE_TASK_MARKER, layout.DESIGN_MARKER, layout.READ_FIRST_MARKER):
            self.assertIn(marker, snippet)

    def test_report_templates_exist(self) -> None:
        for name in ("TASK-SUMMARY", "SLICE-UAT", "SLICE-SUMMARY", "VALIDATION", "SUMMARY"):
            self.assertTrue((CLOUD / "reports" / f"{name}.md").is_file(), name)
        self.assertEqual(layout.REPORT_DIR, ".delivery")

    def test_legacy_templates_unchanged(self) -> None:
        paths = sorted(p.relative_to(ROOT).as_posix()
                       for p in list((TPL / "openspec").glob("*")) + list(TPL.glob("*.md")))
        self.assertGreaterEqual(len(paths), 16)
        for rel in paths:
            old = subprocess.run(["git", "show", f"{PLANNING_COMMIT}:{rel}"], cwd=ROOT,
                                 capture_output=True, check=True).stdout
            self.assertEqual((ROOT / rel).read_bytes(), old, rel)


if __name__ == "__main__":
    unittest.main()
