# Rebuild the Exocortex from GitHub

This is the survivability procedure. It is written for either a human operator or an agent.

## Recovery modes

### Stateless reconstruction

Goal: rebuild a functioning Exocortex with fresh state from source and public/declared dependencies.

Requires this repository, package/model sources, and credentials only for optional cloud providers. It does not require the original GOMS database.

### Stateful recovery

Goal: restore prior Exocortex continuity.

Requires stateless reconstruction plus a separately protected state bundle described in `STATE_AND_SECRETS.md`.

## 1. Prepare the host

Reference platform is macOS Apple Silicon. Install Git/GitHub CLI, Python 3.11 for the pinned Hermes runtime, Python >=3.12 plus `uv` for GOMS, Docker, Node, Ollama, Neo4j, and Tailscale if remote fabric/Manfred paths are required.

Remote Commander is an external optional-but-important host execution dependency. Without it, Hermes loses the tested macOS host-effector route.

## 2. Clone the canonical repository

```bash
git clone git@github.com:TsatsuAmable/exocortex.git
cd exocortex
python3 scripts/reconstruction_check.py
```

## 3. Create the GOMS environment

```bash
cd goms-v2
uv sync
cd ..
```

GOMS declares Python >=3.12. Do not assume system Python contains its dependencies.

For stateful recovery, restore the GOMS data directory before starting mutating services.

## 4. Install the Exocortex runtime slice

```bash
python3 exocortex_deploy.py \
  --prefix ~/.local/share/exocortex \
  --goms-data-root "${HOME}/Library/Application Support/Aineko/GOMS"
```

The installer atomically rotates the previous runtime to `.previous`.

Current manifest-packaged components are GOMS code, model router, and the Hermes/GSV Aineko profile package. The live service graph is broader; continue with `docs/runtime/SERVICE_TOPOLOGY.md`.

## 5. Install Hermes at the known-good pin

Clone/install `NousResearch/hermes-agent` and check out:

`f6ddd89692dff1f900983a16208f39a1485a14eb`

Use Python 3.11 compatible with that release.

Before starting Hermes, apply the Exocortex-qualified compatibility patch. It makes
main-provider fallback context-safe: a smaller fallback is skipped when the live
request cannot fit its safe input window, and Ollama runtime context is re-resolved
when the fallback model changes.

```bash
python3 ~/.local/share/exocortex/current/hermes/apply_hermes_patches.py \
  --hermes-home ~/.hermes/hermes-agent
```

Do not force this patch onto another Hermes revision. The applicator fails closed
when the checkout is not at the qualified base commit.

Then install the Exocortex profile:

```bash
python3 ~/.local/share/exocortex/current/hermes/install_profile.py \
  --profile-home ~/.hermes/profiles/gsvaineko \
  --skill-source ~/.hermes/skills
```

## 6. Rebuild the local fallback model

```bash
ollama pull qwen3.5:4b
ollama create gsvaineko-core:v1 -f models/gsvaineko-core.Modelfile
```

Cloud/subscription models are optional and must be requalified before promotion.

## 7. Apply the Hermes configuration fragment

Use `config/hermes.gsvaineko.fragment.yaml` as the reconstruction reference, not as a secret-bearing full config.

Configure the GOMS MCP command/environment, Remote Commander URL/token locally, primary/fallback model, Docker sandbox, messaging surface, and toolsets.

## 8. Restore or initialize GOMS state

For fresh state, initialize schema/migrations/seed using GOMS tooling and verify the MCP server starts against the new data root.

For restored state, restore the state bundle before service startup. Verify hashes/ownership and database integrity before enabling workers.

## 9. Configure external services

Configure Neo4j, Ollama, Remote Commander, Tailscale routes if used, Manfred secret material if required, provider OAuth/API credentials, and WhatsApp session if desired.

See `docs/runtime/REFERENCE_CONFIGURATION.md` and `STATE_AND_SECRETS.md`.

## 10. Install/start services

Use `docs/runtime/SERVICE_TOPOLOGY.md` and `deploy/launchd/service-inventory.example.json` as the current reference graph.

The current macOS deployment uses launchd. Exact paths must be rendered from chosen install roots.

Do not enable replication/failover merely because historical launch agents exist. Further replication work was intentionally deferred until v1 completion.

## 11. Acceptance

Run the checks in `docs/reconstruction/ACCEPTANCE_CHECKLIST.md`.

A reconstruction is not complete merely because processes start. It must prove GSV Aineko identity, GOMS durable state, model routing, authority separation, machine execution/recovery, persistence, and restart survivability.

## 12. Record the reconstruction

Record the repository commit, host/platform, dependency versions, state bundle ID if any, deviations from reference configuration, and acceptance results.

Store the record in GOMS and, without secrets, in GitHub issues/logs as appropriate.

### Restore bounded recurring cognition

After Hermes profile installation, recreate/update the zero-LLM recurring-job bindings from the versioned scheduled-intent specs:

```bash
python3 ~/.local/share/exocortex/current/scripts/install_bounded_cron_jobs.py --profile gsvaineko
```

This copies the versioned enqueue wrappers into the Hermes script sandbox and makes the recurring jobs `no-agent`. Their scheduler turns only enqueue approved GOMS intents; `org.aineko.intent-worker` executes those intents in fresh bounded contexts.
