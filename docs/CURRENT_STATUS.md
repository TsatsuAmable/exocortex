# Current Exocortex Reconstruction Status

Date: 2026-09-20 (updated after survivability wave)

## Reconstructible from Git

- GOMS v2 source/schema/MCP/governance/distillation/Manfred integration.
- Shared model router and candidate fleet.
- GSV Aineko SOUL, personality, curated skill manifest and installer.
- Hermes/GOMS integration and authority/capability/route logic.
- Delivery controller.
- Atomic runtime-slice deployment.
- Local fallback model recipe.
- Architecture and reconstruction documentation.
- Sanitized launchd service topology.
- Secret/configuration contracts.
- Reconstruction self-check and acceptance checklist.
- Per-service launchd and systemd user-unit generation from the canonical service inventory (`scripts/generate_launchd.py`, `scripts/generate_systemd.py`).
- Data-driven rescue executor with canonical failure-class plans (`scripts/rescue_executor.py`, `deploy/rescue-plans/`).
- Offline authority-audit reconciler (`scripts/reconcile_authority_audit.py`), deployed standalone at `~/.local/share/exocortex/current/scripts/` and scheduled hourly via `org.aineko.audit-reconciler`.
- Provider lifecycle manager: digest tracking, drift demotion, audited requalification (`compute/model-routing/provider_lifecycle.py`).

## Requires public/upstream dependency retrieval

- Hermes Agent runtime.
- Ollama/base models.
- Neo4j.
- Docker.
- Tailscale where private fabric is used.
- Remote Commander implementation/runtime.
- ordinary Python/Node/package dependencies.

## Requires private/non-Git continuity material for stateful recovery

- canonical GOMS state;
- Hermes authority state/audit;
- provider/Remote Commander/Manfred credentials;
- selected GSV Aineko runtime/session continuity;
- messaging credentials/sessions.

These are covered by the encrypted state bundle (`scripts/state_bundle.py`): AES-256-CBC tarball with SHA-256 manifest, sqlite sidecars and sockets excluded, manifest hashed from the staged payload. Exercised live on 2026-09-20 against real Mac state (3,567 files) and restored on a second host.

## Completed survivability wave (2026-09-20, branch `feat/hermes-goms-exocortex-20260917`)

- `9af9ee9` — scoped expiring authority leases (TTL, de-escalation, skip-level flagging); 18/18 tests.
- `5cfde46` — encrypted state-bundle create/verify/restore; launchd generator; 7/7 + 6/6.
- `3f5d347` — rescue executor + canonical failure-class plans; 8/8.
- `4e02e7f` — offline authority-audit reconciliation; 11/11 + live journal OK.
- `41c94bd` — provider lifecycle manager; 15/15 + live digest/verify.
- `ffe0e3c` — rescue executor HOME-injection fix + regression test; live failure-injection drill passed (distillation worker bootout→bootstrap→kickstart→verify, fresh PID); 9/9.
- `510e817` — systemd user-unit generator mirroring the launchd contract, incl. interval timers; 6/6.
- `ee2d615` — state-bundle hardening from live exercise: socket/sidecar skips, staged-payload hashing; 9/9.

## Exercised drills (all green, 2026-09-20)

- Failure injection: `org.aineko.goms-distillation-workers` bootout → confirm gone → bootstrap → kickstart → verify (exit 0, fresh PID).
- State bundle: create → verify → restore against real `~/.hermes` profile + authority state; second-host restore on fedora (Python 3.14) from a git-bundle + state-bundle transfer; 6/6 suites green on the clone; both generators run on the clone.
- Alternate machine route: Remote Commander MCP outage mid-session; `hermes_machine_run` carried drill, test, and commit work — recovery routing demonstrated live.

## Remaining known gaps

- Whole-system install still requires a human-approved top-level bootstrap; per-service generation is automated.
- GitHub-hosted CI is blocked by account billing/spending state (external condition, see below).
- GOMS `checkpoint` MCP endpoint fails server-side while sibling endpoints work (recorded as failure_70d8d632f6f7); durable supervision state currently recorded via `remember` records on branch `branch_85701fb7738e`.

## Survivability claim

The repository now contains enough architectural, configuration, source, identity, service, and recovery information for a competent human or agent to reconstruct a fresh Exocortex without relying on undocumented original-machine knowledge. The claim was exercised on 2026-09-20 by a clean second-host reconstruction drill (fedora): clone from bundle, full test matrix, encrypted state restore, and both service generators.

Full continuity additionally requires the separate state/secret backup tier, now operable via `state_bundle.py` (create/verify/restore) with a passfile held outside Git.

This claim should be tested periodically by clean-room reconstruction rather than trusted indefinitely.

## GitHub CI status

The reconstruction workflow is committed under `.github/workflows/reconstruction.yml`.
On 2026-09-20 GitHub-hosted jobs for this private repository were blocked before runner startup by the account billing/spending state. This is an infrastructure/account condition, not a test failure.

Until that external condition is cleared, run `scripts/verify_reconstruction.sh` locally. The same reconstruction tests were green locally before publication, and the feature branch `feat/hermes-goms-exocortex-20260917` is pushed to origin with all of the above.