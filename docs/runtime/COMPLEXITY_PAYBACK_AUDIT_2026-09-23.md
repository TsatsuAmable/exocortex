# Exocortex Complexity Payback Audit — 2026-09-23

## Decision rule

A component earns its complexity only if it measurably reduces human attention, enables autonomous execution, improves recovery, preserves required authority, or prevents expensive mistakes. Otherwise it should be merged, quieted, deferred, or removed.

## Evidence from the live system

- The post-brake Aineko `Status?` turn used 4 API calls, down from the pre-brake `What about 811?` turn at 21 calls. The turn still took 225 s because the old transcript crossed the compression threshold and spent ~203 s compacting.
- The next two WhatsApp turns completed in 12.4 s / 3 calls and 31.5 s / 2 calls after compaction.
- The retired generic Hermes gateway was previously crash-looping every ~30 s. Its plist still existed in LaunchAgents, so unload alone was not reboot-safe.
- The ChatGPT replication worker is explicitly deferred, currently has an empty queue, and has historical Tailscale-SSH authorization failures.
- The hourly Notion wrapper already performs deterministic sync before starting Hermes. Recent LLM stewardship cycles repeatedly reported no inbound edits, no writes, and no human attention required.
- ChatGPT ingest has real historical value (hundreds of non-zero ingest events) but recent polling is mostly no-op and generates large logs.

- Topology, infrastructure-health, cognition-health, distillation metrics, and the Agalmic controller emit large volumes of unchanged snapshots. They are useful signals but their present cadence/logging is disproportionate.
- Distillation metrics has also accumulated repeated Python-compatibility tracebacks because the launch job used the system Python while the code requires a newer interpreter.

## Disposition

| Component | Disposition | Reason |
| --- | --- | --- |
| GOMS canonical state / intent ledger | KEEP | Durable state, idempotency, evidence, recovery |
| Aineko bounded intent worker | KEEP | Moves sustained work out of the human-facing session |
| gsvaineko gateway | KEEP | Primary human control plane |
| generic `ai.hermes.gateway` | REMOVE live | Duplicate authority and demonstrated crash-loop |
| ChatGPT replication worker | DEFER / disable live | Explicitly deferred; idle; not proven failover |
| Notion deterministic sync | KEEP | Performs the actual governed projection/capture |
| Notion hourly LLM steward | CONDITIONAL | Judgment only when inbound edit or sync failure exists |
| ChatGPT GOMS ingest | KEEP, QUIET | Proven ingestion value; suppress/reduce no-op noise later |
| topology / infra / cognition health | MERGE or QUIET | Useful observability, excessive independent polling/logging |
| distillation metrics | KEEP, SLOW | Useful backlog evidence; fix interpreter and reduce cadence |
| Agalmic/scarcity controller | DEFER REVIEW | Current runs repeatedly find no blocked scarcity/capability match |
| survivability audit | KEEP | Direct recovery/reconstruction value |
| delivery controller | KEEP | Direct autonomous software-delivery value |

## Immediate subtraction tranche

1. Make the Notion LLM pass conditional on deterministic inbound capture or deterministic-sync failure.
2. Retire the legacy generic Hermes gateway plist from the live LaunchAgents directory.
3. Disable the deferred ChatGPT replication launch job.
4. Run distillation metrics with the Exocortex/GOMS venv and reduce its cadence from 60 s to 900 s.
5. Do not add sub-agents or context architecture during this tranche.

## Next candidates, evidence required first

- Consolidate topology, infrastructure, and cognition health into one sampled health pass only if their state transitions and repair ownership can be preserved.
- Reduce ChatGPT ingest churn by logging only state changes/non-zero ingests rather than weakening continuity.
- Disable or event-trigger the Agalmic controller if a review confirms it has produced no actionable scarcity transition over a representative window.
- Replace transcript growth with fresh scoped sessions only after measuring post-compaction behavior under normal use.

## Acceptance metric

Exocortex v1 is earning its complexity when ordinary high-level intents require materially fewer human follow-ups than direct tool use, while failures recover without transcript growth, duplicate supervisors, or recurring no-op model work.
