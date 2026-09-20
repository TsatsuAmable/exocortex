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
    manifest = json.loads((src / "exocortex.manifest.json").read_text(encoding="utf-8"))
    for component in manifest.get("components", {}).values():
        source_rel = component["source"]
        install_rel = component["install"]
        shutil.copytree(
            src / source_rel,
            staging / install_rel,
            ignore=shutil.ignore_patterns(
                ".venv", "__pycache__", "*.pyc", "goms.sqlite3", "events.jsonl", "*.lock"
            ),
        )
    (staging / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    old = prefix / ".previous"
    if old.exists():
        shutil.rmtree(old)
    if release.exists():
        release.rename(old)
    staging.rename(release)
    return release


def hermes_fragment(release, goms_data_root=None):
    release = Path(release)
    goms = release / "goms-v2"
    data_root = Path(
        goms_data_root
        or os.environ.get("EXOCORTEX_GOMS_DATA_ROOT")
        or (release.parent / "data" / "goms")
    ).expanduser().resolve()
    default_python = Path(source_root()) / "goms-v2" / ".venv" / "bin" / "python"
    command = os.environ.get("EXOCORTEX_PYTHON") or (
        str(default_python) if default_python.exists() else "python3"
    )
    return {"mcp_servers": {"goms": {
        "command": command,
        "args": [str(goms / "mcp_server.py")],
        "enabled": True,
        "env": {
            "EXOCORTEX_GOMS_ROOT": str(goms),
            "GOMS_HOME": str(data_root),
            "AINEKO_MODEL_ROUTER_PATH": str(release / "model-routing" / "router.py"),
        },
    }}}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--prefix", default="~/.local/share/exocortex")
    p.add_argument("--source")
    p.add_argument("--print-hermes-config", action="store_true")
    p.add_argument("--goms-data-root")
    a = p.parse_args()
    release = install(a.prefix, a.source)
    print(release)
    if a.print_hermes_config:
        print(json.dumps(hermes_fragment(release, a.goms_data_root), indent=2))
