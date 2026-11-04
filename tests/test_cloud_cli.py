#!/usr/bin/env python3
"""The w2c cloud command group and temporary-container detection."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

_HOME = Path(tempfile.mkdtemp(prefix="w2c-cloud-cli-home-"))
os.environ["W2C_CONFIG"] = str(_HOME / "config.toml")
os.environ["W2C_DATA_HOME"] = str(_HOME / "data")

from w2c import cli as w2c  # noqa: E402
from w2c.cloud import cli as cloud_cli  # noqa: E402
from w2c.cloud import environment  # noqa: E402


def run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = w2c.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


class EphemeralTests(unittest.TestCase):
    def test_each_variable_marks_ephemeral(self) -> None:
        for name in ("CLAUDE_CODE_REMOTE", "CODESPACES", "GITHUB_ACTIONS"):
            self.assertEqual(environment.ephemeral_reason({name: "true"}), name)
        self.assertEqual(
            environment.ephemeral_reason({"CODESPACES": "1", "GITHUB_ACTIONS": "1"}),
            "CODESPACES",
        )
        self.assertIsNone(environment.ephemeral_reason({}))

    def test_false_values_are_ignored(self) -> None:
        for value in ("", "0", "false", "FALSE"):
            self.assertIsNone(environment.ephemeral_reason({"CODESPACES": value}))

    def test_override_wins_both_ways(self) -> None:
        self.assertEqual(
            environment.ephemeral_reason({"W2C_EPHEMERAL": "1"}), "W2C_EPHEMERAL"
        )
        self.assertEqual(
            environment.ephemeral_reason({"W2C_EPHEMERAL": "true"}), "W2C_EPHEMERAL"
        )
        self.assertIsNone(
            environment.ephemeral_reason({"W2C_EPHEMERAL": "0", "CODESPACES": "1"})
        )
        self.assertIsNone(
            environment.ephemeral_reason({"W2C_EPHEMERAL": "false", "CODESPACES": "1"})
        )

    def test_agent_name_override_and_detection(self) -> None:
        name = environment.agent_name
        self.assertEqual(name({"W2C_AGENT": "cursor"}), "cursor")
        self.assertEqual(name({"W2C_AGENT": "cursr", "CLAUDECODE": "1"}), "claude-code")
        self.assertEqual(name({"CLAUDECODE": "0"}), "unknown")
        self.assertEqual(name({"CLAUDECODE": ""}), "unknown")
        self.assertEqual(name({"CLAUDE_CODE_REMOTE": "true"}), "claude-code")
        self.assertEqual(name({"CLAUDECODE": "1", "GITHUB_ACTIONS": "true"}), "claude-code")
        self.assertEqual(name({"GITHUB_ACTIONS": "true"}), "copilot")
        self.assertEqual(name({}), "unknown")

    def test_cmd_env_prints_three_lines(self) -> None:
        def run(env: dict[str, str]) -> str:
            old = dict(os.environ)
            os.environ.clear()
            os.environ.update(env)
            try:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(environment.cmd_env(), 0)
            finally:
                os.environ.clear()
                os.environ.update(old)
            return out.getvalue()

        self.assertEqual(run({"W2C_EPHEMERAL": "1", "W2C_AGENT": "codex"}),
                         "ephemeral: true\nreason: W2C_EPHEMERAL\nagent: codex\n")
        self.assertEqual(run({"W2C_EPHEMERAL": "0"}), "ephemeral: false\nreason: none\nagent: unknown\n")


class CloudGroupTests(unittest.TestCase):
    def test_cloud_group_needs_a_subcommand(self) -> None:
        code, _, _ = run_main(["cloud"])
        self.assertNotEqual(code, 0)
        self.assertTrue(callable(cloud_cli.register))

    def test_init_accepts_cloud_planning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            code, _, err = run_main(
                ["--root", str(root), "init", "--planning", "cloud",
                 "--git-delivery", "slice-commit-milestone-push-pr"]
            )
            self.assertEqual(code, 0, err)
            from w2c import local

            self.assertEqual(local.load_repo_config(root)["planning"], "cloud")

    def test_legacy_milestone_new_refuses_cloud_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            run_main(["--root", str(root), "init", "--planning", "cloud",
                      "--git-delivery", "slice-commit-milestone-push-pr"])
            code, _, err = run_main(["--root", str(root), "milestone-new", "--slug", "x"])
            self.assertEqual(code, 1)
            self.assertIn("use w2c cloud new", err)


if __name__ == "__main__":
    unittest.main()
