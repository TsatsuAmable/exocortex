#!/bin/zsh
set -euo pipefail
ROOT="${GOMS_HOME:-$HOME/Library/Application Support/Aineko/GOMS}"
export GOMS_HOME="$ROOT"
exec "$HOME/Library/Application Support/Aineko/venv/bin/python" \
  "$ROOT/manfred_read_proxy.py" --host 127.0.0.1 --port 8794
