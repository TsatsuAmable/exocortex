#!/bin/zsh
set -euo pipefail
ROOT="${GOMS_HOME:-$HOME/Library/Application Support/Aineko/GOMS}"
export GOMS_HOME="$ROOT"
HOST="${GOMS_MANFRED_AUTHORITY_HOST:?GOMS_MANFRED_AUTHORITY_HOST is required}"
CLIENT="${GOMS_MANFRED_AUTHORITY_CLIENT:?GOMS_MANFRED_AUTHORITY_CLIENT is required}"
KEY_FILE="${GOMS_MANFRED_AUTHORITY_KEY_FILE:-$ROOT/secrets/manfred-ingress.key}"
PYTHON="$HOME/Library/Application Support/Aineko/venv/bin/python"
exec "$PYTHON" "$ROOT/manfred_authority_proxy.py" \
  --host "$HOST" --port 8795 --allowed-client "$CLIENT" --key-file "$KEY_FILE"
