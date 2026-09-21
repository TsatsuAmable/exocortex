# State, Secrets, and Backup Boundary

GitHub is the reconstruction source. It is not the memory vault.

## Recovery tiers

### Tier A: source survivability

Stored in GitHub:
- code;
- architecture;
- configuration schemas/examples;
- identity/SOUL;
- skills;
- service topology;
- model recipes;
- migration/schema code;
- acceptance tests.

This is sufficient to create a fresh functioning Exocortex.

### Tier B: continuity state

Stored outside GitHub in encrypted/offline backups.

Reference runtime size on 2026-09-20:
- GOMS data root: approximately 17 GB;
- GSV Aineko Hermes profile: approximately 653 MB.

## Canonical state to protect

### GOMS

Reference root:

`~/Library/Application Support/Aineko/GOMS`

Important continuity files include `goms.sqlite3`, the hot `events.jsonl` segment, ingestion/queue state needed for exact operational resume, migration/version metadata, authority state, and selected Hermes continuity.

Raw evidence, historical deployment snapshots, rotated ledger archives, and other cold material are a separate archive tier. They are intentionally excluded from the routine encrypted hot-continuity bundle by `.statebundle-ignore`; unique evidence must instead be preserved by the archive backup policy and is never deleted merely because it is old.

Neo4j is not canonical if it can be rebuilt from GOMS.

### Local Hermes authority

Reference root:

`~/.hermes/authority`

Contains `state.json` and append-only `audit.jsonl`.

The audit matters because RECOVERY/EMERGENCY must remain auditable while GOMS is unavailable.

### GSV Aineko profile continuity

Reference root:

`~/.hermes/profiles/gsvaineko`

The source-owned identity/skills are reconstructible from Git. Runtime memories, cron definitions, selected sessions, messaging state, and WhatsApp session material may be backed up for continuity.

Do not blindly restore caches or stale generated skill snapshots.

## Secrets

Never commit Remote Commander bearer tokens, provider API/OAuth credentials, WhatsApp credentials/session keys, Manfred tokens, private signing keys, Tailscale auth keys, Neo4j passwords, or reusable sudo/admin credentials.

Commit only variable names, token-file conventions, public keys where safe, and setup/rotation procedures.

## Manfred secret contract

Reference machine-local files include:
- `secrets/manfred-read.token`;
- `secrets/manfred-authority.token`;
- authority public-key file;
- private signing material on the authorised side only.

## State bundle recommendation

Create an encrypted state bundle with:
- manifest;
- SHA-256 hashes;
- creation timestamp;
- Exocortex Git commit;
- schema/migration version;
- host identifier;
- selected continuity files/directories;
- restore order.

Keep at least two physically/provider-independent copies.

The state bundle itself must not be stored in the Exocortex Git repository.

## Restore order

1. Reconstruct code/runtime from Git.
2. Stop mutating services.
3. Restore GOMS state.
4. Restore local authority state/audit.
5. Restore credentials through a secure local mechanism.
6. Restore selected Hermes continuity data.
7. Rebuild replaceable projections such as Neo4j.
8. Start services.
9. Run acceptance checks.
10. Record the recovery event.

## Regenerate rather than back up

Prefer regeneration for virtual environments, caches, skill prompt snapshots, Neo4j projection, public model downloads, and deployment release directories.

A backup strategy that preserves every cache but loses canonical GOMS is backwards.
