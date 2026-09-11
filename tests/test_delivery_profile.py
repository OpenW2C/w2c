#!/usr/bin/env python3
"""DELIVERY-PROFILE compose helper and M-ROADMAP integration-strategy default."""

from __future__ import annotations

import unittest
from pathlib import Path

from w2c.delivery_profile import (
    DEFAULT_CI_PATH,
    compose_delivery_profile,
)

CHECKOUT = Path(__file__).resolve().parents[1]
CHECKOUT_TEMPLATES = CHECKOUT / "templates"


class DeliveryProfileComposeTest(unittest.TestCase):
    def test_neither_omits_gitflow_and_ci(self) -> None:
        text = compose_delivery_profile(strategy="trunk-direct", ci_pointers=False)
        self.assertIn("| Integration strategy | `trunk-direct` |", text)
        self.assertNotIn("## Gitflow (release train)", text)
        self.assertNotIn("CI/CD spec (portable)", text)
        self.assertNotIn("## CI/CD pointers", text)
        self.assertIn("git_delivery", text)

    def test_gitflow_only(self) -> None:
        text = compose_delivery_profile(strategy="gitflow", ci_pointers=False)
        self.assertIn("| Integration strategy | `gitflow` |", text)
        self.assertIn("| Integration branch (day-to-day) | `develop` |", text)
        self.assertIn("| Production branch | `main` |", text)
        self.assertIn("## Gitflow (release train)", text)
        self.assertIn("back-merge", text.lower())
        self.assertNotIn("CI/CD spec (portable)", text)
        self.assertNotIn("## CI/CD pointers", text)

    def test_ci_only(self) -> None:
        text = compose_delivery_profile(strategy="feature-branch", ci_pointers=True)
        self.assertIn("| Integration strategy | `feature-branch` |", text)
        self.assertNotIn("## Gitflow (release train)", text)
        self.assertIn(f"| CI/CD spec (portable) | `{DEFAULT_CI_PATH}` |", text)
        self.assertIn("## CI/CD pointers", text)

    def test_both_gitflow_and_ci_custom_path(self) -> None:
        text = compose_delivery_profile(
            strategy="gitflow",
            ci_pointers=True,
            ci_path="docs/ci/",
            project_title="demo-app",
        )
        self.assertIn("Project Delivery Profile — demo-app", text)
        self.assertIn("## Gitflow (release train)", text)
        self.assertIn("| CI/CD spec (portable) | `docs/ci/` |", text)
        self.assertIn("## CI/CD pointers", text)

    def test_invalid_strategy_raises(self) -> None:
        with self.assertRaises(ValueError):
            compose_delivery_profile(strategy="rebase-onto-main", ci_pointers=False)  # type: ignore[arg-type]


class DeliveryProfileTemplateTest(unittest.TestCase):
    def test_shipped_template_exists_with_compose_rules(self) -> None:
        path = CHECKOUT_TEMPLATES / "DELIVERY-PROFILE.md"
        self.assertTrue(path.is_file(), f"missing {path}")
        text = path.read_text(encoding="utf-8")
        self.assertIn("Compose rules", text)
        self.assertIn("gitflow", text)
        self.assertIn("CI/CD", text)
        self.assertIn("git_delivery", text)

    def test_m_roadmap_does_not_hardcode_trunk_direct(self) -> None:
        roadmap = (CHECKOUT_TEMPLATES / "M-ROADMAP.md").read_text(encoding="utf-8")
        self.assertNotIn("| Integration strategy | trunk-direct |", roadmap)
        self.assertIn(
            "| Integration strategy | (from .w2c/DELIVERY-PROFILE.md) |",
            roadmap,
        )
        cli = (CHECKOUT / "src" / "w2c" / "cli.py").read_text(encoding="utf-8")
        self.assertNotIn("| Integration strategy | trunk-direct |", cli)
        self.assertIn(
            "| Integration strategy | (from .w2c/DELIVERY-PROFILE.md) |",
            cli,
        )


if __name__ == "__main__":
    unittest.main()
