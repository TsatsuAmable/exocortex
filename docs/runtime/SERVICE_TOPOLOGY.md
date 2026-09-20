# Service Topology

The live Exocortex is a composition of independently running services. The top-level deployment manifest does not yet generate all of them.

## Hermes

`ai.hermes.gateway-gsvaineko`

Purpose: messaging gateway, GSV Aineko turns, MCP/tool discovery.

## GOMS distillation

- `org.aineko.goms-distillation-queue`
- `org.aineko.goms-distillation-workers`
- `org.aineko.goms-distillation-semantic`

Purpose: durable queue, extraction workers, semantic promotion/materialization.

Workers consume the shared model router through `AINEKO_MODEL_ROUTER_PATH`.

## GOMS maintenance and health

Reference services include topology controller, infrastructure health controller, cognition health controller, semantic maintenance, distillation metrics, queue hygiene, guardian review, and Agalmic controller where enabled.

They are deterministic/persistent supervision loops, not conversational agents.

## Manfred

- `org.aineko.goms-manfred-read`
- `org.aineko.goms-manfred-control`
- `org.aineko.goms-manfred-authority`

Read, control, and authority surfaces are intentionally separated.

## Delivery Controller

`com.aineko.delivery-controller`

Persists delivery transaction state and observes GitHub/CI without continuously running a model.

## Neo4j

Currently managed as a local service. It is a projection/query substrate, not canonical GOMS truth.

## External host services

### Remote Commander

Reference endpoint: loopback MCP port 8771.

Provides authorised host filesystem/process/command effectors when Hermes' normal terminal is Docker-sandboxed.

### Ollama

Reference API port 11434.

Provides local models and the current Ollama cloud/subscription bridge.

### Tailscale

Provides private reachability for remote/Manfred paths. Exact addresses are machine-local configuration.

## Historical/live-but-not-v1-critical jobs

Some launchd jobs may exist for ChatGPT ingestion/export watch, replication, vault sync, and prior integrations. Presence on one machine does not make them a core reconstruction requirement.

Further GOMS replication/failover was intentionally deferred until Exocortex v1 completion.

## Service specification

Sanitized reference inventory:

`deploy/launchd/service-inventory.example.json`

It records labels, program/arguments, working roots, schedules/keepalive, required environment names, and log locations. Secrets/private-network addresses are placeholders.

## Portability gap

Current v1 work still needs generated service definitions from one authoritative manifest, launchd/systemd adapters, dependency/health ordering, and idempotent install/uninstall.

Until then, this document plus the sanitized inventory is the manual reconstruction authority.
