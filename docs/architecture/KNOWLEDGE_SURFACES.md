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
