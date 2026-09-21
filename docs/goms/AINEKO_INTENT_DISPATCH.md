# Aineko Intent Dispatch — Exocortex v1

## Problem
GOMS control intents were previously attention-derived only (`attention_item → control_intent`). ChatGPT, Hermes, and Manfred had no durable, idempotent, auditable path to submit tasks **to** Aineko and receive a canonical intent ID plus acknowledgement. This is the Exocortex v1 Aineko intent-dispatch gap.

## Contract (canonical)
- **First-class `control_intents` row**: `kind='aineko_task'` (or `external`/`submitted`) reuses existing `control_intents` machinery, events, ledger, and terminal lifecycle. No parallel store.
- **Idempotent submission**: `submit_intent(..., idempotency_key)` → `{intent_id, acknowledged, replayed}`. Fingerprint = canonical hash of semantic payload (title, summary, kind, source, project, priority, risk_tier, execution_policy, recommended_action, alternatives, verification_policy, provenance, evidence_refs, decision_required, conversation locator). Same key + same fingerprint replays same intent_id. Same key + different fingerprint → `idempotency_key_reused` (no write).
- **Status-queryable**: `control_intent(intent_id)` / `control_intents(status)` / `ControlIntentService.get()` returns current status, `acknowledged_at`, `provenance.submission`, `execution_attempts`, and `evidence_refs`.
- **Safely cancellable before execution**: `cancel_intent(intent_id)` allowed from `DETECTED, STAGED, NEEDS_DECISION, APPROVED, DEFERRED, ESCALATED` → `CANCELLED` (terminal). Rejected from `EXECUTING, VERIFYING, RESOLVED, REJECTED, FAILED, CANCELLED, OUTCOME_UNKNOWN`. Durable, audited (`control_intent_cancel` event).
- **Restart-resumable**: All state in SQLite (`control_intents`, `control_intent_submissions`, `control_intent_execution_attempts`). Reopening `GomsStore` preserves intents, submissions, and claims.
- **Auditable**: Every transition appends `control_intent_events` and `events.jsonl` (`control_intent_submit`, `control_intent_cancel`, `control_intent_aineko_claim`, `control_intent_aineko_result`, plus standard `control_intent_events`). Provenance retains `submission.{actor, idempotency_key, human_attested, resolved_by, submitted_at}` and `project`.

## Authority semantics
- **Submission ≠ authorization**. `human_attested=False` (default) creates `NEEDS_DECISION` and requires a separate `decide_control_intent(..., human_attested=True, resolved_by='human:...')` via `ManfredControl`.
- **Explicit human_attested** (`human_attested=True` + `resolved_by` starting with `human:`) auto-approves on submit (transitions `NEEDS_DECISION → APPROVED`). No implicit escalation from model confidence or source.
- **HUMAN_ONLY preserved**: `execution_policy=HUMAN_ONLY` remains non-claimable by Aineko workers (`human_only_intent_not_claimable_by_worker`). Only `AUTO_AFTER_APPROVAL` and `CONFIRM_HIGH_RISK` (after confirmation) are worker-claimable. The claim boundary enforces the policy.

## Worker / queue claim boundary and evidence/results
- **Queue**: `list_pending_for_worker(kind, limit)` / MCP `aineko_pending_intents` returns `APPROVED` intents ordered by priority.
- **Claim**: `claim_for_aineko(intent_id, worker_id)` atomically `BEGIN IMMEDIATE` checks `status=APPROVED` and policy ≠ `HUMAN_ONLY`, inserts one `control_intent_execution_attempts` row (unique per intent), and transitions `APPROVED → EXECUTING`. Second claim → `execution already claimed` or status mismatch. This is the only durable claim boundary; restart sees the same attempt.
- **Evidence/results**: `record_aineko_result(intent_id, attempt_id, worker_id, status, result, evidence_title, evidence_summary)` finishes the attempt, transitions `EXECUTING → VERIFYING → RESOLVED` (SUCCESS), `EXECUTING → FAILED` (FAILED), or `EXECUTING → OUTCOME_UNKNOWN` (UNKNOWN), writes `outcome` JSON, appends ledger events, and creates a durable `evidence` entity (`aineko-execution`) whose ID is appended to `control_intents.evidence_refs` and referenced in provenance.

## Surfaces
- **MCP** (`goms-v2/mcp_server.py`): `submit_intent`, `cancel_intent`, `aineko_pending_intents`, `aineko_claim_intent`, `aineko_complete_intent` (in addition to existing `control_intent`, `control_intents`, `decide_control_intent`, `link_control_intent_conversation`).
- **Manfred control plane** (`goms-v2/manfred_control.py`): idempotent command types `submit_intent`, `cancel_intent`, `aineko_claim_intent`, `aineko_complete_intent` via `/v1/manfred/commands` (bearer) and signed authority proxy (`/v1/manfred/intent-command`) — `ALLOWED_COMMANDS` extended. Reuses `manfred_commands` ledger for command-level idempotency plus submission-level fingerprint.
- **HTTP loopback**: Manfred HTTP remains loopback-only; remote exposure remains via authenticated tunnel/proxy. No change to peer-auth or tailnet checks.

## Lifecycle
```
submit(..., idempotency_key, human_attested?) → NEEDS_DECISION (acknowledged_at)
  ──human_attested+human resolved_by──► APPROVED
  ──decide(APPROVE) via Manfred───────► APPROVED
  ──cancel (pre-execution)───────────► CANCELLED (terminal)
  ──approve then claim_for_aineko────► EXECUTING (one attempt)
  ──record_aineko_result(SUCCESS)────► VERIFYING → RESOLVED (+ evidence)
  ──record_aineko_result(FAILED)─────► FAILED
  ──stale EXECUTING handled as OUTCOME_UNKNOWN via existing staleness guard
```

## Storage
- Canonical SQLite: `control_intents`, `control_intent_events`, `control_intent_execution_attempts`, new `control_intent_submissions` ( `idempotency_key PK, intent_id UNIQUE, fingerprint, timestamps` ).
- Ledger: `events.jsonl` append-only (prev_line_sha256 chain).
- Projection: Neo4j rebuild unchanged; no new projection state.

## Non-goals
- GOMS replication/failover intentionally untouched (deferred until v1 complete per `docs/goms/GOMS.md` and `docs/runtime/SERVICE_TOPOLOGY.md`).
- No new model routing or delivery-controller authority.

## Verification
- Unit: `goms-v2/test_aineko_dispatch.py` — submit, duplicate same payload (replay), duplicate different payload (reused error), status queryable, cancel before execution, cancel from APPROVED, cancel after EXECUTING rejected, claim single-worker boundary, HUMAN_ONLY not claimable, evidence creation, restart-resumable (reopen store), authority (no auto-approval without `human_attested`+`human:` actor), MCP surfaces, Manfred command ledger.
- Existing suites: `test_control_intents`, `test_manfred_control`, `test_intent_execution`, `test_mcp_control_intents` (when `mcp` available) remain green.
- Reconstruction: `python3 scripts/reconstruction_check.py` passes (no secret-bearing paths, required files present including this doc and schema).
