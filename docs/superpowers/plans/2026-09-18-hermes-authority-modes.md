# Hermes Authority Modes

Date: 2026-09-18
Status: Accepted architecture for Exocortex v1

## Purpose

Hermes is both an Exocortex client and the human principal's independent machine
recovery path. Capability and current authority are therefore separate concepts.
GOMS governs ordinary Exocortex activity, but GOMS must not be the sole source of
Hermes authority: a failed control plane must not disable its own recovery tool.

## Modes

| Mode | Authority | Intended use |
| --- | --- | --- |
| OBSERVE | Read-only machine and GOMS | Diagnosis and context reconstruction |
| OPERATE | Normal user-level machine operations | Routine delegated work |
| ADMIN | Privileged machine administration | Explicitly delegated administration |
| RECOVERY | Independent repair of machine/Exocortex control plane | GOMS/MCP/tool failure |
| EMERGENCY | Locally authorized break-glass administration | Exceptional recovery outside normal envelope |

Modes grant ceilings, not instructions. Entering a mode never authorizes a
specific HUMAN_ONLY GOMS control intent.

## Authority roots

Normal modes may consume GOMS policy. ADMIN, RECOVERY, and EMERGENCY require an
explicit local human-controlled authority mechanism independent of GOMS. The
implementation must not store reusable administrator secrets in GOMS.

Privileged elevation should be short-lived where the operating system permits.
Mode selection and privileged actions must be locally auditable even when GOMS
is unavailable. Audit records are reconciled into GOMS after recovery.

## Invariants

1. GOMS remains canonical for Exocortex goals, semantic state, control intents,
   provenance, and ordinary governance.
2. Hermes has no second semantic/state authority.
3. Mode elevation does not mutate a control intent or count as approval,
   confirmation, or human attestation.
4. HUMAN_ONLY intent lifecycle transitions still require the existing explicit
   human decision path.
5. RECOVERY can repair GOMS, MCP, Hermes integration, service configuration and
   dependencies without requiring those components to be healthy.
6. EMERGENCY is explicit break-glass authority, locally invoked by the human
   principal and separately audited.
7. Privileged credentials/secrets remain outside portable repository state and
   outside GOMS semantic memory.
8. Every mutating Hermes action records actor, mode, target, action, timestamp,
   result and available provenance.
9. Recovery audit is append-only locally and must tolerate GOMS being offline.
10. Portability must preserve this authority model on supported hosts. Service
    adapters may differ by OS, but the mode semantics do not.

## Task 2 impact

Governed Exocortex writes remain intentionally narrow:
- record_clarification: durable provenance-bearing evidence; no intent lifecycle mutation.
- propose_policy: durable PROPOSED idea requiring human ratification; never canonical policy by insertion.

These are GOMS-facing operations and are independent of machine authority mode.
ADMIN/RECOVERY/EMERGENCY machine operations will use a separate local authority
adapter rather than overloading GOMS control-intent APIs.

## Implementation sequence

1. Add adversarial tests for governed GOMS writes and HUMAN_ONLY invariants.
2. Implement record_clarification and propose_policy through the canonical store.
3. Add local Hermes authority-mode configuration/state machine.
4. Add append-only local privileged-action audit independent of GOMS.
5. Add OS authority adapter, launchd/macOS first, with explicit local elevation.
6. Add recovery commands constrained to control-plane repair.
7. Add explicit break-glass EMERGENCY entry and audit.
8. Reconcile offline audit records into GOMS when canonical services recover.
9. Exercise the mode model in the clean-machine acceptance harness.

Replication/failover remains deferred until Exocortex v1 functionality is complete.
