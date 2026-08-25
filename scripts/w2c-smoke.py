#!/usr/bin/env python3
"""W2C smoke — same checks as `w2c smoke`."""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir():
    sys.path.insert(0, str(_SRC))

from w2c.cli import main_smoke  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main_smoke())
