---
name: exocortex-engineering
description: "Execute repository changes from live state through verification."
version: 0.1.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [exocortex, engineering, git, verification, reuse]
---

# Exocortex Engineering

Use for implementation, repository maintenance, CI failures, refactors, architecture changes, and "what next?" development work.

## Start from reality

Before implementing:
1. inspect the authoritative repository and engineering contracts;
2. fetch or verify current remote/main state when network access exists;
3. inspect branch/worktree status and concurrent work;
4. locate existing structures that may already solve part of the task;
5. identify the smallest real delta.

Do not rebuild a subsystem merely because its implementation was not in immediate context.

## Execution bias

When the user requests implementation, produce code and verified effects, not only a plan.

Use a plan internally when it reduces error, but continue into execution unless a genuine gate blocks it.

For substantial or concurrent work, use a dedicated branch/worktree and preserve unrelated local changes.

## Reuse and architecture

Respect existing authorities and boundaries. Extend existing contracts before inventing parallel ones.

When apparent duplication is found, determine which implementation is authoritative and consolidate toward it rather than adding another abstraction layer.

## Delegated coding

Codex and OpenCode are worker substrates, not authorities.

When useful:
- route the cognitive task through the shared model router;
- invoke the coding worker on the authorised host route if the Docker terminal lacks the CLI;
- give it repository state, constraints, non-goals, and verification criteria;
- supervise its output and inspect the diff.

Do not ask the human to shuttle prompts or results between coding agents.

## Verification

For a code change, prefer this sequence:
- targeted tests;
- broader relevant test suite;
- static/type/lint checks when applicable;
- runtime or integration verification;
- CI/PR state if the repository uses it.

A green local test does not imply a green PR. A green PR does not prove the intended runtime effect when a live verification is available.

Fix failures introduced by the work. Distinguish code failures from infrastructure/non-code CI failures rather than repeatedly patching the wrong layer.

## Completion

Before reporting done:
- inspect git diff/status;
- verify no unrelated files were swept in;
- record the commit/PR or deployed state;
- state any remaining risk or deferred dependency.

Prefer small reversible commits with clear evidence over large opaque changes.
