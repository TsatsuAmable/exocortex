---
name: exocortex-orchestration
description: "Route, delegate, supervise, and verify multi-agent work."
version: 0.1.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [exocortex, orchestration, delegation, models, workers]
---

# Exocortex Orchestration

Use when work spans models, agents, machines, repositories, long-running workers, or parallel streams.

## Decide before spawning

Delegate only when specialization, independence, parallelism, context isolation, or a better cognitive substrate provides real leverage.

Do not spawn agents merely to create activity.

## Model routing

For substantial delegated cognition, call mcp__goms__model_route with:
- task family;
- privacy class;
- direct vs agent mode;
- required context.

Prefer the highest-ranked **qualified active** route. Treat provisional routes as experiments and unqualified/retiring routes as non-primary.

Already-paid, free, or local capacity is preferable when capability is sufficient. Quality requirements outrank token thrift.

## Delegation contract

Every delegated unit should have:
- a concrete objective;
- relevant context and authoritative source locations;
- boundaries and non-goals;
- expected artefact/effect;
- verification criteria;
- a return channel.

Do not ask the human to relay work between agents.

## Parallelism

Parallelise independent work. Serialize tasks that share mutable state, authority, or a dependency boundary.

For repositories, use isolated branches/worktrees where concurrent writes could collide.

## Supervision

Delegation is not completion.

Track worker state, inspect outputs, recover stalled routes, and verify the final effect. If a worker fails, classify whether the failure is model, tool, permission, environment, task specification, or architecture before choosing the next route.

Record durable capabilities, failures, and useful routing evidence in GOMS so future routing improves.

## Cost and capacity

Avoid pinning critical workflows to one provider. Preserve local/offline survival.

Use stronger or more expensive models selectively for adjudication, difficult recovery, or tasks where evidence shows cheaper routes are inadequate.
