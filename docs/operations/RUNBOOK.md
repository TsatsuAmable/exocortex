# Operations Runbook

## Routine health view

Check:
- GSV Aineko gateway state;
- GOMS MCP availability;
- canonical GOMS data root;
- distillation queue/workers/semantic daemon;
- model router primary/fallback eligibility;
- Remote Commander health/policy;
- Ollama availability;
- Neo4j projection health;
- Manfred surfaces if in use;
- delivery-controller active jobs.

Do not equate a running PID with a healthy capability.

## Safe deployment

1. Ensure source branch/worktree is clean or intentionally staged.
2. Run reconstruction and targeted regression tests.
3. Run `exocortex_deploy.py`.
4. Verify `current` points to the new runtime and `.previous` exists if replacing a release.
5. Confirm no GOMS database exists inside the release tree.
6. Restart only affected services.
7. Verify the intended capability from the consumer side.

## GSV Aineko profile update

1. Commit SOUL/skills/profile manifest in source.
2. Run profile installer test.
3. Install onto active profile.
4. Invalidate/rebuild skill snapshot.
5. Restart gateway at a safe boundary.
6. Run behavioural smoke test.

## Model/provider change

1. Add candidate or update lifecycle/qualification.
2. Run model-specific regression/latency/tool-use checks.
3. Promote only after qualification.
4. Verify `model_route`.
5. Do not change machine authority.
6. Record retirement dates/digests where known.

## GOMS code change

1. Preserve/backup canonical state when migration risk exists.
2. Run targeted GOMS tests in its declared environment.
3. Deploy code separately from data.
4. Restart the minimum service set.
5. Verify durable read/write and any affected projection/worker.
6. Record schema migration and rollback procedure.

## Service failure

Use the recovery architecture:
- inspect;
- classify layer;
- preserve evidence;
- choose alternate authorised route;
- repair minimum layer;
- verify original capability;
- record incident.

## Before machine reboot

Confirm:
- canonical data is flushed/backed up as appropriate;
- no migration is mid-flight;
- expected launch services are enabled;
- local authority/audit state is intact.

After reboot run restart-survivability acceptance.

## GitHub survivability

Changes that materially alter architecture, config contract, skills, external dependencies, state roots, or recovery procedures are incomplete until the reconstruction docs/manifests are updated in the same change.
