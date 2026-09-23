# Exocortex Knowledge Surfaces

## Authority model

- GOMS: canonical machine-readable state, evidence/provenance, decisions, commitments, branches, authority, and reconciliation.
- GitHub: executable/project truth for source, tests, engineering contracts, issues, PRs, and versioned design.
- Obsidian / aineko-vault: human-readable durable knowledge and synthesis.
- Notion: structured project/decision/work coordination and collaboration.
- Manfred: operational projection and control.

## Data flow

Outbound:

GOMS/GitHub -> selective projection -> Obsidian / Notion / Manfred

Inbound:

human/external edit -> provenance-bearing candidate/control update -> GOMS reconciliation -> canonical state

No external knowledge surface may silently overwrite canonical state.

## Operating loop

project -> detect -> reconcile -> verify -> record

Routine synchronization and stale-view repair are A0 attention work. Conflicts are preserved and reconciled, not resolved by last-writer-wins.

## Surface choice

Use the minimum useful surface. Avoid mirroring everything everywhere.

- machine reasoning/governance: GOMS
- executable engineering state: GitHub
- human-readable synthesis: Obsidian
- structured coordination/collaboration: Notion
- immediate operational control: Manfred

## Implemented wiring

### Obsidian / aineko-vault

The governed bidirectional path is implemented in `goms-v2/knowledge_surface_sync.py`.

Scheduled order is inbound-first: detect edits to the last generated projection, persist any delta as provenance-bearing GOMS evidence with CANDIDATE status, regenerate the canonical projection under `90 System/Projections/`, persist projection hashes/state outside the vault, then let the existing Git-backed vault sync provide transport and history.

This avoids last-writer-wins and prevents a human edit from being silently destroyed before capture.

### Notion

Hermes's Nous-approved official Notion MCP is the integration substrate. It can be installed non-interactively, but initial authentication requires human Notion OAuth approval. Once authenticated, Aineko owns the same projection/reconciliation loop under this authority contract.
### Notion (implemented 2026-09-21)

The governed bidirectional path is implemented in `goms-v2/notion_surface_sync.py`, mirroring the Obsidian adapter contract (inbound-first, evidence-with-diff CANDIDATE capture, projection hashes persisted outside the surface, no last-writer-wins). `scripts/run_notion_surface_steward.sh` is scheduled hourly via `org.aineko.goms-notion-sync`, but the deterministic adapter is now the normal scheduled path. A Hermes/LLM stewardship pass runs only when the adapter captures an inbound edit that requires judgment or when deterministic sync fails. Proactive token rotation (`scripts/refresh_notion_token.py`) still runs before each pass.

The Notion MCP write path is grounded in the live server v1.2.0 schemas: `notion-create-pages` with `parent.data_source_id` (ledger-first primary write), `notion-update-page` `replace_content` (human-facing page mirror; ledger mode refreshes the page too), `notion-move-pages` for bounded test-artifact quarantine. Change detection is digest-based: the machine footer carries a timestamp-stable SHA-256 of the canonical content, capture fires only on digest mismatch, and the comparison canonicalizes (detable, envelope unwrap, unescape, non-empty-line sequence) to absorb Notion render artifacts such as blank-line collapsing and `<table>` XML. Compared content is wall-clock-free; provenance timestamps live in the footer/state, not compared content.

Live verification (2026-09-21): end-to-end round trip GOMS -> ledger row (21:24Z) -> inbound bounded edit captured as provenance-bearing CANDIDATE evidence with diff -> reconciliation path verified; idempotence gate = 4 consecutive steward passes all no-op (inbound `unchanged`, outbound sha identical); 22/22 sync-module tests green. Test-artifact duplicates (24 ledger rows from pre-idempotence passes) were quarantined via `notion-move-pages` into a dedicated archive page; the canonical round-trip row and its inbound evidence were preserved.
