#!/usr/bin/env python3
"""Shim for DATA_HOME / checkout copies. Prefer `w2c` on PATH or `python -m w2c`."""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir():
    sys.path.insert(0, str(_SRC))

from w2c.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
