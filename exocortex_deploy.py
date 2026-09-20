#!/usr/bin/env python3
"""Install a reproducible Exocortex runtime slice and generate Hermes MCP config."""
import argparse
import json
import os
import shutil
import subprocess
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
                ".venv", "__pycache__", "*.pyc", "goms.sqlite3", "events.jsonl",
                "distillation_semantic_daemon.lock"
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


def ensure_goms_runtime(release):
    release = Path(release).expanduser().resolve()
    project = release / "goms-v2"
    lock = project / "uv.lock"
    if not lock.is_file():
        raise FileNotFoundError(f"Packaged GOMS lockfile missing: {lock}")
    environment = release.parent / "venvs" / "goms"
    env = dict(os.environ)
    env["UV_PROJECT_ENVIRONMENT"] = str(environment)
    subprocess.run(
        ["uv", "sync", "--project", str(project), "--frozen"],
        check=True, env=env,
    )
    python = environment / "bin" / "python"
    if not python.is_file():
        raise RuntimeError(f"GOMS runtime interpreter was not created: {python}")
    return python


def hermes_fragment(release, goms_data_root=None):
    release = Path(release)
    goms = release / "goms-v2"
    data_root = Path(
        goms_data_root
        or os.environ.get("EXOCORTEX_GOMS_DATA_ROOT")
        or (release.parent / "data" / "goms")
    ).expanduser().resolve()
    stable_python = release.parent / "venvs" / "goms" / "bin" / "python"
    command = os.environ.get("EXOCORTEX_PYTHON") or str(stable_python)
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
    p.add_argument("--no-sync-runtime", action="store_true")
    a = p.parse_args()
    release = install(a.prefix, a.source)
    if not a.no_sync_runtime:
        ensure_goms_runtime(release)
    print(release)
    if a.print_hermes_config:
        print(json.dumps(hermes_fragment(release, a.goms_data_root), indent=2))
