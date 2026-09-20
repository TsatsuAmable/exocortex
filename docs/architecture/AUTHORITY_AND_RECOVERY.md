# Authority and Recovery Architecture

## Core distinction

Capability, authority, semantic approval, and model intelligence are separate.

A tool may exist without being authorised. A model may be capable without having permission. An elevated machine mode does not approve a HUMAN_ONLY GOMS decision.

## Modes

| Mode | Ceiling | Typical use |
|---|---|---|
| OBSERVE | read-only | diagnosis/context |
| OPERATE | normal user-level mutation | routine delegated work |
| ADMIN | privileged administration | explicit administration |
| RECOVERY | independent control-plane repair | Exocortex/tool failure |
| EMERGENCY | explicit break-glass maximum | exceptional recovery |

Modes are ceilings, not task authorizations.

## Local authority root

`goms-v2/hermes_authority.py` stores state/audit under `~/.hermes/authority` by default.

This is intentionally independent of GOMS availability.

Elevation requires explicit human authorization. Audit records include actor/principal, mode, action, target, result, timestamp and detail.

## Capability discovery

`hermes_capability_graph.py` combines core capabilities with discovered execution-fabric routes.

A route is viable only if it is:
- available;
- authorised for current mode;
- healthy.

## Route selection

`hermes_route_selector.py` defines preference by task kind and excludes previously attempted routes.

Decision outcomes are:
- ACT;
- RECOVER;
- ESCALATE.

ESCALATE is appropriate only when no healthy authorised route remains.

## Recovery invariant

The system being repaired must not be the sole provider of its own repair authority.

This is why:
- authority state/audit is local;
- RECOVERY exists separately from ordinary GOMS governance;
- host effectors such as Remote Commander are distinct from model/GOMS state.

## Remaining hardening

Current authority mode is persistent state rather than a scoped expiring lease. Long-term hardening should add TTL/action scope/nonces and automatic de-escalation.

Offline recovery audit reconciliation into GOMS also remains an explicit v1 gap.
