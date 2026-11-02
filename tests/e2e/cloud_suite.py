"""Stages that run the opt-in cloud mode on a dummy project.

Stored outputs live under tests/e2e/expected/cloud/. Later tasks add stages here.
"""

from __future__ import annotations

import subprocess

from tests.e2e.harness import Project, Stage


def c01_env(p: Project) -> None:
    proc = p.w2c("init", "--planning", "cloud", "--git-delivery", "slice-commit-milestone-push-pr")
    p.expect_tokens(proc, "initialized .w2c/")
    p.expect_tokens(p.read(".w2c/config.toml"), 'planning = "cloud"')
    env = dict(p.env)
    env["W2C_EPHEMERAL"] = "1"
    proc = subprocess.run(
        [str(p.home / ".local" / "bin" / "w2c"), "cloud", "env"],
        cwd=str(p.root), env=env, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(f"w2c cloud env failed\n{proc.stdout}{proc.stderr}")
    p.expect_tokens(proc, "ephemeral: true", "reason: W2C_EPHEMERAL")
    p.expect_matches("C01-env.txt", proc.stdout)


STAGES = [
    Stage("C01", "cloud planning init and env", c01_env),
]
