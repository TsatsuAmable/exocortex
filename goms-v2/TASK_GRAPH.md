# Aineko Capability Work Graph

This file is the human-readable projection of the GOMS branch ledger. GOMS remains canonical for branch state and checkpoints.

## Priority rule
Finish shared capability infrastructure before allowing project branches to multiply. A task may run in parallel only when it has a clear worker, bounded inputs, a durable output location, and a checkpoint/handoff path.

## P0: Coordination spine
1. **GOMS core + MCP** — ACTIVE
   - Canonical SQLite/FTS + append-only provenance ledger.
   - Typed memory entities and semantic relations.
   - Branch/checkpoint state.
   - MCP server shared by OpenCode, Hermes, and future workers.
   - Next: regression suite, Neo4j projection, import/export, retrieval evaluation.

2. **Checkpoint/orchestration protocol** — ACTIVE
   - Depends on GOMS MCP.
   - Detect branch/fork/park/conclude/delegate transitions.
   - Produce compact project-state packets on demand.
   - Delivery-controller v0.2: pilot #1 completed on Nemosyne PR #707 through successful production deployment; launchd observation is active. Pilot exposed/fixed approval-gate classification, stale duplicate-check handling, and an XR evidence-kind validation defect. Bounded isolated-worktree patch/push authority is implemented and tested but remains dormant until a real PR needs it; merge/deployment authority stays disabled.

3. **Resource stewardship** — ACTIVE
   - Independent foundation for worker scheduling.
   - Keep compute availability and maintenance state observable.

## P1: Cognitive fabric
4. **Worker/model router** — ACTIVE
   - Depends on checkpoints + resource stewardship.
   - Local Qwen is validated baseline.
   - OpenCode free-model benchmark resumes only after routing harness exists.
   - Route by task class, privacy, latency, quality floor, and cost.

5. **GSV Aineko identity reconstruction** — PARKED-READY
   - Depends on stable memory + runtime boundary.
   - Identity remains runtime-agnostic; Hermes is current candidate host.
   - Preserve old workspace as archaeology, do not reactivate it implicitly.

6. **Academic research capability** — PARKED
   - Add only after provenance ingestion contract is defined.
   - Candidate connectors: Scite / Consensus / other evidence-aware scholarly search.

## P1: Economic bootstrap
7. **Cognition funding loop** — ACTIVE
   - Distressed Compute Index + attention-adjusted opportunity market.
   - Goal: machine cognition -> revenue -> controlled compute -> more cognition.
   - First experiments should require little human attention and produce measurable cashflow.

## P2: Project branches
8. **Nemosyne local reconciliation** — BLOCKED
   - Preserve uncertain staged PT4B-era work before syncing with upstream.
   - Then return to forward roadmap work and verification campaigns.

9. **Agalmic compute-scarcity study** — ACTIVE
   - Instrument real workloads before publishing stronger claims.
   - Feed compute and economic observations into the funding loop.

10. **Repository archaeology** — ACTIVE, LOW-BANDWIDTH
    - Finish salvage/adapt/archive/retire classification.
    - Promote only discoveries that displace an identified scarcity.

11. **Crystal Egg / The Crystal Covenant** — PARKED-READY
    - Valuable uncommitted local implementation and strong design corpus exist.
    - First action is preservation + visual gap review, not feature proliferation.

12. **EvolvoGrid civilization simulation** — PARKED
    - Reframe as a research programme before more implementation.
    - Run experiments opportunistically on surplus compute after the compute fabric can schedule them.

## Operating invariant
Every substantial branch must have: objective, status, last verified result, unresolved questions, next action, blocker if any, worker if delegated, and durable provenance. Topic switches create checkpoints rather than forgotten tails.
