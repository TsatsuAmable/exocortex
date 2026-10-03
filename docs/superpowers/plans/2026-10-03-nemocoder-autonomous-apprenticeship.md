# NemoCoder autonomous apprenticeship programme

Date: 2026-10-03
Status: ACTIVE DESIGN / AUTONOMOUS BOOTSTRAP
Priority: P1 Cognitive Fabric
Base host: MacBook Pro / Apple M1 Pro / 16 GB unified memory
First target repository: TsatsuAmable/nemosyne

## Objective

Build a locally served coding specialist that becomes measurably good at Nemosyne engineering through a closed, evidence-gated apprenticeship loop:

`mine -> reconstruct task -> baseline -> train -> hidden eval -> diagnose -> promote/reject -> repeat`.

The user should not have to curate datasets, choose every task, supervise every training round, or manually advance the curriculum.

## Relationship to Exocortex continual learning

The existing Exocortex continual-learning roadmap remains the general research lane for durable learned cognition and mini-AGI-style continual learning.

NemoCoder is narrower and applied. It may use ordinary supervised fine-tuning, LoRA/QLoRA, preference optimisation or other bounded post-training methods. It does **not** wait for the mini-AGI reproduction result because specialist coding adaptation does not depend on that hypothesis.

Shared primitives should converge where useful:
- provenance-aware corpus manifests;
- model/checkpoint lineage;
- retention/regression evaluation;
- promotion/rollback;
- GOMS evidence;
- model routing;
- survivability/reconstruction.

## Architectural invariants

1. Nemosyne remains an application target, never the home or authority for NemoCoder.
2. GOMS/Git remain canonical for provenance and project facts. Learned weights are derived artifacts.
3. Candidate models never train against the secret holdout.
4. Evaluation never mutates the target repository's canonical `main`.
5. A trained model earns task classes through evidence. It does not self-grant execution, merge, roadmap, scientific or security authority.
6. A model can be discarded and reconstructed without losing canonical knowledge.
7. Training completion is not promotion.

## Model strategy

### First inference baseline
- `gpt-oss-20b`, served through Ollama if local resource preflight passes.
- It is a benchmark target, not a commitment to use it for every training round.

### Trainable alternatives
- Gemma 4 small variants are eligible.
- Other compact coding-capable open models may be selected from measured evidence.
- Model choice is based on Nemosyne benchmark quality, trainability on available compute, latency, memory and reproducibility.

### Training/runtime separation
Ollama is the preferred local serving interface. Fine-tuning is performed by an interchangeable backend such as MLX-LM where compatible or Transformers/TRL/PEFT. External GPU training is optional and must obey existing spend/authority policy.

## Phases

### NC0 — host and dependency preflight

Build the deterministic preflight:
- host CPU/GPU/unified memory/disk/swap;
- Ollama health and installed models;
- Python/uv environment;
- Git/GitHub access;
- MLX, Transformers, TRL, PEFT compatibility;
- target-repository access;
- thermal/resource guardrails.

Exit: machine-readable capability report plus an explicit local-training envelope.

### NC1 — provenance-aware Nemosyne corpus miner

Mine:
- Git commits and merges;
- PR task statements and accepted patches;
- tests added with fixes;
- CI failures and recoveries;
- RFL findings and reproducers;
- Shadow findings and later dispositions;
- ADR/RFC/roadmap-linked work;
- rejected/reverted approaches where disposition is known.

Every candidate record retains source repo, immutable SHAs, PR/finding IDs, task family, affected paths, evidence and admission status.

Exit: deterministic raw corpus manifest with secret/provenance checks.

### NC2 — leakage and quality admission

Build admission filters for:
- credentials/private material;
- hidden-eval contamination;
- duplicated solutions;
- obsolete/superseded architecture;
- candidate findings incorrectly treated as accepted truth;
- changes without adequate evidence;
- generated noise and process-only churn.

Exit: versioned curated corpus whose records are traceable to canonical source evidence.

### NC3 — historical task reconstruction

For each eligible historical change:
1. checkout immutable pre-change base in a disposable worktree;
2. generate a sanitized task statement that does not expose the patch;
3. register allowed tools/paths and risk class;
4. capture authoritative public tests;
5. create or identify hidden falsifiers where justified;
6. retain the historical solution only as evaluator provenance.

Exit: at least 50 reproducible tasks across several difficulty levels.

### NC4 — frozen evaluation harness

Create:
- public development suite;
- frozen secret holdout;
- time-split fresh-task suite;
- compilation/typecheck/test graders;
- production-path and hidden-falsifier graders;
- diff/path boundary checks;
- authority/security/governance checks;
- latency, memory and tool reliability measures;
- explicit ABSTAIN scoring.

Exit: deterministic benchmark runner with tamper-evident manifests.

### NC5 — untouched base-model baselines

Run the same benchmark against:
1. GPT-OSS-20B via Ollama;
2. at least one smaller locally trainable candidate;
3. optionally the best existing local coding model already available.

Measure score by task family and difficulty, not only aggregate score.

Exit: baseline capability curve and initial incumbent selection. No fine-tuning before NC4/NC5.

### NC6 — first bounded fine-tune

