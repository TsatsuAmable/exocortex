# Aineko Capability Map — MacBookPro.lan

Generated: 2026-09-10T01:54:29+01:00

## Hardware
```
Model Name: MacBook Pro
Model Identifier: MacBookPro18,3
Chip: Apple M1 Pro
Total Number of Cores: 8 (6 performance and 2 efficiency)
Memory: 16 GB
```

## High-value tooling
- **adb** — `Android Debug Bridge version 1.0.41`
- **cargo** — `cargo 1.97.1 (c980f4866 2026-06-30)`
- **clang** — `Apple clang version 17.0.0 (clang-1700.6.4.2)`
- **cmake** — `cmake version 4.2.3`
- **docker** — `Docker version 29.2.1, build a5c7197d72`
- **ffmpeg** — `ffmpeg version 8.0.1 Copyright (c) 2000-2025 the FFmpeg developers`
- **gh** — `gh version 2.87.3 (2026-02-23)`
- **git** — `git version 2.53.0`
- **go** — `go version go1.26.0 darwin/arm64`
- **java** — `openjdk version "11.0.17" 2022-10-18 LTS`
- **node** — `v25.6.1`
- **npm** — `11.9.0`
- **ollama** — app/server 0.33.2; Homebrew CLI 0.33.3
- **pnpm** — `10.30.3`
- **python3** — Homebrew Python 3.14.7; scientific compute venv also provisioned
- **rustc** — `rustc 1.97.1 (8bab26f4f 2026-07-14)`
- **sqlite3** — `3.43.2 2023-10-10 13:08:14 1b37c146ee9ebb7acd0160c0ab1fd11017a419fa8a3187386ed8cb32b709aapl (64-bit)`
- **swift** — `Apple Swift version 6.2.4 (swiftlang-6.2.4.1.4 clang-1700.6.4.2)`
- **uv** — `uv 0.12.5 (Homebrew 2026-08-14 aarch64-apple-darwin)`
- **xcodebuild** — `Xcode 26.3 Build version 17C529`

## Relevant applications
- Blender
- Docker
- Meta Quest Remote Desktop
- Notion
- Obsidian
- Ollama
- Visual Studio Code
- Xcode

## Local AI / persistence
- Memory Palace: `/Users/tsatsuamable/.mempalace` (present; Chroma/SQLite + MiniLM embedding substrate).
- Durable knowledge store: Markdown + SQLite FTS5 under `~/Documents/aineko-infrastructure/knowledge`.
- Scientific compute: isolated Python environment under `~/Documents/aineko-infrastructure/compute/.venv`.
- Embeddings: `nomic-embed-text` available through Ollama.
- Local language worker: `aineko-worker:v0.3` based on Qwen3.5 9B, 8K working context, ~20.6 tok/s observed, regression-gated prompt policy.
- Local worker dispatcher/provenance: `~/Documents/aineko-infrastructure/local-ai/dispatch.py` + JSONL result log.
- Resource stewardship: health checks and policy under `~/Documents/aineko-infrastructure/resource-stewardship`.
- Durable delivery controller v0.1: `~/Documents/aineko-infrastructure/delivery-controller`; model-agnostic SQLite state machine, GitHub PR/CI observation, GOMS checkpoints, and a dormant `launchd` scheduler template. Observe-only until evidence justifies greater authority.

## Coordination
- Desktop Commander provides authorised terminal/filesystem access.
- `~/Documents/aineko-infrastructure` is the machine-cognition infrastructure root.
- Full filesystem access remains enabled by user choice; secret stores are not inventoried.

## Current gaps
- Multi-device compute-worker registry and scheduler beyond the current Mac worker.
- Academic research plugin connection.
- Home/ambient plugin connection.
- Additional worker devices when available.
- Workload telemetry sufficient to quantify which compute scarcity is actually binding.
