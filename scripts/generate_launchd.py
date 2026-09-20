#!/usr/bin/env python3
"""Generate launchd plists from the canonical service inventory.

Reads deploy/launchd/service-inventory.example.json (or a deployment-specific
inventory) and emits one .plist per non-external service.

Placeholder policy:
  $VAR references expand from the generator environment (HOME is derived
  automatically; GOMS_HOME / HERMES_HOME / EXOCORTEX_CURRENT come from
  --values or the environment).
  <ANGLE_BRACKET> placeholders are deployment-specific (Tailscale bind IPs,
  allowed client IPs, venv python paths). They are supplied via --values.
  Services with unresolved placeholders are skipped with a warning unless
  --strict is given, in which case generation fails listing the missing keys.

Services marked "external": true are managed outside launchd generation and
are never emitted. historical_or_optional entries are never emitted.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DOCTYPE = ('<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
           '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">')

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


def _plist_string(value: str) -> ET.Element:
    el = ET.Element("string")
    el.text = value
    return el


def build_plist(service: dict, values) -> tuple[Path, str] | None:
    label = service["label"]
    missing = set()
    spec = expand_all(service, values, missing)
    if missing:
        return (f"{label}.plist", sorted(missing))

    root = ET.Element("plist", {"version": "1.0"})
    top = ET.SubElement(root, "dict")

    def add(key, el):
        top.append(ET.Element("key"))
        top[-1].text = key
        top.append(el)

    add("Label", _plist_string(label))

    if service.get("role"):
        add("Comment", _plist_string(service["role"]))

    command = spec["command"]
    if len(command) == 1 and command[0].endswith(".sh"):
        add("Program", _plist_string(command[0]))
    else:
        pa = ET.Element("array")
        for arg in command:
            pa.append(_plist_string(arg))
        add("ProgramArguments", pa)

    if spec.get("working_directory"):
        add("WorkingDirectory", _plist_string(spec["working_directory"]))

    if spec.get("environment"):
        env_dict = ET.Element("dict")
        for key in sorted(spec["environment"]):
            env_dict.append(ET.Element("key"))
            env_dict[-1].text = key
            env_dict.append(_plist_string(str(spec["environment"][key])))
        add("EnvironmentVariables", env_dict)

    if spec.get("run_at_load"):
        add("RunAtLoad", ET.Element("true"))
    if spec.get("keep_alive"):
        add("KeepAlive", ET.Element("true"))
    if spec.get("start_interval_seconds"):
        iv = ET.Element("integer")
        iv.text = str(int(spec["start_interval_seconds"]))
        add("StartInterval", iv)

    logdir = values.get("LOG_DIR", "/tmp")
    add("StandardOutPath", _plist_string(f"{logdir}/{label}.out.log"))
    add("StandardErrorPath", _plist_string(f"{logdir}/{label}.err.log"))

    xml = ET.tostring(root, encoding="unicode")
    return (Path(f"{label}.plist"),
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'{DOCTYPE}\n{xml}\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", type=Path,
                    default=Path(__file__).resolve().parent.parent
                    / "deploy/launchd/service-inventory.example.json")
    ap.add_argument("--values", type=Path, default=None,
                    help="JSON file of placeholder values, e.g. {\"GOMS_HOME\": \"/...\"}")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--strict", action="store_true",
                    help="fail on unresolved placeholders instead of skipping")
    args = ap.parse_args()

    values = {}
    if args.values:
        values = json.loads(args.values.read_text(encoding="utf-8"))

    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    services = [s for s in inventory.get("services", [])
                if not s.get("external")]

    args.out.mkdir(parents=True, exist_ok=True)
    generated, skipped = [], []
    for service in services:
        result = build_plist(service, values)
        if result is None:
            continue
        if isinstance(result[1], list):  # unresolved placeholders
            skipped.append((result[0], result[1]))
            continue
        path, xml = result
        target = args.out / path
        target.write_text(xml, encoding="utf-8")
        generated.append(target.name)

    print(json.dumps({"generated": generated, "skipped": skipped,
                      "inventory": str(args.inventory)}, indent=2))
    if args.strict and skipped:
        sys.exit(f"error: unresolved placeholders for {skipped}")
    return 0


if __name__ == "__main__":
    main()