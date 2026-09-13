# Session State — 2026-09-10

## Operating decision
GOMS is the canonical machine-readable exocortex and provenance layer. External tools may enrich it but must remain replaceable. Notion, if adopted, is a human-facing cockpit, not the source of truth.

## Active
- Cognitive memory infrastructure: prior art done; capability charter, SQLite ledger, checkpoint schema, and native Neo4j exist. Next: comparative evaluation against Graphiti/Mem0/OpenClaw memory.
- Branch/checkpoint ledger: v1 implemented and 12 session branches seeded. Next: automatic checkpointing on topic switches and delegation.
- Local AI worker: Qwen3.5 9B promoted as `aineko-worker:v0.3` after regression tests. Next: expand task benchmarks and routing thresholds.
- Compute fabric: Mac capability inventory and model plurality identified. Next: capability registry, scheduler, and worker adapters.
- Resource stewardship: health checks, Ollama maintenance, and model load/unload policy established. Next: automate health snapshots and thresholds.
- Repository archaeology: 49 repos inventoried; old GSV Aineko workspace, GOMS, EvolvoGrid, self-evolution and orchestration artefacts recovered. Next: finish salvage/retire triage.
- GOMS salvage/redesign: generic agent-memory prior art is crowded; repositioned as provenance-first research exocortex. Next: ontology, import mapping, evaluation questions.
- Agalmic compute scarcity: candidate case established. Next: instrument 10–20 real workloads before stronger publication claims.

## Blocked / needs verification
- Nemosyne local checkout reconciliation: old staged work may contain unique changes. Next: verify archive/reconciliation state and current upstream before destructive sync.

## Parked
- EvolvoGrid: old civilization/life-simulation designs recovered. Next: reformulate the research question before implementation.
- Agalmic Research site: repo/tests/build healthy. Next: add compute-scarcity material only after measurement design is ready.
- External plugins/ambient capabilities: Desktop access is live; scholarly, Notion, and Homey options identified. Next: connect scholarly research first; use Notion only if a human cockpit is useful; defer Homey until a concrete attention-saving use case exists.

## Archaeology identity finding
- One genuine configured persistent personality found: GSV Aineko in `~/workspace-main`.
- C-3PO references are upstream OpenClaw development templates, not evidence of another personal agent.
- Search for role-personas/sub-minds remains part of repository archaeology.

## Control principle
You set goals and priorities. The principal orchestrator tracks branches and delegates. Workers execute scoped tasks. GOMS preserves state, provenance, conclusions, unresolved work, and next actions so topic changes do not erase orientation.
