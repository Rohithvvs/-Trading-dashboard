#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
exec "${PAPER_PYTHON:-/workspace/sahil-fyers-turso/.venv/bin/python}" "$ROOT/engine.py" "$@"
