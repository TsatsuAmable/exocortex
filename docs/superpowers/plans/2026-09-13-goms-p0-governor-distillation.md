# GOMS P0 Distillation + Governor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make distillation measurable and taxonomy-safe, then deploy a bounded Governor reconciler whose first production case is replication degradation.

**Architecture:** Keep model output candidate-only, canonicalize/validate before promotion, and treat the Governor as a deterministic reconciliation kernel over desired vs observed state. Human authorization boundaries must never be crossed by automated repair.

**Tech Stack:** Python 3.14, SQLite, launchd, Ollama/Agalmic broker, Tailscale, unittest.

**Spec:** `goms-v2/TASK_GRAPH.md` and the live GOMS resource/attention schema.

## Global Constraints
- Canonical GOMS SQLite + append-only ledger remain authoritative.
- Repairs are allow-listed, bounded, reversible, and auditable.
- Human authorization/judgment boundaries escalate, never auto-execute.
- Model review cannot directly mutate canonical state.
- Raw replication evidence is never discarded on failure.

---
### Task 1: Distillation policy integration
**Files:** modify `goms-v2/distillation_pipeline.py`, `distillation_validate.py`, `distillation_gold_pipeline_eval.py`, `distillation_eval.py`; test `test_distillation_policy.py`.

- [ ] Keep policy regressions green.
- [ ] Replace duplicated extraction/validation taxonomy prompts with `distillation_policy` builders.
- [ ] Canonicalize extractor and validator kinds before persistence/scoring.
- [ ] Reap stale RUNNING rows as ABANDONED before a new run.
- [ ] Run unit suite and repeated gold evaluation; record variance, not a single point estimate.

### Task 2: Boundary-aware replication worker
**Files:** create `goms-v2/replication_worker.py`, `test_replication_worker.py`; deploy wrapper to Aineko bin only after tests.

- [ ] Test classification of Tailscale additional-check output as `human_authorization_required`.
- [ ] Test cooldown suppression and preservation of pending jobs.
- [ ] Test ordinary transient failures remain retryable with bounded attempts.
- [ ] Persist worker state without embedding authentication URLs in canonical GOMS.
- [ ] Verify successful replication path still hash-checks manifests before deletion.

### Task 3: Governor persistence/controller
**Files:** modify `schema.sql`; create `governor_controller.py`; extend `test_governor.py`.

- [ ] Add reconciliation run/action persistence with observed generation, disposition, attempt count, and result.
- [ ] Reconcile declared resources using `decide_reconciliation`.
- [ ] Surface one deduplicated HUMAN_REQUIRED attention item for authorization boundaries.
- [ ] Allow only explicit safe repairs and enforce retry budget.
- [ ] Verify no mutation occurs for human-owned or authorization-gated resources.
### Task 1: Distillation policy integration
**Files:** modify `goms-v2/distillation_pipeline.py`, `distillation_validate.py`, `distillation_gold_pipeline_eval.py`, `distillation_eval.py`; test `test_distillation_policy.py`.

- [ ] Keep policy regressions green.
- [ ] Replace duplicated extraction/validation taxonomy prompts with `distillation_policy` builders.
- [ ] Canonicalize extractor and validator kinds before persistence/scoring.
- [ ] Reap stale RUNNING rows as ABANDONED before a new run.
- [ ] Run unit suite and repeated gold evaluation; record variance, not a single point estimate.

### Task 2: Boundary-aware replication worker
**Files:** create `goms-v2/replication_worker.py`, `test_replication_worker.py`; deploy wrapper to Aineko bin only after tests.

- [ ] Test classification of Tailscale additional-check output as `human_authorization_required`.
- [ ] Test cooldown suppression and preservation of pending jobs.
- [ ] Test ordinary transient failures remain retryable with bounded attempts.
- [ ] Persist worker state without embedding authentication URLs in canonical GOMS.
- [ ] Verify successful replication path still hash-checks manifests before deletion.

### Task 3: Governor persistence/controller
**Files:** modify `schema.sql`; create `governor_controller.py`; extend `test_governor.py`.

- [ ] Add reconciliation run/action persistence with observed generation, disposition, attempt count, and result.
- [ ] Reconcile declared resources using `decide_reconciliation`.
- [ ] Surface one deduplicated HUMAN_REQUIRED attention item for authorization boundaries.
- [ ] Allow only explicit safe repairs and enforce retry budget.
- [ ] Verify no mutation occurs for human-owned or authorization-gated resources.
### Task 4: Deploy and verify
**Files:** versioned launchd examples/deploy script plus runtime copies.

- [ ] Run `uv run python -m unittest discover -v` with zero failures.
- [ ] Run the original evaluator crash case and stale-run cleanup.
- [ ] Deploy tested files, restart only affected noncritical controllers, and observe fresh state.
- [ ] Confirm replication retry storm stops while backlog remains intact and one actionable escalation is present.
- [ ] Run short timeout-bounded Ollama adversarial reviews against the actual diff.
- [ ] Fix any decisive review findings, rerun tests, then commit the hardening tranche.
