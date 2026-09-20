# Reference Configuration

This document records the tested configuration shape without committing live secrets.

## Files

- `config/exocortex.env.example` — machine-local environment contract.
- `config/hermes.gsvaineko.fragment.yaml` — essential Hermes profile fragment.
- `hermes/profile_manifest.json` — curated skill surface.
- `compute/model-routing/fleet.json` — model candidates and qualification state.
- `deploy/launchd/service-inventory.example.json` — sanitized macOS service reference.

## Reference paths

```text
runtime release           ~/.local/share/exocortex/current
GOMS canonical data       ~/Library/Application Support/Aineko/GOMS
GSV Aineko profile        ~/.hermes/profiles/gsvaineko
Hermes authority state    ~/.hermes/authority
Hermes installation       ~/.hermes/hermes-agent
```

Source and state must remain separate.

## Hermes

Reference behaviour:
- primary personality: `exocortex`;
- terminal backend: Docker;
- persistent sandbox;
- GOMS and Remote Commander exposed as toolsets;
- GOMS MCP launches packaged `mcp_server.py`;
- GOMS MCP receives canonical state root through `GOMS_HOME`;
- model router path points to packaged router;
- Remote Commander token remains local.

Current reference primary model is `glm-5.3-flash:cloud`; this is operational state, not identity. Current local fallback is `gsvaineko-core:v1`.

## Remote Commander

Reference MCP endpoint: `http://127.0.0.1:8771/mcp`.

Treat it as a default, not an architectural constant. Its bearer token is local secret state.

## Neo4j

Reference local endpoints:
- Bolt: `127.0.0.1:7687`
- HTTP: `127.0.0.1:7474`

Neo4j is a replaceable projection. Keep credentials local.

## Manfred

Current code defaults:
- control HTTP: loopback port 8793;
- read proxy: port 8794;
- authority proxy: port 8795.

Do not commit Tailnet addresses. Bindings/client allowlists are environment configuration.

## Ollama

Reference API:
- `http://127.0.0.1:11434`
- OpenAI-compatible: `http://127.0.0.1:11434/v1`

Local fallback recipe is stored under `models/`.

## Known-good dependency reference

On 2026-09-20:
- Hermes Agent 0.21.1 / upstream `f6ddd896...`;
- Python 3.11.14 for Hermes;
- GOMS Python >=3.12;
- Node 26.8.2;
- Docker 29.2.1;
- Ollama 0.33.2 server / 0.33.3 CLI;
- Neo4j 2026.07.1;
- Tailscale 1.102.4.

Newer versions are allowed only after acceptance testing.
