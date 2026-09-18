#!/usr/bin/env python3
"""Generate Hermes GOMS MCP config from a discovered Exocortex installation."""
import os
import sys
from pathlib import Path


def discover_goms_root():
    override = os.environ.get("EXOCORTEX_GOMS_ROOT")
    candidates = [
        Path(override).expanduser() if override else None,
        Path(__file__).resolve().parent,
        Path.home() / ".local" / "share" / "exocortex" / "goms-v2",
    ]
    for candidate in candidates:
        if candidate and (candidate / "mcp_server.py").is_file():
            return candidate.resolve()
    raise FileNotFoundError("Unable to discover goms-v2; set EXOCORTEX_GOMS_ROOT")


def hermes_mcp_config(root=None):
    root = Path(root or discover_goms_root()).resolve()
    python = root / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable).resolve()
    return {
        "command": str(python),
        "args": [str(root / "mcp_server.py")],
        "enabled": True,
    }


if __name__ == "__main__":
    import json
    print(json.dumps({"goms": hermes_mcp_config()}, indent=2))
