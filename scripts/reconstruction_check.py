#!/usr/bin/env python3
"""Structural survivability check for the Exocortex repository."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    "README.md",
    "SECURITY.md",
    "exocortex.manifest.json",
    "exocortex_deploy.py",
    ".statebundle-ignore",
    "goms-v2/mcp_server.py",
    "goms-v2/schema.sql",
    "goms-v2/storage_governor.py",
    "goms-v2/storage_policy.json",
    "docs/goms/STORAGE_GOVERNANCE.md",
    "goms-v2/attention_market.py",
    "docs/goms/ATTENTION_BUDGET_MARKET.md",
    "compute/model-routing/router.py",
    "compute/model-routing/fleet.json",
    "hermes/SOUL.md",
    "hermes/profile_manifest.json",
    "hermes/install_profile.py",
    "docs/reconstruction/REBUILD_FROM_GITHUB.md",
    "docs/reconstruction/STATE_AND_SECRETS.md",
    "docs/reconstruction/ACCEPTANCE_CHECKLIST.md",
    "docs/runtime/SERVICE_TOPOLOGY.md",
    "config/hermes.gsvaineko.fragment.yaml",
    "config/exocortex.env.example",
    "models/gsvaineko-core.Modelfile",
]

FORBIDDEN_TRACKED = [
    re.compile(r"(^|/)\.env$", re.I),
    re.compile(r"(^|/)(auth|credentials?)\.json$", re.I),
    re.compile(r"(^|/).*\.(key|p12|pfx)$", re.I),
    re.compile(r"(^|/)(goms|state|delivery).*\.(sqlite3|db)(-|$)", re.I),
    re.compile(r"(^|/)whatsapp/session", re.I),
    re.compile(r"(^|/)secrets?/", re.I),
]

RUNTIME_COMMANDS = ["git", "python3", "docker", "node", "ollama", "gh", "uv"]

def fail(msg: str, errors: list[str]) -> None:
    errors.append(msg)
    print(f"FAIL: {msg}")

def tracked_files() -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(ROOT), "ls-files"], text=True, stderr=subprocess.DEVNULL
        )
        return [line.strip() for line in out.splitlines() if line.strip()]
    except Exception:
        return []

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", action="store_true",
                    help="also require reference host commands to be available")
    args = ap.parse_args()
    errors: list[str] = []

    for rel in REQUIRED:
        if not (ROOT / rel).is_file():
            fail(f"required file missing: {rel}", errors)

    manifest_path = ROOT / "exocortex.manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        for name, component in manifest.get("components", {}).items():
            source = ROOT / component["source"]
            entry = source / component["entrypoint"]
            if not source.exists():
                fail(f"component {name} source missing: {source}", errors)
            if not entry.is_file():
                fail(f"component {name} entrypoint missing: {entry}", errors)

    profile_path = ROOT / "hermes/profile_manifest.json"
    if profile_path.is_file():
        profile = json.loads(profile_path.read_text())
        for name in profile.get("custom_skills", []):
            path = ROOT / "hermes/skills" / name / "SKILL.md"
            if not path.is_file():
                fail(f"custom skill missing: {name}", errors)

    for rel in tracked_files():
        for pattern in FORBIDDEN_TRACKED:
            if pattern.search(rel):
                fail(f"forbidden state/secret-like tracked path: {rel}", errors)
                break

    if args.runtime:
        for command in RUNTIME_COMMANDS:
            if not shutil.which(command):
                fail(f"reference runtime command unavailable: {command}", errors)

    if errors:
        print(f"reconstruction-check: {len(errors)} error(s)")
        return 1

    print("reconstruction-check: OK")
    if not args.runtime:
        missing = [c for c in RUNTIME_COMMANDS if not shutil.which(c)]
        if missing:
            print("runtime-note: commands not present here: " + ", ".join(missing))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
