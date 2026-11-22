#!/usr/bin/env python3
"""Accepted-risk register, Threat Surface parsing, and security smoke gates."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-risks-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from w2c import cli as w2c  # noqa: E402
from w2c import local as w2c_local  # noqa: E402
from w2c import risks  # noqa: E402


def run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = w2c.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
        except w2c.W2CError as exc:
            return 1, out.getvalue(), str(exc)
    return code, out.getvalue(), err.getvalue()


THREAT_NONE = """- Security review: none
- Reason: searched auth and input handlers; layout-only change
"""

THREAT_REQUIRED = """- Security review: required
- Reason:
- Threats: F1, src/login.py:12, auth/session, High
- Controls: session cookie HttpOnly (OWASP ASVS V3)
- Security tests: test_rejects_forged_session
- Accepted risks:
"""

THREAT_ACCEPTED = """- Security review: accepted
- Reason:
- Threats: F1, src/api.py:4, network/API, Medium
- Controls:
- Security tests:
- Accepted risks: R001
"""


class ParseThreatSurfaceTests(unittest.TestCase):
    def test_parses_structured_none(self) -> None:
        surface = risks.parse_threat_surface(THREAT_NONE)
        assert surface is not None
        self.assertEqual(surface.security_review, "none")
        self.assertIn("layout-only", surface.reason)

    def test_unstructured_returns_none(self) -> None:
        self.assertIsNone(risks.parse_threat_surface("- None; pure function."))

    def test_html_comment_shape_alone_is_empty(self) -> None:
        self.assertIsNone(
            risks.parse_threat_surface(
                "<!-- Shape: Security review (required|none|accepted); Reason; Threats; "
                "Controls; Security tests; Accepted risks. -->"
            )
        )

    def test_required_problems(self) -> None:
        surface = risks.parse_threat_surface(THREAT_REQUIRED)
        self.assertEqual(
            risks.threat_surface_problems(surface, verify_blob="pytest -k test_rejects_forged_session"),
            [],
        )
        missing = risks.threat_surface_problems(
            risks.parse_threat_surface(
                "- Security review: required\n- Threats:\n- Controls:\n- Security tests:\n"
            )
        )
        self.assertTrue(any("Threats" in p for p in missing))


class RegisterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="w2c-risk-reg-"))
        (self.root / ".w2c").mkdir()
        w2c_local.write_repo_config(
            self.root,
            track=False,
            git_delivery="slice-commit-milestone-push-pr",
            security_risk_register="local",
        )

    def test_accept_and_follow_up(self) -> None:
        risk_id = risks.accept_risk(
            self.root,
            scope="M001",
            slice_id="S01",
            finding="deep link opens without auth",
            evidence="app/DeepLink.kt:40",
            severity="High",
            reason="shipping layout first; ticket next sprint",
        )
        self.assertEqual(risk_id, "R001")
        entries = risks.list_entries(self.root)
        self.assertEqual(len(entries), 1)
        risks.follow_up_risk(self.root, "R001", "https://example.test/T-1")
        self.assertEqual(risks.list_entries(self.root)[0].ticket, "https://example.test/T-1")

    def test_cli_risk_accept_list(self) -> None:
        os.chdir(self.root)
        code, out, err = run_main(
            [
                "risk-accept",
                "--scope",
                "M001",
                "--slice",
                "S01",
                "--finding",
                "secret in log",
                "--evidence",
                "src/log.py:9",
                "--severity",
                "Critical",
                "--reason",
                "accepted until scrub lands",
            ]
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "R001")
        code, out, err = run_main(["risk-list"])
        self.assertEqual(code, 0, err)
        self.assertIn("R001", out)

    def test_committed_path_required(self) -> None:
        with self.assertRaises(w2c_local.LocalError):
            w2c_local.assert_security_risk_register_invariants("committed", "")


class HelpSecurityTests(unittest.TestCase):
    def test_help_security_prints_doc(self) -> None:
        code, out, err = run_main(["help", "security"])
        self.assertEqual(code, 0, err)
        self.assertIn("Evidence or nothing", out)
        self.assertIn("Trigger list", out)


class SecurityReviewResultTests(unittest.TestCase):
    def test_none_requires_na(self) -> None:
        surface = risks.parse_threat_surface(THREAT_NONE)
        self.assertEqual(
            risks.security_review_result_ok({"security_review": "n/a"}, surface),
            [],
        )
        self.assertTrue(
            risks.security_review_result_ok({"security_review": "pass"}, surface)
        )

    def test_required_needs_pass(self) -> None:
        surface = risks.parse_threat_surface(THREAT_REQUIRED)
        self.assertEqual(
            risks.security_review_result_ok({"security_review": "pass"}, surface),
            [],
        )
        self.assertTrue(
            risks.security_review_result_ok({"security_review": "n/a"}, surface)
        )


class DriverSecurityStageTests(unittest.TestCase):
    def test_task_stages_include_security_review(self) -> None:
        from w2c.cloud.driver import TASK_STAGES

        self.assertIn("security-review", TASK_STAGES)
        self.assertEqual(
            TASK_STAGES.index("security-review"),
            TASK_STAGES.index("review") + 1,
        )


if __name__ == "__main__":
    unittest.main()
