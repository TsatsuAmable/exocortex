# Exocortex v1 Verified Delta — 2026-09-18

## Definition of done
Exocortex v1 is a reproducibly deployable capability, not merely the current Mac installation. A supported clean machine must be able to clone/copy the source, supply machine-local configuration/secrets separately, bootstrap the independent components, start them, and pass an end-to-end capability test. Runtime state remains portable/exportable without embedding machine-specific paths.

## Evidence inspected
- Branch: feat/hermes-goms-exocortex-20260917 at cf91aaf.
- Existing Hermes/GOMS plan: 2026-09-17-hermes-goms-exocortex.md.
- GOMS task graph/session state/capability map.
- Current worktree and 225-test suite.
- Current launchd service inventory on Tsatsus-Ultron.local.
- Portability scan for hard-coded user/Mac paths and deployment/bootstrap assets.

## Delta against Hermes/GOMS plan
| Planned item | State | Verified evidence / delta |
| --- | --- | --- |
| Task 1 failing tests | DONE | test_exocortex_context.py exists uncommitted and focused test is RED because exocortex_context is absent. |
| Task 1 read model | MISSING | exocortex_context.py does not exist. |
| Task 1 MCP exocortex_brief | MISSING | test imports expected wrapper but implementation is absent. |
| Task 1 regression pass/commit | MISSING | Full suite: 225 tests, one import error caused by intentional RED test. |
| Task 2 governed writes | MISSING | No ExocortexContext implementation yet. Existing control-intent/Governor authority substrate is present and must be reused. |
| Task 3 canonical GOMS wiring | PARTIAL | Canonical runtime DB and GOMS/Hermes services exist; plan still embeds Mac-specific GOMS_HOME and repo paths. |
| Task 3 smoke/authority verification | MISSING | Cannot run exocortex_brief until Task 1 implementation exists. |

## Existing capability that must not be rebuilt
- Canonical GOMS SQLite/provenance substrate, semantic assertions, branches/checkpoints.
- Control intents, Governor and authority review/convergence machinery.
- MCP server and Manfred read/control/authority surfaces.
- Distillation queue, workers, semantic daemon, model client and promotion gates.
- Topology/infrastructure/cognition health controllers and alerts.
- Delivery controller with durable workspaces/checkpoints and bounded execution policy.
- Hermes gateways and Hermes agent installation.
- Local model dispatch/resource stewardship.
- Existing launchd runtime on the Mac.

## Portability delta
| Requirement | State | Gap |
| --- | --- | --- |
| Single bootstrap/install entrypoint | MISSING | Only delivery-controller/install-runtime.sh exists; no whole-Exocortex installer. |
| Declarative component manifest | MISSING | Independent services are assembled implicitly from local state. |
| Machine-neutral paths | PARTIAL | Source examples/plan/capability map contain /Users/tsatsuamable and MacBook-specific assumptions. |
| Fresh environment creation | PARTIAL | goms-v2 has pyproject/uv.lock, but checked worktree contains a path-bound .venv and no top-level bootstrap. |
| Service installation abstraction | MISSING | Runtime is launchd-centric; Linux/systemd deployment is not packaged. |
| Hermes installation/config generation | MISSING | Hermes exists locally, but Exocortex does not provision/configure it reproducibly. |
| GOMS schema/state bootstrap | PARTIAL | Schema and seed/migration tooling exist; top-level orchestration is absent. |
| Capability discovery | PARTIAL | Static Mac capability map and topology inventory exist; no deployment-time registry contract. |
| Secrets/config separation | PARTIAL | Example configs exist in components; no unified Exocortex config contract. |
| End-to-end deployment acceptance test | MISSING | Component tests exist, but no clean-machine Exocortex acceptance test. |
| Cross-platform packaging | MISSING | Current deployed orchestration is macOS launchd. |

## Revised implementation order
1. Finish Task 1 from its verified RED state, without rebuilding existing GOMS authority/state machinery.
2. Finish governed Hermes writes and authority invariants.
3. Wire Hermes to canonical GOMS using machine-neutral configuration rather than committing the Mac path.
4. Add an Exocortex component manifest and capability/discovery contract.
5. Add top-level bootstrap/config generation with idempotent install and health checks.
6. Add service adapters: launchd first from current known-good state, then systemd; keep service definitions generated from one manifest.
7. Add state export/import and explicit secret/config boundaries.
8. Add clean-machine acceptance harness proving Hermes -> GOMS context -> governed action/proposal -> verification -> durable state.
9. Run acceptance on a second machine before declaring v1 deployable.

## Deferred
Further GOMS replication/failover remains deferred until Exocortex v1 functionality is complete. Portability/export is in scope; distributed failover is not.

## Immediate next implementation
Implement exocortex_context.py and the MCP exocortex_brief wrapper to turn the already-verified RED test GREEN, then run the full suite. This is the smallest unimplemented delta on the critical path.
