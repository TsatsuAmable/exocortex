# Security and Secret Handling

The Exocortex repository is reconstructive, not secret-bearing.

Never commit API/OAuth secrets, bearer tokens, private keys, WhatsApp session credentials, Tailscale auth keys, database passwords, reusable administrator credentials, or live canonical databases.

Commit variable names, endpoint defaults, schemas, public keys where intended for distribution, secret-file path conventions, generation/rotation procedures, and redacted service inventories.

## Authority

Model capability and machine authority are separate.

The authority state machine is local and auditable. Elevated modes require explicit human authorization. Machine recovery does not grant semantic approval over HUMAN_ONLY intents.

## Remote surfaces

Prefer loopback for control surfaces. Expose non-loopback services only through authenticated/private transport with explicit client restrictions.

## Accidental secret commit

If a secret is committed:
1. rotate/revoke it immediately;
2. remove it from the current tree;
3. rewrite Git history if exposure warrants it;
4. invalidate cached/runtime copies;
5. record the incident and rotation.

Deleting the line in a later commit does not unexpose the secret.
