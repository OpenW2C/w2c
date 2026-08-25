#!/usr/bin/env bash
# W2C smoke — ledger coherence checks.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$ROOT/w2c-smoke.py" "$@"
