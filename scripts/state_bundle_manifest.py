#!/usr/bin/env python3
"""Emit a non-secret manifest of continuity state that should be backed up."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()

DEFAULT_ITEMS = [
    ("goms_root", HOME / "Library/Application Support/Aineko/GOMS", True),
    ("hermes_profile", HOME / ".hermes/profiles/gsvaineko", True),
    ("hermes_authority", HOME / ".hermes/authority", True),
]

def size_bytes(path: Path) -> int | None:
    if not path.exists():
        return None
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            p = Path(root) / name
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output")
    ap.add_argument("--git-commit")
    args = ap.parse_args()
    items = []
    for name, path, sensitive in DEFAULT_ITEMS:
        items.append({
            "name": name,
            "path": str(path),
            "exists": path.exists(),
            "size_bytes": size_bytes(path),
            "sensitive": sensitive,
        })
    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": args.git_commit,
        "note": "Manifest only. This script does not copy or expose secret/state bytes.",
        "items": items,
    }
    text = json.dumps(payload, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(text)
    else:
        print(text, end="")

if __name__ == "__main__":
    main()
