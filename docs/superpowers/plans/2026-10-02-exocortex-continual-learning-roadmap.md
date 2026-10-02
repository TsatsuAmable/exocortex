# Exocortex Continual-Learning Roadmap

Date: 2026-10-02
Status: PLANNED / EXPERIMENTAL
Priority: P1 Cognitive Fabric
Reference implementation: https://github.com/volotat/mini-AGI

## Objective

Test whether Exocortex can convert accumulated governed experience into cheap local cognitive competence that retrieval alone does not provide, without sacrificing provenance, reconstructibility, privacy, or previously learned capability.

mini-AGI is a reference implementation and experimental stimulus, not an Exocortex dependency and not evidence of AGI.

## Architectural invariant

GOMS remains canonical for knowledge, authority, provenance, branch state, and reconstructible memory.

Learned weights are a **derived cognitive substrate**, comparable to an index, cache, embedding store, or compiled projection. They must never become the sole carrier of facts, decisions, authority, provenance, or recovery-critical state.

A lost model must be replaceable from canonical sources, deterministic corpus manifests, training/evaluation configuration, checkpoint lineage, and promotion records. Learned outputs may advise routing, context selection, compression, procedural prediction, or bounded recall; they do not grant execution authority.

## Research question

> Can Exocortex learn useful local competence continuously from its own governed experience, while preserving prior competence and outperforming or reducing the cost of retrieval-only approaches on bounded tasks?

## Hypotheses

- **H1:** continual local learning can reduce context/token cost for recurring Exocortex tasks without reducing task success.
- **H2:** slow-changing shared parameters plus faster specialist parameters can reduce catastrophic forgetting.
- **H3:** procedural competence, routing priors, failure recognition, and context selection will benefit more than raw factual memorisation.
- **H4:** GOMS + retrieval + learned priors will outperform either retrieval-only or learned-weights-only approaches on selected bounded tasks.
- **H5:** if learned weights cannot show incremental value under controlled evaluation, this lane should stop rather than graduate by architectural enthusiasm.

## Scope boundaries

In scope:
- reproduce continual-learning/forgetting probes;
- deterministic GOMS-to-training-corpus export;
- local incremental-training experiments;
- retention/interference measurement;
- bake-off against current GOMS FTS/context-packet retrieval;
- optional shadow-mode router integration;
- checkpoint lineage, rollback, and reconstruction.

Out of scope until evidence supports expansion:
- replacing GOMS;
- granting learned weights execution authority;
- autonomous self-modification without evaluation gates;
- training on secrets without explicit governance;
- broad factual memorisation merely to duplicate retrieval;
- making mini-AGI a production dependency.

## Experimental phases

### CL0 — Architecture preflight

Define the continual-learning capability contract, data flow, authority matrix, provenance/checkpoint schema, privacy rules, compute/storage budget, reconstruction recipe, and prohibited authority transitions.

**Exit:** learned weights cannot become a second source of truth; every promoted checkpoint is traceable to source manifests and evaluation results; model loss does not imply memory loss.

### CL1 — Reproduce mini-AGI continual-learning probe

Independently test the central empirical result before borrowing architectural conclusions. Start reduced-scale, then approach the published configuration where practical.

Required arms:
1. frozen/static expert working set;
2. swapping experts with shared trunk at expert LR;
3. swapping experts with shared trunk at 0.1x LR;
4. interleaved control.

Capture acquisition, prior-domain loss change, working-set size, RAM/VRAM, throughput, training time, checkpoint size, expert utilisation, and shared-trunk drift.

**Exit:** result is independently reproduced, bounded, or falsified. No Exocortex integration begins on an unverified headline result.

### CL2 — Deterministic Exocortex corpus adapter

Build a reproducible governed training stream from selected validated procedures, project-state packets, failure/recovery records, routing decisions, implementation lessons, and non-sensitive technical context.

Every emitted record must retain or reference source entity ID, source revision/hash, timestamp, provenance class, inclusion policy, and corpus version.

**Exit:** identical canonical state + configuration yields the same corpus manifest/hash; exclusions are explicit; rebuild/removal procedures exist.

### CL3 — Controlled continual-learning experiment

