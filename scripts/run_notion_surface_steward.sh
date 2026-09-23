#!/bin/zsh
set -eu

: "${EXOCORTEX_CURRENT:?EXOCORTEX_CURRENT required}"
: "${HERMES_HOME:?HERMES_HOME required}"
: "${NOTION_KNOWLEDGE_SURFACE_PAGE_ID:?NOTION_KNOWLEDGE_SURFACE_PAGE_ID required}"
: "${NOTION_COCKPIT_PAGE_ID:?NOTION_COCKPIT_PAGE_ID required}"
: "${NOTION_LEDGER_DATA_SOURCE_ID:?NOTION_LEDGER_DATA_SOURCE_ID required}"


# Proactive OAuth token rotation: Notion access tokens are short-lived (~8h).
# Rotate when <1h remains so the hourly steward never runs on a stale token.
if ! python3 "$EXOCORTEX_CURRENT/scripts/refresh_notion_token.py" 3600; then
  echo "[notion-surface] token refresh failed; continuing with stored token"
fi

# Deterministic governed sync is the normal hourly path. The LLM steward
# is reserved for actual inbound edits or deterministic-sync failure.
GOMS_HOME="${GOMS_HOME:-$HOME/Library/Application Support/Aineko/GOMS}"
SYNC_SCRIPT="$EXOCORTEX_CURRENT/goms-v2/notion_surface_sync.py"
SYNC_RESULT="${TMPDIR:-/tmp}/notion-surface-sync.$$.json"
trap 'rm -f "$SYNC_RESULT"' EXIT
if [ -f "$SYNC_SCRIPT" ]; then
  export NOTION_TOKEN=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['access_token'])" "$HERMES_HOME/mcp-tokens/notion.json" 2>/dev/null || true)
  if GOMS_HOME="$GOMS_HOME" python3 "$SYNC_SCRIPT" sync \
    --root "$GOMS_HOME" \
    --page-id "$NOTION_KNOWLEDGE_SURFACE_PAGE_ID" \
    --ledger-id "$NOTION_LEDGER_DATA_SOURCE_ID" >"$SYNC_RESULT" 2>&1; then
    cat "$SYNC_RESULT"
    if python3 - "$SYNC_RESULT" <<'PY'
import json, sys
try:
    result = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if not result.get("inbound", {}).get("captured") else 1)
PY
    then
      echo "[notion-surface] no inbound edit; deterministic sync complete; skipping LLM steward"
      exit 0
    fi
  else
    cat "$SYNC_RESULT" >&2
    echo "[notion-surface] deterministic sync failed; LLM steward continues" >&2
  fi
fi

PROMPT="$EXOCORTEX_CURRENT/hermes/prompts/notion-knowledge-surface-steward.md"
TMP="${TMPDIR:-/tmp}/notion-knowledge-surface-steward.$$.md"
trap 'rm -f "$TMP" "$SYNC_RESULT"' EXIT

sed   -e "s/NOTION_KNOWLEDGE_SURFACE_PAGE_ID/$NOTION_KNOWLEDGE_SURFACE_PAGE_ID/g"   -e "s/NOTION_COCKPIT_PAGE_ID/$NOTION_COCKPIT_PAGE_ID/g"   -e "s/NOTION_LEDGER_DATA_SOURCE_ID/$NOTION_LEDGER_DATA_SOURCE_ID/g"   "$PROMPT" > "$TMP"

exec "$HOME/.local/bin/hermes"   --in "$EXOCORTEX_CURRENT"   --reasoning medium   --skills exocortex-knowledge-surfaces,exocortex-executive   --toolsets goms,notion   -z "$(cat "$TMP")"
