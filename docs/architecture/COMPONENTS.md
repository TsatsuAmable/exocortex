# Component Inventory

This document distinguishes canonical Exocortex components from replaceable external dependencies.

## GSV Aineko / Hermes

**Role:** executive interface, orchestrator, recovery actor, human-attention gate.

**Source in this repo:**
- `hermes/SOUL.md`
- `hermes/profile_manifest.json`
- `hermes/install_profile.py`
- `hermes/skills/exocortex-*/SKILL.md`

**External runtime:** Nous Research Hermes Agent.

**Known-good pin:** Hermes Agent 0.21.1, upstream `f6ddd89692dff1f900983a16208f39a1485a14eb`.

The upstream runtime is replaceable in principle, but the Exocortex identity and skills are owned here.

## GOMS

**Role:** canonical semantic/provenance memory, governance, control intents, project context, claims/evidence, branches/checkpoints, failure/lesson history.

**Source:** `goms-v2/`

Important groups:
- canonical store/schema: `goms_store.py`, `schema.sql`
- MCP surface: `mcp_server.py`
- context: `exocortex_context.py`
- governance/control: `governor*.py`, `control_intents*.py`
- graph projection: `graph_backend.py`, `neo4j_projection.py`
- distillation: `distillation_*.py`
- health/topology: `*_health_controller.py`, `topology_*.py`
- Hermes integration: `hermes_*.py`
- Manfred integration: `manfred_*.py`

Canonical state lives outside Git.

## Model router

**Role:** choose cognitive substrate without coupling cognition to authority.

**Source:** `compute/model-routing/`

Inputs include:
- candidate fleet;
- task family;
- privacy;
- context requirement;
- agent/tool requirement;
- candidate qualification;
- lifecycle/retirement;
- historical task outcomes.

The router intentionally prefers transparent evidence-driven logic over an unvalidated learned router.

## Execution fabric

**Role:** effect changes on machines through explicit authorised routes.

Current routes:
- Hermes machine tools;
- Remote Commander MCP;
- Tailscale-discovered remote execution routes.

Relevant source:
- `goms-v2/hermes_capability_graph.py`
- `goms-v2/hermes_fabric_discovery.py`
- `goms-v2/hermes_route_selector.py`
- `goms-v2/hermes_machine_tools.py`
- `goms-v2/hermes_execution_supervisor.py`

## Authority subsystem

**Role:** local machine authority independent of GOMS health.

Source:
- `goms-v2/hermes_authority.py`
- `goms-v2/hermes_macos_adapter.py`
- `goms-v2/hermes_attention_gate.py`

Modes:
- OBSERVE
- OPERATE
- ADMIN
- RECOVERY
- EMERGENCY

Local audit state is intentionally outside GOMS so recovery remains auditable while GOMS is down.

## Manfred

**Role:** mobile/control-plane projection and command surface.

Current services:
- read proxy, typically port 8794;
- control HTTP surface, loopback port 8793;
- authority proxy, typically port 8795 on an authenticated/private network binding.

Source:
- `goms-v2/manfred_read_proxy.py`
- `goms-v2/manfred_http.py`
- `goms-v2/manfred_authority_proxy.py`
- `goms-v2/manfred_control.py`
- `goms-v2/manfred_projection.py`

Tokens/private keys are machine-local state.

## Delivery Controller

**Role:** durable long-running software-delivery supervision.

Source: `delivery-controller/`

It owns deterministic job state, GitHub/CI observation, checkpoints and authority gates. LLMs are bounded reasoning providers rather than transaction authorities.

## Neo4j

**Role:** replaceable graph projection/query engine.

Canonical GOMS meaning must remain reconstructible without Neo4j. Neo4j currently listens locally on Bolt/HTTP in the reference deployment.

## Ollama and model providers

**Role:** local and subscription-backed inference substrate.

Current fleet includes:
- Ollama cloud candidates;
- local Qwen/GSV Aineko candidates;
- OpenCode candidates;
- Google subscription route candidates.

Qualification state is recorded in `compute/model-routing/fleet.json`.

## Remote Commander

**Role:** authorised host/machine effector exposed through MCP.

It is external to this repository and must be configured separately. The Exocortex depends on its capability contract, not its internal implementation.

## Tailscale

**Role:** private reachability between Exocortex machines/services.

Addresses are configuration, never architecture. Do not commit current Tailnet IPs as requirements.

## Related repositories

See `docs/reconstruction/REPOSITORY_MAP.md` for canonical/legacy/adjacent status.