Suggested sequence: Exocortex core operations -> Nemosyne technical context -> Agalmic Research workflows -> deliberately novel held-out technical material.

Evaluate after every tranche for target-task success, retention, negative transfer, latency, training/inference cost, and context-token requirement.

**Exit:** acquisition/retention/interference matrix exists and identifies both gains and regressions.

### CL4 — Baseline bake-off

Compare:
A. model with no Exocortex context;
B. GOMS FTS/context-packet retrieval;
C. learned substrate only;
D. GOMS retrieval + learned substrate.

Primary outcomes: bounded task success, context tokens, latency, compute cost, failure rate, provenance completeness, and human attention required.

**Promotion gate:** learned cognition must improve a pre-specified outcome or combination of outcomes. “Interesting representation” is not an admissible promotion criterion.

### CL5 — Shadow-mode hybrid prototype

Candidate bounded uses: context-selection prior, procedure prediction, task-class routing hints, recurring failure-pattern recognition, context compression, and low-cost semantic cue generation.

Existing router remains authoritative. Learned output is advisory, decisions/counterfactuals are logged, and no execution permission derives from learned output.

**Exit:** shadow evidence demonstrates incremental value with no material safety/provenance regression.

### CL6 — Continual-update controller

Only after CL5 succeeds, automate: source-manifest snapshot -> candidate training -> regression/forgetting suite -> active-vs-candidate comparison -> lineage record -> gated promotion -> rollback pointer.

Hard rule: no candidate becomes active merely because training completed.

### CL7 — Survivability and reconstruction

Git/GOMS must retain training recipe, corpus-builder code, corpus-manifest schema, evaluation suite, checkpoint metadata, lineage, promotion decision, and compatibility/version information. Large model blobs may live outside Git if digest and reconstruction path are recorded.

**Exit:** a clean machine can regenerate an equivalent substrate; deleting learned checkpoints cannot destroy canonical knowledge.

## Evaluation protocol

Every experiment pre-specifies: claim, corpus version, treatment arms, held-out evaluation material, metrics, failure thresholds, stopping rule, compute budget, and promotion rule.

Minimum metric families:
1. acquisition;
2. retention;
3. interference;
4. efficiency: tokens, latency, compute, storage;
5. attention: human checking/intervention removed;
6. provenance;
7. recoverability.

Prefer **ABSTAIN / NO-PROMOTION** when criteria are absent or inconclusive.

## Initial tranche

Run **CL0 + CL1** first.

Do not build the Exocortex corpus trainer before mini-AGI's continual-learning result is independently reproduced or bounded. If the result does not survive reproduction, retain any useful primitives as prior art and stop this lane.

Preferred first compute target: Apple-Silicon Mac where practical, because the purpose is cheap local cognition. CUDA may be used for reference reproduction where necessary; platform convenience is not architectural evidence.

## Relationship to existing Exocortex components

- **GOMS:** canonical explicit memory and provenance.
- **Retrieval/context packets:** explicit relevant-memory injection.
- **Learned substrate:** derived priors, habits, procedural competence, and compression.
- **Worker/model router:** controlled consumer of learned advisory signals.
- **Governor/authority boundary:** sole execution-authority path.
- **Survivability layer:** reconstructs recipes, manifests, lineage, and compatible checkpoints.

Desired eventual division of labour:

`GOMS explicit memory -> retrieval explicit context -> learned substrate cheap intuition -> stronger models deliberation -> Governor authority`

## Decision gates

After CL1: **GO**, **NARROW**, or **STOP** based on reproduction evidence.
After CL4: **PROMOTE TO SHADOW** only when a pre-specified Exocortex task demonstrates measurable incremental value.
After CL5: **PROMOTE TO CONTROLLED PRODUCTION** only for the task class actually validated.

## Durable outputs even on failure

A reproducible continual-learning benchmark, GOMS corpus-manifest tooling, retention/interference harness, model-lineage schema, promotion/rollback protocol, retrieval-vs-learned-memory evidence, Apple-Silicon feasibility measurements, and a reusable local-cognition benchmark.

## Next action

Implement CL0 architecture preflight and CL1 reproduction harness. Record evidence before authorising CL2.
