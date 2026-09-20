# Repository Map

## Canonical Exocortex repository

### `TsatsuAmable/exocortex`

**Status:** canonical Exocortex source and reconstruction index.

Owns the architecture and reconstruction documentation, current GOMS v2 code, model routing, GSV Aineko identity and skills, deployment slice, authority/execution integration, and delivery controller.

This repository should be sufficient for a stateless rebuild when combined with declared public dependencies.

## Related repositories

### `TsatsuAmable/goms_project`

**Visibility:** public.  
**Status:** historical/legacy GOMS lineage and prior implementation context.

Do not treat it as the canonical source for the current Exocortex GOMS runtime. The current source is maintained here under `goms-v2/`. It remains valuable for archaeology and provenance.

### `TsatsuAmable/aineko-device-agent`

**Visibility:** private.  
**Role:** Android/device substrate associated with the wider Aineko/Life Cockpit ecosystem.

It is an adjacent capability, not a prerequisite for a minimal stateless Exocortex reconstruction.

### `TsatsuAmable/aineko-vault`

**Visibility:** private.  
**Role:** Git-backed Obsidian knowledge graph.

It is a continuity/knowledge adjunct, not the canonical GOMS store. Its loss must not make GOMS unreconstructible.

## Upstream external repository

### `NousResearch/hermes-agent`

Provides the Hermes runtime shell.

Known-good Exocortex reference:
- version 0.21.1;
- commit `f6ddd89692dff1f900983a16208f39a1485a14eb`.

The Exocortex-owned identity/profile/skills live in this repository and are installed onto Hermes.

## Repository policy

Every dependency is classified as one of:
- **canonical**: loss changes Exocortex meaning or prevents faithful reconstruction;
- **adjacent**: useful capability but not required for the core reconstruction;
- **replaceable substrate**: implementation may change if the contract is preserved;
- **historical**: provenance/archaeology only.

No undocumented private repository may be a hidden mandatory dependency.

If a new repository becomes mandatory for reconstruction, add it here and add a reconstruction acceptance check.
