"""Detect a temporary container, where only pushed work survives, and the agent in use."""

from __future__ import annotations

import os
from typing import Mapping

OVERRIDE = "W2C_EPHEMERAL"
VARIABLES = ("CLAUDE_CODE_REMOTE", "CODESPACES", "GITHUB_ACTIONS")

AGENT_OVERRIDE = "W2C_AGENT"
AGENTS = ("claude-code", "copilot", "cursor", "codex", "unknown")
# Checked in order: Claude Code can itself run inside GitHub Actions.
AGENT_VARIABLES = (
    ("CLAUDECODE", "claude-code"),
    ("CLAUDE_CODE_REMOTE", "claude-code"),
    ("GITHUB_ACTIONS", "copilot"),
)


def _is_set(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() not in ("", "0", "false")


def ephemeral_reason(env: Mapping[str, str] | None = None) -> str | None:
    """Name the variable that marks a temporary container, or None."""
    env = os.environ if env is None else env
    override = env.get(OVERRIDE, "").strip().lower()
    if override in ("1", "true"):
        return OVERRIDE
    if override in ("0", "false"):
        return None
    for name in VARIABLES:
        if _is_set(env, name):
            return name
    return None


def agent_name(env: Mapping[str, str] | None = None) -> str:
    """One of AGENTS. W2C_AGENT wins when it names one; any other value is ignored."""
    env = os.environ if env is None else env
    override = env.get(AGENT_OVERRIDE, "").strip().lower()
    if override in AGENTS:
        return override
    for name, agent in AGENT_VARIABLES:
        if _is_set(env, name):
            return agent
    return "unknown"


def cmd_env() -> int:
    reason = ephemeral_reason()
    print(f"ephemeral: {'true' if reason else 'false'}")
    print(f"reason: {reason or 'none'}")
    print(f"agent: {agent_name()}")
    return 0
