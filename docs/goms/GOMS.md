# GOMS in the Exocortex

## Role

GOMS is the canonical durable semantic/provenance substrate of the Exocortex.

It preserves useful joint state across sessions, models, machines, and projects without making a model vendor, graph engine, vector store, or chat transcript the sole keeper of meaning.

## Canonical information classes

GOMS represents projects, questions, claims, evidence/counterevidence, decisions, artefacts, tasks/commitments, scarcities/capabilities, failures/lessons, people/tools/agents, branches/checkpoints, control intents, provenance, and temporal change.

## Canonical vs projection

Canonical durable state is held in the GOMS store/event substrate.

Neo4j is a replaceable graph projection. Embeddings/retrieval indexes are replaceable too.

A replaceable component must not become the only copy of canonical meaning.

## MCP

`goms-v2/mcp_server.py` exposes compact Exocortex context, memory/recall, branches/checkpoints, claims/evidence, semantic search/world, control intents, resilience/guardian surfaces, Hermes authority/capability integration, and model routing.

Tool names may evolve; these semantic roles are the stable contract.

## Distillation

Raw conversational/event material flows through queue, extraction, validation/review, semantic promotion, and canonical entities/assertions.

Throughput doctrine and backlog scaling are defined in docs/goms/PROMOTION_THROUGHPUT.md. Human work-rate is treated as an input signal; normal operation scales semantic promotion capacity rather than slowing ingestion at the human boundary.

Design principles include partial-work preservation, extraction/judgment separation, promotion gates, provenance, admissibility discipline, ABSTAIN, and shared model routing.

## Governance

GOMS distinguishes evidence/clarification, proposals, canonical policy/decision, and HUMAN_ONLY transitions.

Machine authority mode does not automatically authorize semantic/control decisions.

## State root

State is outside deployment releases.

Reference macOS root:

`~/Library/Application Support/Aineko/GOMS`

The runtime release passes this path as `GOMS_HOME`, preventing deployment from replacing the canonical database with a source snapshot.

## Replication

Historical replication services may exist, but additional replication/failover work was explicitly deferred until Exocortex v1 functionality is complete. Do not confuse experiments with proven failover.
