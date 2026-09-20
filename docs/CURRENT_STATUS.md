# Current Exocortex Reconstruction Status

Date: 2026-09-20

## Reconstructible from Git

- GOMS v2 source/schema/MCP/governance/distillation/Manfred integration.
- Shared model router and candidate fleet.
- GSV Aineko SOUL, personality, curated skill manifest and installer.
- Hermes/GOMS integration and authority/capability/route logic.
- Delivery controller.
- Atomic runtime-slice deployment.
- Local fallback model recipe.
- Architecture and reconstruction documentation.
- Sanitized launchd service topology.
- Secret/configuration contracts.
- Reconstruction self-check and acceptance checklist.

## Requires public/upstream dependency retrieval

- Hermes Agent runtime.
- Ollama/base models.
- Neo4j.
- Docker.
- Tailscale where private fabric is used.
- Remote Commander implementation/runtime.
- ordinary Python/Node/package dependencies.

## Requires private/non-Git continuity material for stateful recovery

- canonical GOMS state;
- Hermes authority state/audit;
- provider/Remote Commander/Manfred credentials;
- selected GSV Aineko runtime/session continuity;
- messaging credentials/sessions.

## Not yet fully automated

- whole-system service generation/install;
- systemd portability;
- second-machine clean reconstruction;
- encrypted state-bundle creation/restore;
- independent rescue executor beyond current recovery routes;
- scoped/expiring authority leases;
- offline audit reconciliation;
- provider digest-based automatic requalification.

## Survivability claim

The repository now contains enough architectural, configuration, source, identity, service, and recovery information for a competent human or agent to reconstruct a fresh Exocortex without relying on undocumented original-machine knowledge.

Full continuity additionally requires the separate state/secret backup tier.

This claim should be tested periodically by clean-room reconstruction rather than trusted indefinitely.

## GitHub CI status

The reconstruction workflow is committed under `.github/workflows/reconstruction.yml`.
On 2026-09-20 GitHub-hosted jobs for this private repository were blocked before runner startup by the account billing/spending state. This is an infrastructure/account condition, not a test failure.

Until that external condition is cleared, run `scripts/verify_reconstruction.sh` locally. The same reconstruction tests were green locally before publication.
