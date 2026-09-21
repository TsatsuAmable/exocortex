---
name: exocortex-knowledge-surfaces
description: "Govern and use Obsidian, Notion, Manfred, and related human-facing knowledge surfaces without weakening GOMS canonical authority."
version: 0.1.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [exocortex, goms, obsidian, notion, knowledge, projection, reconciliation]
---

# Exocortex Knowledge Surfaces

Knowledge surfaces are interfaces onto the Exocortex, not independent memory authorities.

GSV Aineko owns keeping them coherent, useful, reconstructible, and low-attention.

## Authority order

Use these roles consistently:

1. **GOMS** — canonical machine-readable state, provenance, claims/evidence, commitments, branches, decisions, authority, reconciliation, and current operational knowledge.
2. **GitHub** — executable/project truth for source code, engineering contracts, versioned design, tests, issues, PRs, and reproducible implementation history.
3. **Obsidian / aineko-vault** — durable human-readable knowledge garden for synthesis, notes, linked concepts, research narratives, project context, and long-lived reflection.
4. **Notion** — structured coordination/cockpit surface for project views, decision registers, work tracking, dashboards, collaboration, and other structured human interaction.
5. **Manfred and other UI surfaces** — operational projections and control interfaces.

No projection surface silently outranks GOMS or GitHub in its domain.

## Core rule

Projection is not canonicalization.

Information may flow outward from GOMS into Obsidian, Notion, Manfred, or another human-facing surface as a projection.

Human edits or external changes may flow back inward only as:
- observations;
- candidate claims;
- proposed decisions;
- task/control-intent updates;
- evidence;
- explicit corrections.

They must retain provenance and pass the appropriate GOMS reconciliation/adjudication path before becoming canonical.

## Standing loop

**project → detect → reconcile → verify → record**

### Project
Keep useful human-facing views synchronized from canonical state.

Examples:
- project status and roadmaps;
- current decisions and unresolved questions;
- research syntheses;
- canonical claims with provenance links;
- active commitments;
- investigation branches;
- dashboards and attention surfaces.

Projection should be selective. Do not dump the entire GOMS evidence graph into human tools.

### Detect
Notice meaningful changes in Obsidian/Notion:
- new human note or synthesis;
- changed decision or priority;
- correction to project state;
- newly linked evidence;
- explicit task/action;
- external collaboration update.

Ignore formatting-only and mechanically generated changes where they carry no semantic delta.

### Reconcile
Translate meaningful external changes into provenance-bearing GOMS candidates.

Do not:
- overwrite canonical state directly from an Obsidian note;
- accept a Notion database field as truth merely because it changed;
- resolve conflicts by "last writer wins";
- duplicate the same concept across surfaces as independent facts.

When conflicts exist, preserve both observations, identify the governing authority for that domain, and reconcile explicitly.

### Verify
After synchronization:
- confirm the target projection reflects intended canonical state;
- confirm inbound edits were captured with provenance;
- confirm no authority inversion occurred;
- confirm links/identifiers remain resolvable;
- confirm sync is idempotent where practical.

### Record
Persist significant sync/reconciliation failures and any unresolved ambiguity in GOMS.

Routine successful synchronization should not generate human attention.

## Obsidian remit

Obsidian is the Exocortex's durable human knowledge garden.

Prefer it for:
- conceptual synthesis;
- long-form notes;
- linked research ideas;
- readable project histories;
- durable personal reasoning artefacts;
- material intended to remain useful without a database UI.

Use the existing Git-backed aineko-vault where available.

Aineko may create/update projections and organize the vault, but must preserve human-authored content and provenance. Human-authored changes are evidence/candidates on ingestion, not automatic canonical truth.

## Notion remit

Notion is the structured coordination cockpit.

Prefer it for:
- portfolio/project dashboards;
- roadmap and milestone views;
- decision registers;
- structured work queues;
- collaboration surfaces;
- recurring review views;
- compact executive summaries.

Notion should normally project GOMS/GitHub state rather than become a competing project database.

Write-back may be enabled for fields with explicit semantics, such as an approved decision or human-entered priority, but those changes must enter GOMS through a defined provenance/reconciliation contract.

## Choosing a surface

Use the minimum useful surface:
- machine reasoning/governance → GOMS;
- executable engineering state → GitHub;
- human-readable synthesis → Obsidian;
- structured coordination/collaboration → Notion;
- immediate operational control → Manfred.

Do not mirror everything everywhere.

## Attention contract

Routine projection, synchronization, deduplication, stale-view repair, and conflict detection are normally **A0** work.

A1/A2 may be used for non-urgent summaries or bundled reconciliation questions.

A3 requires the normal Attention Budget Market standard: a concrete human-only decision plus material cost of waiting.

## Growth and repair

If a surface becomes stale, duplicated, lossy, or expensive to maintain:
1. inspect the adapter/sync path;
2. repair bounded integration problems autonomously;
3. reduce unnecessary projection volume;
4. preserve provenance and rollback;
5. update reconstruction/service contracts if the surface is now relied upon.

A new external service, materially broader write authority, or new exposure/security boundary requires a proposal under exocortex-self-improvement.

## Success condition

Knowledge surfaces are successful when they reduce friction for the human without creating another source of truth.

Aineko should be able to answer:
- what is canonical;
- where a human-readable view lives;
- whether that view is current;
- what changed externally;
- whether the change was reconciled;
- whether any ambiguity genuinely requires human judgment.
