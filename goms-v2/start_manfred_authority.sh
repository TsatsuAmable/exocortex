#!/bin/zsh
set -euo pipefail
ROOT="${GOMS_HOME:-$HOME/Library/Application Support/Aineko/GOMS}"
export GOMS_HOME="$ROOT"
HOST="${GOMS_MANFRED_AUTHORITY_HOST:?GOMS_MANFRED_AUTHORITY_HOST is required}"
CLIENT="${GOMS_MANFRED_AUTHORITY_CLIENT:?GOMS_MANFRED_AUTHORITY_CLIENT is required}"
ALLOWED_SIGNERS="${GOMS_MANFRED_AUTHORITY_ALLOWED_SIGNERS_FILE:-$ROOT/secrets/manfred-authority-allowed_signers}"
SIGNER_IDENTITY="${GOMS_MANFRED_AUTHORITY_SIGNER_IDENTITY:-millhouse-manfred}"
PYTHON="$HOME/Library/Application Support/Aineko/venv/bin/python"
exec "$PYTHON" "$ROOT/manfred_authority_proxy.py" \
  --host "$HOST" --port 8795 --allowed-client "$CLIENT" \
  --allowed-signers-file "$ALLOWED_SIGNERS" --signer-identity "$SIGNER_IDENTITY"
