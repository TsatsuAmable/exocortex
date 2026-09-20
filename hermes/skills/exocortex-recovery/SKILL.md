---
name: exocortex-recovery
description: "Recover Exocortex services without human attention handoff."
version: 0.1.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [exocortex, recovery, administration, resilience, break-glass]
---

# Exocortex Recovery

Use for degraded services, failed routes, machine administration, broken integrations, unavailable tools, or break-glass situations.

## Recovery rule

A failed first route is a recovery problem, not a reason to transfer mechanical work to the human.

1. Inspect current capability and policy.
2. Identify the failed layer.
3. Preserve evidence and rollback state.
4. Select another authorised route.
5. Repair the minimum layer required.
6. Verify both the repair and the original intended effect.
7. Record the failure mode and recovery if reusable.

## Authority modes

Treat authority as a ceiling:

- **OBSERVE**: inspect only.
- **OPERATE**: normal reversible user-space operations and authorised service/process work.
- **ADMIN**: privileged routine administration under explicit authority.
- **RECOVERY**: independent recovery when normal Exocortex paths are impaired.
- **EMERGENCY**: exceptional maximum authority explicitly granted by the human.

Never widen permissions merely because a route is inconvenient.

## Host execution

The normal Hermes terminal may be sandboxed. For authorised macOS host effects, use the Remote Commander MCP and its exact namespaced tools. Inspect device policy before declaring host execution unavailable.

Machine-route selection and model selection are separate. A stronger model does not grant stronger machine permissions.

## Escalation

Escalate only after the available authorised recovery graph is exhausted, or when a hard human gate is reached.

Report:
- what failed;
- what was tried;
- current safe state;
- the exact human decision/action still required.
