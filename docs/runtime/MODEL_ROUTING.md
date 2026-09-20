# Model Routing

## Purpose

The Exocortex depends on a capability class, not a single provider/model.

Source: `compute/model-routing/router.py`  
Fleet: `compute/model-routing/fleet.json`

GOMS exposes the router through `mcp__goms__model_route`; GOMS distillation workers also use the same authority.

## Eligibility

Candidates are excluded when disabled/unqualified, privacy-incompatible, lacking required tool use, lacking context capacity, or retired.

## Ranking

Current ordering considers:
1. lifecycle penalty;
2. qualification;
3. known-good evidence;
4. cold-start rank;
5. marginal cost;
6. latency;
7. resource class;
8. estimated success.

Near-retirement models are drained even when historically successful.

For non-general task families, cross-family success alone is not enough to mark a candidate known-good. Family-specific evidence is required.

## Provider classes

The fleet can represent local Ollama, Ollama subscription/cloud, OpenCode/free, Google subscription, future ChatGPT/Codex OAuth, and other adapters.

Qualification state is operational evidence, not a permanent endorsement.

## Identity boundary

GSV Aineko is independent of selected model.

Switching model does not change Exocortex identity, GOMS truth, machine authority, control-intent approval, or human principal.

## Local survival route

Reference offline fallback: `gsvaineko-core:v1`, rebuilt from `models/gsvaineko-core.Modelfile`.

A working local fallback is part of survivability even if quality is lower than cloud primaries.

## Lifecycle hardening

Aliases may change underlying versions. Future qualification should bind to provider/model version or digest and automatically re-run regression tests when identity changes.
