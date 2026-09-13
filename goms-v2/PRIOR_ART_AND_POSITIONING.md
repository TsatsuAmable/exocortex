# GOMS v2 Prior Art and Positioning

Status: design review after external prior-art sweep, 2026-09-10.

## Process correction

We began a minimal GOMS v2 scaffold before completing the external prior-art review. That was premature. The scaffold is deliberately small and remains useful, but further architecture work should follow this comparison.

## Major prior art

- MemGPT / Letta: hierarchical memory tiers and model-managed virtual context.
- Generative Agents: experience stream, retrieval, reflection, and planning.
- Reflexion: episodic lessons from task feedback used to improve later attempts.
- MemoryBank: persistent personal memory, salience, reinforcement, and forgetting.
- Zep / Graphiti: temporal knowledge graphs, provenance, fact invalidation, and hybrid graph/vector/text retrieval.
- Mem0: extraction, consolidation, retrieval, and graph-enhanced conversational memory.
- A-MEM: dynamically linked and evolving memory notes rather than fixed schemas.
- AgeMem: learned store/retrieve/update/summarize/discard memory operations.
- Microsoft GraphRAG: graph-derived corpus structure for local and global retrieval.
- LoCoMo / LongMemEval / LoCoMo-Plus: evaluation families for long-term and cognitive memory.
## Revised GOMS role

GOMS is not positioned as a generic long-term-memory invention. Its distinctive target is a provenance-first research exocortex for sustained human-machine work.

Canonical objects should include:
- research questions, hypotheses and claims
- evidence, sources and counter-evidence
- decisions and superseded decisions
- artefacts, experiments and verification results
- scarcities, capabilities and bottleneck migrations
- tasks, failures, lessons and reusable procedures
- projects, people-context and durable preferences where appropriate

The important information lives in typed relationships and temporal state changes, not merely semantic similarity.

## Design consequences

1. Adopt temporal validity and provenance semantics rather than inventing them from scratch.
2. Keep raw source/episode history distinct from derived claims and summaries.
3. Treat supersession as a first-class relation; never silently overwrite history.
4. Combine lexical, semantic and graph retrieval.
5. Separate canonical evidence from model-generated interpretation.
6. Record confidence/uncertainty and the provenance of derived memories.
7. Make memory operations measurable and benchmarkable.
8. Prefer importing/adapting mature components such as Graphiti where they fit rather than reproducing them.