Build trainer abstraction:
`prepare -> train -> checkpoint -> export -> verify-load -> evaluate`.

First run uses a small admitted slice and parameter-efficient tuning. Persist:
- base model identity;
- corpus hash;
- trainer config;
- seed where meaningful;
- adapter/checkpoint hash;
- environment;
- wall time/resource use.

Exit: one candidate checkpoint that can be served and evaluated reproducibly.

### NC7 — progressive curriculum

Difficulty levels:
- L0 repository navigation/factual retrieval;
- L1 locate implementation behind a contract;
- L2 focused tests;
- L3 deterministic bug reproduction;
- L4 one-file repair;
- L5 bounded multi-file repair;
- L6 CI/build diagnosis;
- L7 lifecycle/concurrency/trust-boundary repair;
- L8 architecture archaeology/authority audit;
- L9 small pre-specified roadmap tranche;
- L10 adversarial review;
- L11 select/propose the next safe bounded task.

Instruction scaffolding decays with level. Early levels provide file hints and recipes. Higher levels provide goals, governing contracts and normal tools only.

Exit: automatic level unlock/regression logic driven by hidden evaluation.

### NC8 — closed self-improvement loop

Automate:
`identify weakness -> assemble clean training slice -> train -> hidden eval -> compare -> promote/reject -> diagnose -> augment -> repeat`.

Rejected checkpoints remain evidence but never replace the incumbent.

Exit: unattended multi-round execution with checkpoint recovery and circuit breakers.

### NC9 — agent interface and routing

Expose the incumbent through:
- Ollama/OpenAI-compatible local endpoint where possible;
- a stable NemoCoder CLI;
- Hermes/OpenCode worker adapter;
- model-version/capability metadata;
- ABSTAIN/escalation response;
- tool-call sandbox.

Register it with the shared Exocortex model router as a qualified specialist only for task families actually demonstrated.

Exit: other Exocortex workers can call NemoCoder without bespoke manual setup.

### NC10 — earned operational permissions

Capability permissions are separate from model scores.

Possible progression:
read-only archaeology -> test/falsifier generation -> isolated historical repair -> isolated current-branch repair -> CI triage -> review assistance -> bounded implementation assistance.

Still excluded unless separately authorised:
- merge authority;
- Nemosyne roadmap authority;
- security-policy changes;
- scientific/evidence acceptance;
- credential access;
- self-modification of its own promotion criteria.

Exit: machine-readable mapping from benchmark evidence to permitted assistance classes.

### NC11 — continuous apprenticeship

Continuously:
- quarantine newly merged work before mining;
- add genuinely novel tasks;
- re-run prior replay suites;
- detect forgetting and overfitting;
- compare newly available base models;
- retrain only when expected benefit justifies compute;
- preserve lineage and rollback.

Exit: sustainable maintenance loop, not a one-off model.

## Promotion gates

A checkpoint may replace the incumbent only when all are true:
- zero critical authority/security/secret-leakage violations;
- at least 80% executable success on >=20 eligible hidden tasks at the claimed level;
- prior unlocked levels regress by <=5 percentage points;
- aggregate hidden score improves by >=3 percentage points, or a preregistered task-family objective materially improves without material regression;
- environment, corpus and artifact identities are complete.

Insufficient sample size produces `ABSTAIN_INSUFFICIENT_EVIDENCE`.

Thresholds cannot be relaxed after seeing the candidate result.

## Required tooling

NemoCoder must implement:
1. host preflight;
2. Git/PR/RFL/Shadow corpus miner;
3. secret/leakage/provenance scrubber;
4. historical task rebuilder;
5. disposable worktree/sandbox executor;
6. grader and hidden-falsifier registry;
7. curriculum classifier;
8. trainer backend abstraction;
9. model/checkpoint/experiment registry;
10. promotion and regression gate;
11. Ollama serving adapter;
12. Hermes/OpenCode/CLI bridge;
13. supervisor with singleton lease, heartbeat, timeout, crash recovery and resource limits;
14. periodic progress reporter;
15. reproducible export/reconstruction bundle.

## Stop/escalation conditions

Stop the relevant action rather than improvising when:
- secret holdout contamination is suspected;
- credentials/private data enter a dataset candidate;
- an eval would mutate canonical production state;
- evidence cannot be made executable;
- repeated rounds regress without a bounded diagnosis;
- resource pressure threatens the host;
- external paid compute is needed outside approved policy;
- a capability request crosses execution, merge, governance, security or scientific authority.

## User reporting

Detailed state is machine-readable. User-facing reports occur on:
- phase completion;
- material checkpoint promotion/rejection;
- blocker requiring human action;
- material compute/cost decision;
- otherwise approximately every six hours while active.

Report only: phase, measurable result, incumbent/candidate, changed artifact, next autonomous action and blocker if any.

## Initial autonomous sequence

Start NC0 immediately. Then NC1-NC5 establish the benchmark before any training. NC6 begins only after the untouched-model baseline exists.

The first concrete milestone is: **50 reconstructed Nemosyne tasks, five or more difficulty bands, a frozen hidden benchmark, and baseline curves for GPT-OSS-20B plus one smaller trainable candidate.**
