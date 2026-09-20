#!/bin/zsh
set -eu

: "${EXOCORTEX_CURRENT:?EXOCORTEX_CURRENT required}"
: "${HERMES_HOME:?HERMES_HOME required}"
: "${NOTION_KNOWLEDGE_SURFACE_PAGE_ID:?NOTION_KNOWLEDGE_SURFACE_PAGE_ID required}"
: "${NOTION_COCKPIT_PAGE_ID:?NOTION_COCKPIT_PAGE_ID required}"
: "${NOTION_LEDGER_DATA_SOURCE_ID:?NOTION_LEDGER_DATA_SOURCE_ID required}"

PROMPT="$EXOCORTEX_CURRENT/hermes/prompts/notion-knowledge-surface-steward.md"
TMP="${TMPDIR:-/tmp}/notion-knowledge-surface-steward.$$.md"
trap 'rm -f "$TMP"' EXIT

sed   -e "s/NOTION_KNOWLEDGE_SURFACE_PAGE_ID/$NOTION_KNOWLEDGE_SURFACE_PAGE_ID/g"   -e "s/NOTION_COCKPIT_PAGE_ID/$NOTION_COCKPIT_PAGE_ID/g"   -e "s/NOTION_LEDGER_DATA_SOURCE_ID/$NOTION_LEDGER_DATA_SOURCE_ID/g"   "$PROMPT" > "$TMP"

exec "$HOME/.local/bin/hermes"   --in "$EXOCORTEX_CURRENT"   --reasoning medium   --skills exocortex-knowledge-surfaces,exocortex-executive   --toolsets goms,notion   -z "$(cat "$TMP")"
