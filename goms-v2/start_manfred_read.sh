#!/bin/zsh
set -euo pipefail
ROOT="${GOMS_HOME:-$HOME/Library/Application Support/Aineko/GOMS}"
export GOMS_HOME="$ROOT"
HOST="${GOMS_MANFRED_READ_HOST:-127.0.0.1}"
CLIENT="${GOMS_MANFRED_READ_CLIENT:-}"
PYTHON="$HOME/Library/Application Support/Aineko/venv/bin/python"
if [[ -n "$CLIENT" ]]; then
  exec "$PYTHON" "$ROOT/manfred_read_proxy.py" --host "$HOST" --port 8794 --allowed-client "$CLIENT"
fi
exec "$PYTHON" "$ROOT/manfred_read_proxy.py" --host "$HOST" --port 8794
