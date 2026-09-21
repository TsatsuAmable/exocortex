#!/bin/bash
set -euo pipefail
EXO="${EXOCORTEX_CURRENT:-$HOME/.local/share/exocortex/current}"
GOMS="${GOMS_HOME:-$HOME/Library/Application Support/Aineko/GOMS}"
exec python3 "$EXO/scripts/submit_scheduled_intent.py" \
  "$EXO/config/scheduled-intents/global-opportunity-scan.json" \
  --exocortex-home "$EXO" --goms-home "$GOMS"
