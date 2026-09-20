# Disaster Recovery

## Failure classes

### Source machine lost, GitHub available, no state bundle

Perform stateless reconstruction. Functionality/identity return, but lived GOMS continuity and local credentials are lost.

### Source machine lost, GitHub + state bundle available

Perform stateful recovery. This is the intended full survivability path.

### GOMS down, host alive

Use the local authority/recovery substrate and machine execution routes. Do not make recovery depend on GOMS MCP being healthy.

### Cloud provider unavailable

Use shared model routing and preserve local fallback. Provider failure must not widen machine authority.

### Remote Commander unavailable

Try other authorised routes in the capability graph. Repair Remote Commander under local recovery authority if necessary.

### Hermes gateway unavailable

Recover the Hermes service independently using host access. GOMS state should remain intact.

## Recovery order

1. Preserve failing-state evidence if safe.
2. Identify failed layer.
3. Confirm canonical state is not being overwritten.
4. Recover minimum dependencies first.
5. Restore GOMS before mutating GOMS workers.
6. Restore local authority state/audit.
7. Restore secrets using secure local mechanisms.
8. Start canonical stores/control services.
9. Start projections/workers.
10. Start Hermes/GSV Aineko and messaging.
11. Run reconstruction acceptance.
12. Reconcile offline recovery audit when supported.
13. Record incident and recovery.

## Rollback

`exocortex_deploy.py` stages a new runtime and rotates the prior runtime to `.previous`.

That is code rollback, not data rollback. Never replace canonical GOMS state merely to roll back code.

## Break-glass

EMERGENCY authority requires explicit local human authorization, local append-only audit, minimum necessary action, post-recovery de-escalation, and later reconciliation.

## Recovery drills

Periodically perform clean stateless reconstruction, copied state restore, GOMS-down recovery, cloud-provider loss, Remote Commander loss, Hermes restart, and machine reboot/service return.

Documentation without drills is only a hypothesis.
