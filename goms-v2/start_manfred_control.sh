#!/bin/zsh
set -euo pipefail
ROOT="${GOMS_HOME:-$HOME/Library/Application Support/Aineko/GOMS}"
export GOMS_HOME="$ROOT"
export GOMS_MANFRED_TOKEN="$(<"$ROOT/secrets/manfred-read.token")"
export GOMS_MANFRED_AUTHORITY_TOKEN="$(<"$ROOT/secrets/manfred-authority.token")"
exec "$HOME/Library/Application Support/Aineko/venv/bin/python" \
  "$ROOT/manfred_http.py" --host 127.0.0.1 --port 8793
