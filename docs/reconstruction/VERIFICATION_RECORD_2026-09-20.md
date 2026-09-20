# Reconstruction Verification Record — 2026-09-20

## Repository

Canonical remote: `TsatsuAmable/exocortex` (private)

Verified remote commit:

`6b85513b8363aaa039f152287587a385da874781`

## Procedure

A fresh clone was created from GitHub into a disposable directory outside the development worktree.

The following were executed from that clone:

1. `python3 scripts/reconstruction_check.py`
2. deployment regression test;
3. model-router regression test;
4. `exocortex_deploy.py` into a blank runtime prefix;
5. verification that GOMS, model router, Hermes profile, and delivery controller were present in the new runtime;
6. verification that no `goms.sqlite3` was copied into the release;
7. `uv sync --frozen` inside `goms-v2`;
8. 48 focused GOMS/model-router/authority/capability/route tests;
9. GSV Aineko profile installer regression.

## Result

**PASS**

Observed clean-clone markers:
- `reconstruction-check: OK`
- `CLEAN_CLONE_DEPLOY=OK`
- GOMS focused suite: 48 tests, all passing
- GSV Aineko profile test: passing
- `CLEAN_CLONE_FULL_CONTRACT=OK`

The GOMS lockfile produced a fresh environment without relying on the original worktree virtual environment.

## What this proves

At this commit, the GitHub repository contains enough source/configuration/identity/deployment information to:
- reconstruct the packaged Exocortex runtime slice;
- build the GOMS Python environment;
- rebuild the GSV Aineko profile package;
- validate model-routing and authority contracts.

This is a **fresh-state reconstruction proof**, not yet a full second-machine stateful-recovery proof.

## External CI note

The committed GitHub Actions workflow was prevented from starting by the GitHub account billing/spending state for private-repository runners. GitHub reported this before executing any workflow step.

This is not a repository-test failure.

Until that account condition is cleared, the authoritative executable mirror is:

`scripts/verify_reconstruction.sh`

## Remaining proof obligations

- execute the same reconstruction on a second physical/virtual host;
- restore an encrypted continuity state bundle;
- generate/install the full service graph from manifests;
- test GOMS-down recovery and independent rescue path;
- exercise provider-loss and Remote Commander-loss failure injection.
