---
name: exocortex-survivability
description: "Continuously prove, maintain, and repair Exocortex reconstructibility, continuity, and recovery readiness."
version: 0.1.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [exocortex, survivability, reconstruction, continuity, recovery, stewardship]
---

# Exocortex Survivability

Survivability is a standing GSV Aineko responsibility, not a one-off project.

The Exocortex is survivable when a competent human or authorised agent can reconstruct its functioning capability from canonical Git sources plus separately protected continuity material, and when its recovery routes remain exercised rather than merely documented.

## Standing loop

**inventory → prove → exercise → detect drift → repair → verify → record**

Run this loop periodically and after material architectural, deployment, authority, storage, routing, or dependency changes.

### Inventory
Identify:
- canonical repository revision and reconstruction contract;
- required external dependencies and versions;
- protected continuity/state bundle and freshness;
- service-generation manifests;
- authority/audit state;
- provider/model lifecycle state;
- rescue plans and alternate machine routes;
- supported reconstruction hosts.

### Prove
Verify, as applicable:
- reconstruction structural checks;
- focused contract tests;
- continuity bundle integrity;
- service manifest generation;
- rescue-plan integrity;
- authority audit reconciliation;
- provider lifecycle consistency;
- no undocumented mandatory dependency has appeared.

### Exercise
At bounded cadence, exercise real recovery paths rather than trusting documentation:
- restart/recover a non-critical service;
- restore a test continuity bundle;
- reconstruct on a clean secondary host or disposable environment;
- route around an intentionally unavailable provider/tool;
- verify recovery/audit evidence afterwards.

Do not perform disruptive failure injection merely to satisfy cadence. Prefer bounded canaries and rotate exercised failure classes.

### Detect drift
Treat as survivability defects:
- reconstructible state differs from live state without documentation;
- secrets or state are required but absent from the protected continuity contract;
- a service cannot be generated from canonical configuration;
- recovery depends on the component being repaired;
- provider/model digests drift without requalification;
- a machine-specific path or undocumented local edit becomes mandatory;
- continuity proof becomes stale;
- recovery tests stop representing the live architecture.

### Repair
Inside accepted architecture and authority, repair survivability regressions autonomously:
- update code/config/manifests;
- rebuild stale continuity artifacts;
- refresh qualified provider state;
- repair rescue routes;
- update reconstruction docs and tests;
- remove hidden local-only dependencies;
- restore scheduled stewardship.

Material new architecture, exposure, authority, or recovery-risk choices require a bounded proposal under the self-improvement protocol.

## Human boundary

Routine survivability work is normally A0 under the Attention Budget Market.

Do not interrupt the human for:
- periodic reconstruction checks;
- continuity bundle verification;
- service manifest regeneration;
- routine recovery canaries;
- repairing a bounded broken recovery path;
- dependency/version drift that can be resolved inside accepted contracts.

Escalate only when:
- recovery requires unavailable credentials, biometrics, or physical access;
- a protected continuity artifact is irrecoverably missing;
- meeting survivability targets requires a material value/cost/risk trade-off;
- a new architecture or authority boundary is required;
- a destructive/irreversible choice is genuinely necessary.

## Evidence contract

Every survivability claim should have current evidence. Prefer:
- commit/tag;
- host/environment;
- command/test set;
- continuity bundle hash;
- service-manifest generation result;
- exercised failure class;
- observed recovery result;
- timestamp.

"Worked previously" is not current evidence.

## Cadence

Default stewardship:
- lightweight reconstruction/dependency/continuity audit: daily;
- continuity bundle refresh/verify: when state materially changes and at least weekly where practical;
- bounded recovery drill: weekly, rotating failure class;
- clean secondary-host reconstruction: after material architecture changes and periodically thereafter.

Cadence may be reduced when the system can prove no relevant state changed.

## Completion

A survivability maintenance cycle is complete when:
- the current architecture is reconstructible from declared sources;
- protected continuity material verifies;
- selected recovery paths are exercised or current proof is still valid;
- drift is repaired or explicitly recorded;
- evidence is durable in GOMS/Git;
- no routine human action is required.
