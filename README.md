# Exocortex

A deployable personal cognitive operating system built around **GSV Aineko / Hermes**, **GOMS**, a shared model router, governed machine execution, durable delivery orchestration, and replaceable external tools.

This repository is the canonical source for reconstructing the Exocortex implementation. It is intentionally separate from Agalmic Research and from application projects that consume it.

## Reconstruction contract

A competent human or agent with:
1. this repository;
2. access to the related repositories listed in `docs/reconstruction/REPOSITORY_MAP.md`;
3. ordinary public package/model sources; and
4. optionally an encrypted state bundle,

must be able to reconstruct a working Exocortex without relying on undocumented knowledge from the original machine.

Two targets are defined:

- **Stateless reconstruction:** recreate the software, architecture, identity, model routing, authority boundaries, services, and fresh durable stores from GitHub and public dependencies.
- **Stateful recovery:** perform stateless reconstruction, then restore the encrypted/non-Git state bundle containing GOMS history, credentials, local authority audit, Hermes session state, and other continuity data.

Git contains no reusable secrets and no canonical live databases.

## System map

```text
Human
  |
  v
GSV Aineko / Hermes
  |-- GOMS durable context, claims, evidence, decisions, branches
  |-- model_route -> qualified model/provider pool
  |-- capability graph -> authorised execution routes
  |-- Codex / OpenCode / specialist workers
  |-- Remote Commander / Tailscale execution fabric
  |-- Manfred read/control/authority surfaces
  '-- Delivery Controller -> GitHub / CI / review lifecycle

GOMS
  |-- canonical SQLite event/state store
  |-- Neo4j replaceable graph projection
  |-- distillation queue/workers/semantic daemon
  |-- topology, cognition and infrastructure health controllers
  '-- governance, provenance and control intents
```

See `docs/architecture/OVERVIEW.md` for the full logical architecture.

## Start here

- Reconstruction: `docs/reconstruction/REBUILD_FROM_GITHUB.md`
- Repository map: `docs/reconstruction/REPOSITORY_MAP.md`
- State/secrets boundary: `docs/reconstruction/STATE_AND_SECRETS.md`
- Acceptance contract: `docs/reconstruction/ACCEPTANCE_CHECKLIST.md`
- Architecture: `docs/architecture/OVERVIEW.md`
- Components: `docs/architecture/COMPONENTS.md`
- Runtime/reference config: `docs/runtime/REFERENCE_CONFIGURATION.md`
- Service topology: `docs/runtime/SERVICE_TOPOLOGY.md`
- GSV Aineko software: `docs/hermes/GSV_AINEKO.md`
- GOMS: `docs/goms/GOMS.md`
- Disaster recovery: `docs/operations/DISASTER_RECOVERY.md`

## Known-good reference point

The current reference runtime was verified on macOS / Apple Silicon on 2026-09-20.

Key tested external versions:
- Hermes Agent 0.21.1, upstream commit `f6ddd89692dff1f900983a16208f39a1485a14eb`
- Python 3.11.14 for Hermes
- GOMS requires Python >=3.12
- Node 26.8.2
- Docker 29.2.1
- Ollama 0.33.2 server / 0.33.3 CLI
- Neo4j 2026.07.1
- Tailscale 1.102.4

These versions are a recovery reference, not eternal requirements. Upgrade only through tested compatibility.

## Current maturity

The live system is functional and substantially more complete than the top-level deployment manifest. The manifest currently packages GOMS, model routing, and the GSV Aineko profile. Several live services are still launchd-managed outside that manifest.

The survivability documentation therefore distinguishes:
- **implemented and packaged**;
- **implemented but externally wired**;
- **external replaceable dependency**; and
- **planned portability gap**.

Do not infer completeness from the manifest alone.

## Security posture

This repository must never contain:
- API/OAuth tokens;
- private keys;
- WhatsApp session material;
- canonical GOMS databases;
- Hermes runtime databases;
- authority credentials;
- machine-specific bearer tokens.

Commit schemas, templates, hashes, recipes, public keys where appropriate, and restore instructions instead.

## Canonical design principles

- Human attention is a scarce control channel.
- GOMS owns canonical durable semantic/provenance state.
- Model choice is replaceable and does not grant machine authority.
- Execution authority is explicit, local, auditable, and independent of model confidence.
- Reuse existing authorities before building parallel systems.
- Prefer reversible actions and verified effects over conversational plans.
- A failed route triggers recovery before human handoff.
- Replaceable infrastructure must not become the sole keeper of canonical meaning.
