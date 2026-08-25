#!/usr/bin/env bash
# W2C CLI — status writer for .w2c ledger files.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$ROOT/w2c.py" "$@"
