# Reconstruction Acceptance Checklist

A recovered Exocortex is accepted only when behaviour, authority, and persistence are verified.

## Source integrity

- [ ] Repository is at a recorded commit.
- [ ] `python3 scripts/reconstruction_check.py` passes.
- [ ] No secret-bearing files are tracked.
- [ ] Manifest component entrypoints exist.
- [ ] GSV Aineko profile manifest references existing skills.

## GOMS

- [ ] GOMS environment installs from declared dependencies.
- [ ] Schema/store opens successfully.
- [ ] MCP server starts.
- [ ] A durable read succeeds.
- [ ] A permitted durable write succeeds.
- [ ] Restart preserves the write.
- [ ] Neo4j projection, if enabled, can be rebuilt/reconciled from canonical state.

## GSV Aineko / Hermes

- [ ] Hermes runs at the selected tested/pinned version.
- [ ] `install_profile.py --check` passes.
- [ ] Active personality is `exocortex`.
- [ ] Skill index exposes all five Exocortex skills.
- [ ] A role smoke test identifies GSV Aineko primarily as the Exocortex executive.
- [ ] For an authorised mechanical task, it acts through a tool rather than instructing the human to do the mechanics.

## Model routing

- [ ] Local fallback `gsvaineko-core:v1` can be created and invoked.
- [ ] `model_route` returns at least one eligible candidate.
- [ ] Retired/disabled/unqualified candidates are not promoted as primary.
- [ ] Private tasks exclude non-private routes.
- [ ] Provider/model failure can fall back without changing machine authority.

## Execution and authority

- [ ] Default authority is OBSERVE or intended local baseline.
- [ ] OPERATE permits the expected routine execution route.
- [ ] Elevation requires explicit human authorization.
- [ ] Mode change is appended to local audit.
- [ ] Remote Commander/chosen host effector can execute a harmless command.
- [ ] A failed preferred route produces recovery/alternate routing before escalation.

## Recovery

- [ ] GOMS can be stopped without deleting local authority/audit.
- [ ] Recovery instructions remain available without querying GOMS.
- [ ] Selected control-plane service can be restarted under the correct authority mode.
- [ ] Original capability is verified after repair.

## Aineko intent dispatch (Exocortex v1)

- [ ] `submit_intent` creates a durable `control_intent` (kind `aineko_task`) and returns `intent_id` + `acknowledged` (MCP and Manfred).
- [ ] Same `idempotency_key` + same payload replays same `intent_id` without duplicate row; different payload with same key is rejected (`idempotency_key_reused`).
- [ ] Status is queryable (`control_intent` / `control_intents` / `ControlIntentService.get`) and includes `acknowledged_at` and `provenance.submission`.
- [ ] `cancel_intent` before `EXECUTING` transitions to `CANCELLED` (audited); `cancel` after `EXECUTING` is rejected.
- [ ] Approved intents appear in Aineko worker queue (`aineko_pending_intents`); `HUMAN_ONLY` remains non-claimable.
- [ ] `aineko_claim_intent` is atomic (one `control_intent_execution_attempts` row, `APPROVED → EXECUTING`); second claim fails. Restart preserves the claim.
- [ ] `aineko_complete_intent` writes durable evidence (`evidence` entity, `evidence_refs`, `outcome`) and transitions to `RESOLVED`/`FAILED`.
- [ ] Submission without `human_attested` + `human:` actor stays `NEEDS_DECISION` (no auto-authorization); with explicit `human_attested` + `human:` actor auto-approves but `HUMAN_ONLY` still blocks worker claim.
- [ ] All transitions are audited (`control_intent_events` + `events.jsonl`); `goms-v2/test_aineko_dispatch.py` passes green.
- [ ] Restart (reopen `GomsStore` / reload `ControlIntentService`) preserves intents, submissions, and claims.

## Optional Manfred

- [ ] Read surface authenticates and returns a brief.
- [ ] Control surface rejects missing/invalid token.
- [ ] Authority path enforces separate credential/signature boundary.
- [ ] Non-loopback exposure uses authenticated/private transport.

## Optional delivery controller

- [ ] Durable job database initializes.
- [ ] GitHub/CI observation works.
- [ ] Waiting consumes no continuous model inference.
- [ ] Authority gates prevent unintended merge/deploy.

## Restart survivability

- [ ] Host/service restart returns the required service graph.
- [ ] GOMS data root is not replaced by a release snapshot.
- [ ] Hermes reconnects to canonical GOMS.
- [ ] Messaging surface reconnects if configured.
- [ ] No source edit with machine-specific paths was required.

Record Git commit, state bundle ID/hash if restored, host/platform, dependency versions, deviations, checks passed/failed, operator/agent, and timestamp.
