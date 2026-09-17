# Hermes GOMS Exocortex Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Hermes a first-class, low-attention GOMS client that reads canonical goals/state and can record bounded clarification/policy proposals without bypassing authority.

**Architecture:** Keep GOMS canonical and expose a compact exocortex read model through MCP. Hermes remains an MCP client; no bespoke Hermes↔GOMS protocol is added. Writes are provenance-bearing proposals/evidence only and never auto-approve or execute control intents.

**Tech Stack:** Python 3.14, SQLite, MCP stdio, unittest, Hermes MCP configuration.

**Spec:** Current agreed architecture: GOMS knows/state, Governor governs authority, Hermes interprets/communicates; use the existing GOMS MCP interface, not a UMM layer.

## Global Constraints
- Do not create a second state store.
- Do not let Hermes bypass `HUMAN_ONLY` or control-intent authority.
- Read from the canonical runtime DB at `~/Library/Application Support/Aineko/GOMS/goms.sqlite3` in production.
- Preserve provenance, validity windows, and epistemic status in goal/context output.
- Keep existing MCP tools compatible.

---

### Task 1: Compact exocortex read model

**Files:**
- Create: `goms-v2/exocortex_context.py`
- Create: `goms-v2/test_exocortex_context.py`
- Modify: `goms-v2/mcp_server.py`

**Interfaces:**
- Produces: `ExocortexContext(store).brief(person_title="User", project=None, limit=12) -> dict`
- MCP tool: `exocortex_brief(person_title="User", project=None, limit=12)`

- [ ] Write failing tests for active goal extraction, provenance/validity fields, constraints/preferences, active branches, and unresolved intents.
- [ ] Run `python -m unittest test_exocortex_context.py -v` and verify RED.
- [ ] Implement the minimal read model using canonical SQLite state; normalize predicates such as `has objective`/`has_objective`.
- [ ] Expose it from `mcp_server.py` with a tool description telling Hermes to use it for context reconstruction.
- [ ] Re-run focused tests and full `unittest discover`.
- [ ] Commit.

### Task 2: Governed Hermes writes

**Files:**
- Modify: `goms-v2/exocortex_context.py`
- Modify: `goms-v2/test_exocortex_context.py`
- Modify: `goms-v2/mcp_server.py`

**Interfaces:**
- Produces: `record_clarification(...)` as durable evidence with provenance; optional intent reference is validated but intent lifecycle is not changed.
- Produces: `propose_policy(...)` as a `PROPOSED` idea with `requires_human_ratification=true`; it does not become canonical policy automatically.

- [ ] Write failing tests proving clarification/policy writes are auditable and do not mutate intent status.
- [ ] Verify RED.
- [ ] Implement minimal write methods and MCP wrappers.
- [ ] Verify focused and full tests.
- [ ] Commit.

### Task 3: Wire Hermes to canonical GOMS and smoke-test

**Files:**
- Runtime config only: `~/.hermes/config.yaml`
- Runtime config only: `~/.hermes/profiles/gsvaineko/config.yaml`

**Interfaces:**
- Add MCP server env `GOMS_HOME=/Users/tsatsuamable/Library/Application Support/Aineko/GOMS` while keeping the repository MCP server code path.

- [ ] Confirm current MCP process is reading the non-canonical repo DB and canonical runtime DB contains semantic goals/intents.
- [ ] Add `GOMS_HOME` to both relevant Hermes MCP configurations, preserving backups.
- [ ] Merge feature branch into `goms/p0-hardening-20260913` after verification.
- [ ] Restart only the Hermes/GOMS MCP process or gateway as needed so discovery reloads safely.
- [ ] Smoke-test `exocortex_brief` against canonical data and verify it returns current `User` goal assertions plus live intents.
- [ ] Verify no control-intent lifecycle changed during smoke test; run `git diff --check` and full tests.
