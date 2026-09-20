# GSV Aineko Skill Catalogue

The skill surface is curated in `hermes/profile_manifest.json`. This is a behavioural control surface, not merely a directory of prompts.

## Exocortex-owned skills

### exocortex-executive
Use for multi-step intents, cross-system work, status/next-step questions, and coordination. Encodes the executive loop, attention gate, context/continuity, routing boundaries, and completion contract.

### exocortex-orchestration
Use for multiple models/agents/machines/repos and long-running/parallel work. Encodes model routing, delegation contracts, supervision, cost/capacity policy, and concurrency boundaries.

### exocortex-recovery
Use for degraded services, failed routes, machine administration, and break-glass recovery. Encodes recovery sequencing, authority modes, host execution and escalation rules.

### exocortex-research
Use for research, evidence synthesis, prior art, experiments, and adversarial evaluation. Encodes claim/evidence separation, admissibility, ABSTAIN, negative-result validity, and reusable research artefacts.

### exocortex-engineering
Use for repository changes, CI failures, refactors and architecture work. Encodes inspect-live-state-first, reuse-before-rebuild, branch/worktree discipline, delegated coding supervision, and verification.

## Supporting generic skills

The reference profile currently includes:
- Hermes runtime management;
- Codex delegation;
- OpenCode delegation;
- GitHub auth/code review/issue-to-PR/issues/PR workflow/repository management;
- systematic debugging;
- test-driven development;
- grounded citations;
- arXiv;
- research paper writing;
- blog monitoring;
- OCR/document tools;
- PDF text editing;
- blocked-page recovery.

## Why curation matters

The reference machine has many more skills available globally. They are intentionally not all injected into GSV Aineko.

Unrelated creative, smart-home, or unsafe/blocked MLOps skills increase prompt noise and weaken the Exocortex role.

The profile installer backs up the existing profile before pruning unrelated skill leaves.

## Skill reconstruction

The Exocortex-owned skills are stored here.

Generic skills are copied from the Hermes skill source declared by the profile installer. If upstream removes or renames one, reconstruction should fail visibly and the profile manifest should be deliberately revised.

## Skill acceptance

After installation:
- `install_profile.py --check` must pass;
- the model-facing skill index must expose all five Exocortex skills;
- behavioural smoke tests should verify the relevant skill changes actual behaviour, not merely file presence.
