#!/usr/bin/env python3
from dataclasses import asdict
from hermes_attention_gate import Capability
from hermes_fabric_discovery import discover_fabric

CORE_CAPABILITIES = (
    ("machine_run", "machine", "OPERATE"),
    ("machine_recovery", "recovery", "RECOVERY"),
    ("goms_memory", "memory", "OBSERVE"),
    ("goms_context", "context", "OBSERVE"),
    ("goms_control", "control", "OPERATE"),
)

class HermesCapabilityGraph:
    """Runtime capability inventory used before Hermes escalates mechanical work."""
    def __init__(self, authority, probes=None, fabric_discoverer=None):
        self.authority = authority
        self.probes = probes or {}
        self.fabric_discoverer = fabric_discoverer or discover_fabric

    def discover(self):
        found = []
        for name, kind, required in CORE_CAPABILITIES:
            probe = self.probes.get(name)
            healthy = True if probe is None else bool(probe())
            found.append({
                **asdict(Capability(name, available=True,
                                    authorized=self.authority.allows(required),
                                    healthy=healthy)),
                "kind": kind, "required_mode": required,
            })
        for row in self.fabric_discoverer():
            item = dict(row)
            item["authorized"] = bool(item.get("authorized", True) and
                                      self.authority.allows(item.get("required_mode", "OPERATE")))
            found.append(item)
        return found

    def candidates(self, kind=None):
        rows = self.discover()
        return [r for r in rows if (kind is None or r["kind"] == kind)
                and r["available"] and r["authorized"] and r["healthy"]]
