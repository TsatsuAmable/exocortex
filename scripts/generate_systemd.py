#!/usr/bin/env python3
"""Generate systemd user units from the canonical service inventory.

Mirrors scripts/generate_launchd.py: same inventory file, same placeholder
policy ($VAR from environment with HOME derived from Path.home(), <ANGLE>
placeholders from --values), one unit per non-external service, skip or
--strict on unresolved placeholders, external services never emitted.

Mapping from inventory fields:
  label                  -> unit name, dots replaced with dashes
  role                   -> Description=
  command                -> ExecStart= (args shell-quoted)
  working_directory      -> WorkingDirectory=
  environment            -> Environment= entries, sorted
  run_at_load            -> [Install] WantedBy=default.target
  keep_alive             -> Restart=always (RestartSec=5)
  start_interval_seconds -> companion <unit>.timer (OnBootSec/OnUnitActiveSec),
                            only when keep_alive is not set

Logs go to the journal: launchd StandardOut/StandardErrorPath have no direct
systemd equivalent without wrapper shells.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path

ANGLE_RE = re.compile(r"<([A-Z_][A-Z0-9_]*)>")
DOLLAR_RE = re.compile(r"\$([A-Z_][A-Z0-9_]*)")


def expand(value, values, missing):
    def angle_sub(match):
        key = match.group(1)
        if key in values:
            return values[key]
        missing.add(key)
        return match.group(0)

    def dollar_sub(match):
        key = match.group(1)
        if key in values:
            return values[key]
        env = os.environ.get(key)
        if env is None and key == "HOME":
            env = str(Path.home())
        if env is not None:
            return env
        missing.add(key)
        return match.group(0)

    if not isinstance(value, str):
        return value
    return ANGLE_RE.sub(angle_sub, DOLLAR_RE.sub(dollar_sub, value))


def expand_all(obj, values, missing):
    if isinstance(obj, str):
        return expand(obj, values, missing)
    if isinstance(obj, list):
        return [expand_all(v, values, missing) for v in obj]
    if isinstance(obj, dict):
        return {k: expand_all(v, values, missing) for k, v in obj.items()}
    return obj


def unit_name(label: str) -> str:
    return label.replace(".", "-") + ".service"


def timer_name(label: str) -> str:
    return label.replace(".", "-") + ".timer"


def build_unit(service, values):
    label = service["label"]
    missing = set()
    spec = expand_all(service, values, missing)
    if missing:
        return (unit_name(label), sorted(missing))

    lines = ["[Unit]"]
    if service.get("role"):
        lines.append(f"Description={service['role']}")
    lines.append("After=network-online.target")
    lines.append("Wants=network-online.target")
    lines.append("")

    lines.append("[Service]")
    exec_start = " ".join(shlex.quote(a) for a in spec["command"])
    lines.append(f"ExecStart={exec_start}")
    if spec.get("working_directory"):
        lines.append(f"WorkingDirectory={spec['working_directory']}")
    env = spec.get("environment") or {}
    for key in sorted(env):
        lines.append(f"Environment={key}={env[key]}")
    if spec.get("keep_alive"):
        lines.append("Restart=always")
        lines.append("RestartSec=5")
    lines.append("")

    lines.append("[Install]")
    lines.append("WantedBy=default.target")
    return (unit_name(label), "\n".join(lines) + "\n")


def build_timer(service, values):
    label = service["label"]
    missing = set()
    spec = expand_all(service, values, missing)
    if missing:
        return (timer_name(label), sorted(missing))
    interval = int(spec["start_interval_seconds"])
    lines = [
        "[Unit]",
        f"Description=Timer companion for {label}",
        "",
        "[Timer]",
        f"OnBootSec={interval}s",
        f"OnUnitActiveSec={interval}s",
        f"Unit={unit_name(label)}",
        "",
        "[Install]",
        "WantedBy=timers.target",
    ]
    return (timer_name(label), "\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", type=Path,
                    default=Path(__file__).resolve().parent.parent
                    / "deploy/launchd/service-inventory.example.json")
    ap.add_argument("--values", type=Path, default=None,
                    help='JSON file of placeholder values, e.g. {"GOMS_HOME": "/..."}')
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--strict", action="store_true",
                    help="fail on unresolved placeholders instead of skipping")
    args = ap.parse_args()

    values = {}
    if args.values:
        values = json.loads(args.values.read_text(encoding="utf-8"))

    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    services = [s for s in inventory.get("services", []) if not s.get("external")]

    args.out.mkdir(parents=True, exist_ok=True)
    generated, skipped = [], []
    for service in services:
        result = build_unit(service, values)
        if isinstance(result[1], list):  # unresolved placeholders
            skipped.append((result[0], result[1]))
            continue
        name, content = result
        target = args.out / name
        target.write_text(content, encoding="utf-8")
        generated.append(name)

        if service.get("start_interval_seconds") and not service.get("keep_alive"):
            tresult = build_timer(service, values)
            if isinstance(tresult[1], list):
                skipped.append((tresult[0], tresult[1]))
            else:
                tname, tcontent = tresult
                (args.out / tname).write_text(tcontent, encoding="utf-8")
                generated.append(tname)

    print(json.dumps({"generated": generated, "skipped": skipped,
                      "inventory": str(args.inventory)}, indent=2))
    if args.strict and skipped:
        sys.exit(f"error: unresolved placeholders for {skipped}")
    return 0


if __name__ == "__main__":
    main()