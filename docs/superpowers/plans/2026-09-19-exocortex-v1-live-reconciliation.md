# Exocortex v1 Live Reconciliation — 2026-09-19

## Scope
Live reconciliation of the Exocortex v1 plan against the Mac runtime before further implementation. Replication/failover remains deferred.

## Verified live state
- Hermes gsvaineko gateway is running under Python 3.11 with its WhatsApp bridge on localhost:3000.
- Hermes launches the packaged GOMS MCP server from ~/.local/share/exocortex/current/goms-v2/mcp_server.py under Python 3.14.
- The packaged runtime manifest and Hermes authority/machine-tool/macOS-adapter files match the current Exocortex worktree implementations.
- Desktop Commander 0.2.51 is live on Node 26.8.2; its prior dead-Node blocker is resolved.
- GOMS/Manfred/distillation services and Neo4j are present as independently running services; this remains a distributed composition, not one monolith.
- Source worktree is feat/hermes-goms-exocortex-20260917 at 76a8cad and was clean before this reconciliation note.

## Plan delta corrected
The 2026-09-18 verified-delta document is now stale. Its Task 1/2/3 critical-path items have subsequently been implemented:
- DONE: compact ExocortexContext and MCP exocortex_brief.
- DONE: governed Hermes writes (record_clarification, propose_policy) with authority tests.
- DONE: machine-neutral Hermes/GOMS discovery and packaged runtime wiring.
- DONE: local Hermes authority state machine for OBSERVE/OPERATE/ADMIN/RECOVERY/EMERGENCY.
- DONE: append-only local authority/action audit.
- DONE: macOS authority adapter and governed machine-tool MCP surface.
- DONE/PARTIAL: portable runtime installer and component manifest. The installer currently packages the GOMS slice only.

## Remaining v1 gaps
1. Component manifest is incomplete: it declares only GOMS, not Hermes gateway, Manfred surfaces, health/topology controllers, delivery controller, model routing, service adapters, or recovery substrate.
2. Whole-system bootstrap is incomplete. exocortex_deploy.py installs a GOMS runtime slice and emits Hermes MCP configuration; it does not reproduce the complete Exocortex.
3. Hermes RECOVERY is not independent enough. Recovery commands live inside the GOMS MCP runtime, so loss of GOMS/MCP removes the recovery surface intended to repair it.
4. No dedicated hermes-rescue/equivalent minimal local executor exists outside the ordinary Exocortex control plane.
5. Authority elevation is persistent state rather than a scoped expiring capability lease. There is no TTL/nonce/action scope or automatic de-escalation.
6. ADMIN delegates elevation to sudo; credential handling is correctly outside GOMS, but non-interactive/local authorization semantics are not packaged or acceptance-tested.
7. Recovery catalogue is narrow: launchd list/restart/bootstrap/bootout only. Runtime/config/network/dependency recovery remains unimplemented.
8. Offline privileged audit exists, but reconciliation of offline audit into canonical GOMS is not implemented/verified.
9. Service definitions are not generated from the component manifest. launchd remains hand-assembled; systemd packaging is absent.
10. Unified machine-local config/secrets contract, state export/import, and deployment-time capability discovery remain incomplete.
11. No clean-machine end-to-end acceptance harness proves install -> start -> Hermes context -> governed action -> durable verification -> recovery.
12. No second-machine acceptance has been completed.

## Verification issue discovered
Running the suite with system Python is not a valid project verification path: dependencies such as MCP and cryptography are absent there. pyproject.toml declares MCP and Neo4j but not cryptography even though Manfred authority tests import it. Verification/bootstrap must own all runtime/test dependencies rather than rely on ambient Mac packages.

## Revised critical path
1. Expand exocortex.manifest.json into the authoritative component/capability/service manifest.
2. Make bootstrap consume that manifest and provision an isolated, complete dependency environment.
3. Extract a minimal Hermes rescue executor that remains callable when GOMS/MCP/Desktop Commander are unavailable.
4. Replace persistent elevation with scoped, expiring local capability leases and automatic de-escalation.
5. Add offline-audit reconciliation into GOMS without making recovery depend on GOMS.
6. Generate launchd service definitions from the manifest, then add systemd adapter.
7. Add state/config/secrets portability boundaries and export/import.
8. Build failure-injection + clean-machine acceptance harness.
9. Validate on a second machine.
10. Only after v1 acceptance, resume deferred replication/failover.

## Immediate implementation tranche
Manifest + bootstrap dependency closure first. This is the smallest change that turns the current collection of working components into an explicit deployable system and provides the substrate needed to package rescue and acceptance tests correctly.
