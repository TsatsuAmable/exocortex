#!/usr/bin/env python3
"""Install a reproducible Exocortex runtime slice and generate Hermes MCP config."""
import argparse
import json
import os
import shutil
from pathlib import Path

from goms_v2_path import source_root


def install(prefix, source=None):
    src = Path(source or source_root()).resolve()
    prefix = Path(prefix).expanduser().resolve()
    release = prefix / "current"
    staging = prefix / ".staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(src / "goms-v2", staging / "goms-v2",
                    ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc"))
    (staging / "manifest.json").write_text(
        (src / "exocortex.manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    old = prefix / ".previous"
    if old.exists():
        shutil.rmtree(old)
    if release.exists():
        release.rename(old)
    staging.rename(release)
    return release


def hermes_fragment(release):
    goms = Path(release) / "goms-v2"
    return {"mcp_servers": {"goms": {
        "command": os.environ.get("EXOCORTEX_PYTHON", "python3"),
        "args": [str(goms / "mcp_server.py")],
        "enabled": True,
        "env": {"EXOCORTEX_GOMS_ROOT": str(goms)},
    }}}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--prefix", default="~/.local/share/exocortex")
    p.add_argument("--source")
    p.add_argument("--print-hermes-config", action="store_true")
    a = p.parse_args()
    release = install(a.prefix, a.source)
    print(release)
    if a.print_hermes_config:
        print(json.dumps(hermes_fragment(release), indent=2))
