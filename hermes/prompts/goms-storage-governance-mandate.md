# GOMS Storage Governance and Compaction Mandate

You are GSV Aineko acting as the Exocortex executive.

The human principal has authorized you to fix and automate GOMS storage growth. This is accepted execution scope.

## Live problem

Canonical GOMS root:
\`~/Library/Application Support/Aineko/GOMS\`

Latest verified measurements before this mandate:

- total: ~17 GiB
- \`deployments/\`: ~11 GiB, including many copied historical GOMS databases
- \`raw/\`: ~4.5 GiB / ~12,017 files
- live \`goms.sqlite3\`: ~736 MiB
- \`events.jsonl\`: ~355 MiB
- canonical semantics remain comparatively small: roughly 353 semantic assertions versus ~87k evidence-heavy entities and ~108k distillation segments

Prior audit found strong evidence of duplicate raw ChatGPT representations and many redundant deployment snapshots.

The objective is not "make the directory small". The objective is:

**keep hot GOMS compact and useful while preserving provenance, continuity and recoverability.**

## Desired storage model

Implement a governed three-temperature model:

1. **Hot**: live canonical GOMS, current operational state, current semantic indexes, active branches/intents, recent audit window.
2. **Warm**: deduplicated evidence/provenance required to explain or re-derive canonical knowledge.
3. **Cold**: compressed raw archives, historical ledger segments, historical deployment/recovery artifacts not needed for routine operation.

Do not delete unique evidence merely because it is old.

## Required implementation

Inspect current main and existing state-bundle/reconstruction/service-generation machinery before adding code. Reuse it.

Build an automated storage governor with:

- inventory and size accounting;
- cryptographic hashing and duplicate detection;
- deployment snapshot retention policy;
- raw-evidence deduplication policy;
- event-ledger rotation/archive policy that preserves verifiable chain continuity;
- explicit hot/warm/cold/quarantine classifications;
- dry-run by default;
- apply mode with a deterministic plan;
- verification mode;
- machine-readable report/metrics;
- rollback/recovery metadata;
- age/size/anchor-aware retention;
- scheduled execution through the existing launchd/systemd service-generation architecture;
- GOMS/Manfred-visible health/attention only for real storage faults or human decisions.

Prefer one coherent controller/policy over scattered cleanup scripts.

## Safety invariants

Before destructive reclamation:

1. create and verify a fresh continuity state bundle using the existing state-bundle machinery;
2. identify current live state and protected recovery anchors;
3. prove exact duplicates by content hash before removing a raw duplicate;
4. preserve at least the current live DB and explicit known-good rollback/reconstruction anchors;
5. never delete the canonical live DB, secrets, authority audit, current continuity bundle, or unique raw evidence;
6. do not VACUUM or rewrite the live DB while writers are active unless using an established safe procedure;
7. verify recoverability after cleanup.

For deployment snapshots, verified obsolete copies outside the retention/anchor set may be deleted after the verified state bundle exists.

For raw evidence, exact duplicate copies may be removed after hash/metadata proof. Unique raw content should be moved/represented as cold archive, not deleted.

For other uncertain material, quarantine or archive rather than destroy.

## First live cleanup

After tests are green and the dry-run is reviewed by your own verification logic:

- perform the first live cleanup within these rules;
- record bytes reclaimed by class;
- verify GOMS services still operate;
- verify the continuity bundle;
- verify a representative canonical context/brief still works;
- record the before/after storage report in GOMS and repository docs.

Do not ask the human to run commands.

## Automation

The fix is incomplete unless future growth is governed automatically.

Schedule the governor at an appropriate low-frequency cadence. It should:

- inventory regularly;
- prune only policy-authorized redundant deployment snapshots;
- dedupe only cryptographically identical raw files;
- rotate/archive the ledger at bounded size/age while preserving verification;
- emit metrics for hot/warm/cold bytes, reclaimable bytes, duplicates, protected anchors and last verified cleanup;
- escalate only if a human value/retention decision is truly required.

Use the Attention Budget Market once merged/available; until then follow the same A0–A3 principle manually and do not generate routine attention.

## Success criteria

- hot operational GOMS is materially smaller and stops unbounded growth;
- no unique evidence is lost;
- continuity/reconstruction remains verified;
- cleanup is reproducible from Git;
- automation is installed through existing service-generation contracts;
- tests cover retention anchors, hash dedupe, chain/archive verification, dry-run/apply, failure rollback and idempotence;
- code/docs/tests are committed and pushed on the dedicated branch;
- open a PR against main;
- leave durable GOMS branch/checkpoint state with exact results and next action.

Begin by auditing actual live structures and existing deployment/state-bundle code. Then implement, test, perform the bounded live cleanup, verify, publish, and report only final results or a genuine human-only decision.
