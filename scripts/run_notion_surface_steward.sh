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

# Deterministic governed sync pass runs before the agent steward.
# The adapter is canonical for projection + inbound capture; the Hermes
# steward pass handles judgment work (dedupe, summarization, backlog).
GOMS_HOME="${GOMS_HOME:-$HOME/Library/Application Support/Aineko/GOMS}"
SYNC_SCRIPT="$EXOCORTEX_CURRENT/goms-v2/notion_surface_sync.py"
if [ -f "$SYNC_SCRIPT" ]; then
  NOTION_TOKEN=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['access_token'])" "$HERMES_HOME/mcp-tokens/notion.json" 2>/dev/null || true)
  GOMS_HOME="$GOMS_HOME" python3 "$SYNC_SCRIPT" sync \
    --root "$GOMS_HOME" \
    --page-id "$NOTION_KNOWLEDGE_SURFACE_PAGE_ID" \
    --ledger-id "$NOTION_LEDGER_DATA_SOURCE_ID" \
    || echo "[notion-surface] deterministic sync failed; steward continues"
fi

PROMPT="$EXOCORTEX_CURRENT/hermes/prompts/notion-knowledge-surface-steward.md"
TMP="${TMPDIR:-/tmp}/notion-knowledge-surface-steward.$$.md"
trap 'rm -f "$TMP"' EXIT

sed   -e "s/NOTION_KNOWLEDGE_SURFACE_PAGE_ID/$NOTION_KNOWLEDGE_SURFACE_PAGE_ID/g"   -e "s/NOTION_COCKPIT_PAGE_ID/$NOTION_COCKPIT_PAGE_ID/g"   -e "s/NOTION_LEDGER_DATA_SOURCE_ID/$NOTION_LEDGER_DATA_SOURCE_ID/g"   "$PROMPT" > "$TMP"

exec "$HOME/.local/bin/hermes"   --in "$EXOCORTEX_CURRENT"   --reasoning medium   --skills exocortex-knowledge-surfaces,exocortex-executive   --toolsets goms,notion   -z "$(cat "$TMP")"
