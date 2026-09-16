# GOMS Authority Review Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the held distillation REVIEW population into an explainable, protocol-owned convergence loop that automatically resolves only deterministic cases and exposes genuinely ambiguous residue through a compact low-attention surface.

**Architecture:** Keep `distillation_promotion_gate` authoritative. Add deterministic review policy helpers for explicit reasons, entity rebinding and contradiction semantics; add an idempotent review reconciler that records every machine action; add it as a bounded semantic-daemon stage; publish residual review cohorts as a GOMS resource/attention summary and Manfred brief section. LLM committee output may annotate residual cases but cannot independently promote them.

**Tech Stack:** Python 3, SQLite, launchd runtime, existing GOMS resources/attention/Manfred control plane.

**Spec:** Live canonical backlog at 2026-09-16: 921 candidate proposals; 636 gate REVIEW decisions; 434 reasonless score-threshold reviews; 108 potential-contradiction reviews; 18 duplicate-only reviews; 19 unresolved-identity reviews; 26 temporal/non-factual reviews.

## Global Constraints
- Preserve the existing temporal-authority and promotion thresholds.
- Never auto-promote because an LLM says a claim is plausible.
- Exact duplicate entity resolution may rebind IDs only when normalized titles match an existing canonical entity.
- Multi-valued predicates must not be treated as contradictions merely because object values differ.
- Functional-state updates may supersede only through existing temporal lineage semantics.
- Every automatic review action must be durable, idempotent, and auditable.
- Human attention should be cohort-level by default, not one alert per candidate.

---

### Task 1: Explainable gate and contradiction semantics
**Files:** Create `goms-v2/distillation_review_policy.py`; create `goms-v2/test_distillation_review_policy.py`; modify `goms-v2/distillation_promotion_gate.py`.
**Interfaces:** Produces `review_reason_for_score(score)`, `predicate_is_functional(predicate)`, and `assess_existing_values(...)` for the gate.
- [ ] Write failing tests proving score-only REVIEW gets `LOW_COMPOSITE_CONFIDENCE`, ordinary multi-valued relations are not contradictions, and stale/new functional-state conflicts are distinguished.
- [ ] Run focused tests and observe expected failures.
- [ ] Implement minimal policy helpers and wire them into the gate.
- [ ] Run focused tests and existing temporal/gate tests.
- [ ] Commit.

### Task 2: Deterministic review reconciler
**Files:** Create `goms-v2/distillation_review_reconciler.py`; create `goms-v2/test_distillation_review_reconciler.py`; modify `goms-v2/schema.sql`.
**Interfaces:** Produces `reconcile_review_batch(connection, limit=50)` and durable table `distillation_review_adjudications` with before/after/action/reason/timestamp.
- [ ] Write failing tests for exact duplicate rebinding, NONFACTUAL quarantine, idempotence, and refusal to auto-resolve low-confidence/identity/ambiguous cases.
- [ ] Verify failures.
- [ ] Implement deterministic actions only: `REBIND_ENTITY`, `QUARANTINE_NONFACTUAL`, `HOLD`; invalidate affected gate/review rows for safe re-evaluation.
- [ ] Verify focused tests and schema recreation tests.
- [ ] Commit.

### Task 3: Fair convergence daemon integration
**Files:** Modify `goms-v2/distillation_semantic_daemon.py`; modify `goms-v2/test_distillation_semantic_daemon.py`.
**Interfaces:** Adds stage count `review_actionable` and bounded stage `adjudicate` without starving validate/reconcile/gate/shape/promote.
- [ ] Write failing scheduler tests showing actionable review gets a fair turn and HOLD-only residue does not loop forever.
- [ ] Verify failures.
- [ ] Add stage/count and script dispatch.
- [ ] Verify daemon tests.
- [ ] Commit.

### Task 4: Low-attention review surface
**Files:** Create `goms-v2/distillation_review_surface.py`; create `goms-v2/test_distillation_review_surface.py`; modify `goms-v2/manfred_control.py` and `goms-v2/test_manfred_control.py` if needed.
**Interfaces:** Produces cohort summary `{total, cohorts, oldest, examples}`; publishes one `AuthorityReviewQueue` resource and at most one attention item; Manfred brief includes the compact summary.
- [ ] Write failing tests for cohort aggregation, deduplicated attention, and concise Manfred projection.
- [ ] Verify failures.
- [ ] Implement resource/attention publishing and brief projection.
- [ ] Verify focused tests.
- [ ] Commit.

### Task 5: Live dry-run, canary, deploy
**Files:** No new behavior unless evidence exposes a defect.
**Interfaces:** Uses a SQLite copy first, then the live runtime only after full verification.
- [ ] Run full unit suite, compileall, and `git diff --check`.
- [ ] Run review reconciler against a live DB copy; compare before/after review cohorts and assert no new canonical assertions are created by adjudication itself.
- [ ] Run gate/shape/promote canary on the copy and inspect all automatically cleared cases.
- [ ] Snapshot live DB/runtime files, deploy verified scripts, run one bounded review cycle, and regenerate queue resource/attention.
- [ ] Re-run full verification and live SQLite integrity check.
