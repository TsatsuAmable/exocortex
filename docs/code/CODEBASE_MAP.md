# Codebase Map

This map is for a human or agent reconstructing intent from source without reading the entire repository.

## Top level

### `exocortex.manifest.json`

Authoritative reconstruction/deployment manifest. Describes packaged components, external dependencies, durable state roots, service inventory, and reconstruction entrypoints.

### `exocortex_deploy.py`

Atomic runtime-slice installer. Copies declared components into a staging release, excludes runtime state, rotates the previous release, and generates Hermes/GOMS MCP configuration.

### `goms_v2_path.py`

Source-root helper used by deployment/config generation.

## `goms-v2/`

### Canonical store and schema
- `goms_store.py` — primary store abstraction.
- `schema.sql` — schema.
- `goms.py` — GOMS command/interface logic.
- `checkpoint.py` — checkpoint support.
- `canonical_temporal_migrate.py` — temporal migration.
- `repository_reconciliation.py` — repository-state reconciliation.

### MCP / Exocortex context
- `mcp_server.py` — main MCP surface.
- `exocortex_context.py` — compact Exocortex context synthesis.
- `hermes_goms_config.py` — Hermes MCP discovery/config.
- `model_router_bridge.py` — bridge to shared model router.

### Claims, semantics, graph
- `graph_backend.py` — graph abstraction.
- `neo4j_projection.py` — Neo4j projection.
- `semantic_maintenance.py` — semantic maintenance.
- `semantic_* / ontology_evolution.py` — semantic/ontology machinery.
- `seed_semantic_core.py` — initial semantic seed.

### Governance and control
- `governor.py`, `governor_controller.py` — governance.
- `control_intents.py`, `control_intent_reconciler.py` — control intents and reconciliation.
- `commitment_gate.py`, `commitment_dashboard.py` — commitment gating/status.
- `guardian_packet.py`, `guardian_review.py` — guardian review.

### Distillation
- `distillation_queue*.py` — queue/server/hygiene.
- `distillation_worker*.py` — worker/daemon/pool.
- `distillation_pipeline.py` — pipeline.
- `distillation_validate*.py` — validation.
- `distillation_review*.py` — review/adjudication.
- `distillation_promot*.py` — promotion.
- `distillation_semantic_daemon.py` — semantic daemon.
- `distillation_model_client.py` — model boundary.

### Hermes authority/execution
- `hermes_authority.py` — local authority modes and append-only audit.
- `hermes_attention_gate.py` — pre-escalation attention gate.
- `hermes_capability_graph.py` — executable capability inventory.
- `hermes_fabric_discovery.py` — execution-fabric discovery.
- `hermes_route_selector.py` — preferred route/failover selection.
- `hermes_machine_tools.py` — machine effectors.
- `hermes_execution_supervisor.py` — supervised execution.
- `hermes_macos_adapter.py` — macOS authority/service adapter.

### Manfred
- `manfred_control.py` — command/control semantics.
- `manfred_http.py` — loopback control HTTP API.
- `manfred_read_proxy.py` — read surface.
- `manfred_authority_proxy.py` — authority/signature surface.
- `manfred_projection.py`, `manfred_sync.py` — projection/sync.

### Health/topology
- `topology_inventory.py`, `topology_controller.py`
- `infrastructure_health_controller.py`
- `cognition_health_controller.py`
- `alerts.py`

## `compute/model-routing/`

- `router.py` — eligibility, lifecycle, evidence and ranking.
- `fleet.json` — candidate registry.
- `test_router.py` — routing/lifecycle regression.
- `PRIOR_ART_AND_DESIGN.md` — routing design rationale.

Runtime-generated task/result/embedding evidence is intentionally ignored by Git.

## `hermes/`

- `SOUL.md` — always-on GSV Aineko identity.
- `profile_manifest.json` — curated skill declaration.
- `install_profile.py` — reproducible profile installer.
- `skills/exocortex-*/SKILL.md` — Exocortex-owned operational skills.
- `test_install_profile.py` — installation/curation regression.

## `delivery-controller/`

Durable software-delivery state machine.

Key files:
- `delivery.py` — main controller.
- `workspace.py` — isolated workspace handling.
- `tick_all.py` — persistent tick entrypoint.
- `nemosyne_continuous.py` — Nemosyne-specific integration.
- `WORK_REFERENCE_ARCHITECTURE.md` — authority/cognition separation.

## `deploy/`

Machine/service deployment references. Current launchd service inventory is sanitized and declarative; future work should generate concrete service files from authoritative manifests.

## `config/`

Secret-free reference configuration fragments.

## `models/`

Reconstructible local model recipes. Large model blobs are not stored in Git.

## `scripts/`

Survivability and reconstruction tooling.

## Tests

Tests live near their components. For recovery, prioritize:
- deployment tests;
- profile installer tests;
- model-router tests;
- GOMS/Hermes integration tests;
- authority/capability/route tests;
- control-intent HUMAN_ONLY invariants;
- delivery-controller tests.

Historical planning documents under `docs/superpowers/plans/` are evidence of evolution, not current authority when contradicted by newer architecture/runtime docs.
