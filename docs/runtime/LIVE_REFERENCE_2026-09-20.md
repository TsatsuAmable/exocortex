# Sanitized Live Reference — 2026-09-20

This is a diagnostic snapshot of the known-good Mac deployment. It is not a mandate to preserve every version or service forever.

## Host/runtime

Reference host: macOS Apple Silicon MacBook Pro.

Observed versions:
- Hermes Agent 0.21.1 / upstream `f6ddd89692dff1f900983a16208f39a1485a14eb`
- Hermes Python 3.11.14
- Node 26.8.2
- Docker 29.2.1
- Ollama server 0.33.2 / CLI 0.33.3
- Neo4j 2026.07.1
- Tailscale 1.102.4

## State footprint

Observed:
- GOMS root: ~17 GB
- GSV Aineko Hermes profile: ~653 MB

This is why Git reconstructs software while encrypted state bundles restore continuity.

## Main local endpoints

- Remote Commander MCP: `127.0.0.1:8771`
- Ollama API: `127.0.0.1:11434`
- Hermes WhatsApp bridge: `127.0.0.1:3000`
- Neo4j Bolt: `127.0.0.1:7687`
- Neo4j HTTP: `127.0.0.1:7474`
- Manfred control: `127.0.0.1:8793`
- Manfred read/authority may bind to private-network addresses configured locally.

Private network addresses are deliberately not recorded here.

## Model reference

At this date:
- `glm-5.3-flash:cloud`: qualified active reference primary.
- `gsvaineko-core:v1`: qualified local fallback.
- `deepseek-v4-flash:cloud`: qualified but draining for announced retirement.
- several other cloud/OpenCode/local candidates: provisional/unqualified per `fleet.json`.

The fleet file is the authority; this paragraph is historical.

## GSV Aineko

Active personality: `exocortex`.

The live behavioural smoke test correctly identified GSV Aineko as the Exocortex executive and stated that authorised mechanical work should be performed through Exocortex tools rather than handed back to the human.

## Service state

The live host included Hermes, GOMS queue/workers/semantic daemon, health/topology controllers, Manfred surfaces, delivery controller, Neo4j, Remote Commander and Ollama.

See the sanitized launchd inventory for wiring.

## Known gaps at this snapshot

- Service definitions are not yet generated from one cross-platform manifest.
- systemd packaging is absent.
- full clean-machine second-host acceptance has not yet been completed.
- recovery authority still needs expiring/scoped lease hardening.
- offline authority audit reconciliation remains incomplete.
- state export/import is documented but not yet a fully automated encrypted bundle workflow.
- external model qualification needs ongoing lifecycle/digest monitoring.
