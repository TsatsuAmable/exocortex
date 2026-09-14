# GOMS Manfred Control Integration Plan

**Goal:** Make Manfred the human-authority cockpit for GOMS without making it a second source of truth.

**Architecture:** GOMS remains canonical. A small authenticated control service exposes a compact read-side brief and a closed set of explicit authority commands. Commands are idempotent, provenance-recorded, and implemented through existing GOMS state transitions rather than arbitrary shell or SQL execution.

**Tech Stack:** Python 3.14, SQLite, GomsStore, stdlib HTTP server, unittest.

## Global constraints
- GOMS SQLite remains canonical.
- Existing Manfred -> GOMS event ingestion remains intact.
- No arbitrary command execution endpoint.
- Bind localhost by default; require bearer token for HTTP control.
- Every mutation has an idempotency key and durable command record.
