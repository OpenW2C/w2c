"""Detect a temporary container, where only pushed work survives."""

from __future__ import annotations

import os
from typing import Mapping

OVERRIDE = "W2C_EPHEMERAL"
VARIABLES = ("CLAUDE_CODE_REMOTE", "CODESPACES", "GITHUB_ACTIONS")


def ephemeral_reason(env: Mapping[str, str] | None = None) -> str | None:
    """Name the variable that marks a temporary container, or None."""
    env = os.environ if env is None else env
    override = env.get(OVERRIDE, "").strip().lower()
    if override in ("1", "true"):
        return OVERRIDE
    if override in ("0", "false"):
        return None
    for name in VARIABLES:
        if env.get(name, "").strip().lower() not in ("", "0", "false"):
            return name
    return None


def cmd_env() -> int:
    reason = ephemeral_reason()
    print(f"ephemeral: {'true' if reason else 'false'}")
    print(f"reason: {reason or 'none'}")
    return 0
