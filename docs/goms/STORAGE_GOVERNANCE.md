# GOMS Storage Governance

## Purpose

GOMS storage is governed by information temperature, not age alone.

- **Hot**: canonical operational state needed for normal Exocortex operation.
- **Warm**: source evidence and provenance needed to explain or re-derive knowledge.
- **Cold**: historical rollback material and archived ledgers that are not part of ordinary reasoning.

Unique evidence is not disposable merely because it is old.

## Controller

\`goms-v2/storage_governor.py\` is the single storage-lifecycle controller.

It provides:

- inventory and hot/warm/cold byte accounting;
- deterministic dry-run plans;
- deployment-snapshot retention;
- SHA-256 exact raw duplicate detection;
- guarded apply;
- hash-chain-preserving ledger rotation;
- archive verification;
- continuity-proof validation;
- scheduled idempotent operation;
- machine-readable JSON reports.

The default policy is \`goms-v2/storage_policy.json\`.

## Safety model

Planning never deletes data.

Apply requires:

1. a plan produced for the same root and policy;
2. an unexpired plan;
3. a fresh continuity proof bound to an encrypted state bundle;
4. unchanged deployment fingerprints;
5. exact SHA-256 equality for every raw duplicate;
6. a valid ledger chain before rotation.

If any preflight check fails, apply stops before mutation.

Ledger rotation is an additional explicit switch. It uses the same stable \`events.lock\` inode as \`GomsStore.append_event\`, so writers cannot retain a descriptor to the old ledger during an atomic rotation.

## Deployment retention

The policy keeps the latest deployment snapshots plus explicitly protected anchors.

Historical deployment directories outside that set are recoverable from:

- canonical Git;
- the current live state;
- the encrypted continuity bundle.

Their presence in the hot GOMS tree is therefore not itself a reason to retain them indefinitely.

## Raw evidence

Raw evidence deletion is permitted only for **byte-identical SHA-256 duplicates**.

Structurally similar conversations, alternate serializations, earlier revisions, or different captures are not duplicates for this purpose and are retained.

The initial live audit on 2026-09-20 found 1,604 JSON files under the ChatGPT-live archive and **zero exact duplicate groups**, despite apparent representational duplication. No raw files should therefore be removed by the first cleanup.

## Ledger archives

When \`events.jsonl\` exceeds the configured threshold:

1. acquire the stable ledger lock;
2. verify the current hash chain;
3. gzip the complete old ledger into \`cold/ledger/\`;
4. verify the compressed archive round-trip;
5. write an archive manifest;
6. replace the hot ledger with one rotation-anchor event whose \`prev_line_sha256\` points to the last archived line;
7. verify the new hot chain.

This bounds hot ledger size without severing audit continuity.

## Continuity versus archive

The encrypted Exocortex state bundle is the **hot continuity tier**. It should not recursively preserve obsolete deployment snapshots or cold archives.

The repository-level \`.statebundle-ignore\` excludes:

- \`deployments\`
- \`cold\`
- \`quarantine\`
- \`storage-governance\`

Raw evidence remains a separate archive concern and is intentionally outside the hot continuity bundle. It is not deleted by storage governance unless exact duplication is proven.

A complete archival backup policy may copy warm/cold evidence independently from the smaller continuity bundle.

## Scheduled operation

The canonical service inventory runs the storage governor daily.

Scheduled mode always writes:

- \`storage-governance/latest-plan.json\`
- \`storage-governance/latest-report.json\`

If a fresh continuity proof is available and policy allows automatic apply, authorized redundancy is reclaimed. If the proof is absent or stale, the run remains a successful dry-run and records the apply gate instead of interrupting the human.

## Operating sequence

For an explicit cleanup:

1. create encrypted state bundle with \`scripts/state_bundle.py create\`;
2. verify it with \`scripts/state_bundle.py verify\`;
3. create a storage continuity proof from those two JSON outputs;
4. generate and inspect the deterministic plan;
5. apply;
6. run \`storage_governor.py verify\`;
7. verify representative GOMS context and service health;
8. retain the machine-readable before/after report.

## First live cleanup result (2026-09-20)

Baseline: total ~17 GiB (deployments ~11 GiB, raw ~4.5 GiB / ~12,017 files, live goms.sqlite3 ~736 MiB, events.jsonl ~355 MiB).

Executed with verified continuity bundle + plan pinned to the live ledger head:

- 4,087 actions applied, 0 skipped;
- 9.92 GB reclaimed from 28 obsolete deployment snapshot directories;
- 0.53 GB reclaimed from 4,058 raw files, each SHA-256-proven as an exact duplicate with its canonical twin retained;
- events.jsonl rotated: 355.5 MB hot ledger -> 69.3 MB cold archive with hash-chain continuity preserved across rotation;
- total: 17 GiB -> 7.37 GB.

Post-cleanup steady inventory (bytes): total 7,371,534,278; hot 758,480,960 (live DB 758,300,672 + ledger 8,256); warm raw 4,292,016,815; cold 69,273,016; other 4,705,999; quarantine 0.

Verification after cleanup: governor verify clean (archives + chain continuity); GOMS services live (brief + agalmic state); scheduled mode exercised 3x (fail-closed without proof, auto-apply with proof, 0-action idempotent steady state).

The machine-readable record is \`storage-governance/history/20260920T211331Z-apply.json\` (apply) and the scheduled reports under \`storage-governance/\`.

## Success metric

The primary metric is not total bytes alone.

The desired state is:

- small bounded hot state;
- deduplicated warm provenance;
- independently recoverable cold history;
- no loss of unique evidence;
- no routine human maintenance.
