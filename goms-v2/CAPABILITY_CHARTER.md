# Cognitive Memory Capability Charter

## Purpose
Build the smallest infrastructure that preserves and compounds our joint capability over years, while keeping critical semantics, provenance, portability, and policy under our control.

The goal is not to own every database, vector index, model, or agent runtime. The goal is to own the parts whose loss or vendor lock-in would damage continuity, auditability, or our ability to evolve the system.

## Current needs
1. Durable continuity across nemosyne.world, Agalmic Research, personal capacity work, and future projects.
2. Deep recall of decisions, hypotheses, evidence, failures, artefacts, recurring bottlenecks, preferences, and abandoned branches.
3. Provenance: who/what asserted something, when, from which source, and with what confidence/status.
4. Temporal evolution: supersession, contradiction, changed beliefs, decisions reversed, and why.
5. Research structure: question -> claim -> evidence/counterevidence -> experiment -> decision -> artefact.
6. Capability structure: scarcity -> attempted displacement -> capability gained -> new bottleneck.
7. Procedural memory: failure -> diagnosis -> lesson -> reusable procedure -> later outcomes.
8. Low-attention retrieval: produce compact context packets instead of forcing the human to reconstruct history.
9. Local-first operation for sensitive and high-value state.
10. Machine-readable interfaces so ChatGPT, local models, OpenClaw, future agents, and tools can share the same memory substrate.

## What we should own
- Canonical ontology and identifiers for projects, questions, claims, evidence, decisions, artefacts, tasks, scarcities, capabilities, failures, lessons, people, tools, and agents.
- Append-only provenance/event ledger and migration history.
- Rules for promotion, supersession, contradiction, confidence, retention, deletion, and trust.
- Export/import format sufficient to reconstruct the useful state without a specific vendor product.
- Evaluation corpus and regression tests for recall, provenance, contradiction, temporal reasoning, and context-packet quality.
- Routing policy deciding when to use deterministic code, local models, frontier models, external agents, or human judgment.

## What should remain replaceable
- Graph engine: Neo4j today; another property/RDF graph later if justified.
- Vector/embedding engine and embedding model.
- Full-text index.
- GraphRAG/Graphiti/Mem0/A-MEM-style retrieval components.
- LLMs and agent runtimes.
- Visualization/UI layer.
- Scheduler and compute workers.

Rule: a replaceable component may accelerate or enrich the system, but must not become the sole keeper of canonical meaning.

## Expected evolution
### Stage 1: Research exocortex
Capture and retrieve meaningful work with provenance and temporal semantics. Human-machine continuity is the primary objective.

### Stage 2: Orchestration memory
Add machine capabilities, workload outcomes, compute resources, model strengths, tool permissions, procedures, and escalation history so work can be routed intelligently.

### Stage 3: Reflective learning
Mine repeated successes/failures to propose better procedures, prompts, models, tools, and scarcity-displacement strategies. Promotion requires regression evidence.

### Stage 4: Multi-agent cognition
Permit independent AI systems to read/write through scoped interfaces. Use multiplicity only where diversity, adversarial checking, isolation, specialization, or parallelism has measurable value.

### Stage 5: Institutional memory
Support durable handoff between humans and machines, reproducible investigations, portable Memory Palaces, and long-lived research programmes independent of any single model vendor.

## Build-vs-adopt decision rule
Adopt an external component when it satisfies the requirement, preserves provenance/exportability, and can be replaced without losing canonical state.
Build or fork when a requirement is central to our differentiating capability and existing tools force semantic compromise, unacceptable trust dependence, poor interoperability, or loss of control.

Every new memory feature must therefore answer: what scarcity does it displace, what evidence says it is needed, what existing tool already does it, what must we own, and how will we test that it improved meaningful work per unit of human attention?
