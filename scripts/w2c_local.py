#!/usr/bin/env python3
"""Compatibility shim. Import w2c.local instead."""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir():
    sys.path.insert(0, str(_SRC))

from w2c.local import *  # noqa: E402,F403
from w2c.local import COPILOT_INSTRUCTION_RELPATHS, data_home, global_config_path  # noqa: E402,F401
