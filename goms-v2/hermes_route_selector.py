#!/usr/bin/env python3
PREFERENCE = {
    "machine": ("machine_run", "remote_commander", "tailscale_fabric"),
    "remote_execution": ("remote_commander", "tailscale_fabric", "machine_run"),
    "worker": ("distillation_worker_pool", "machine_run", "remote_commander"),
    "memory": ("goms_memory",),
    "context": ("goms_context",),
    "control": ("goms_control",),
}

def select_route(capabilities, task_kind="machine", attempted=()):
    viable={c["name"]:c for c in capabilities
            if c.get("available") and c.get("authorized") and c.get("healthy")
            and c["name"] not in set(attempted)}
    order=PREFERENCE.get(task_kind, PREFERENCE["machine"])
    for name in order:
        if name in viable:
            return {"route":name,"decision":"ACT" if not attempted else "RECOVER",
                    "reason":"preferred healthy authorized route"}
    return {"route":None,"decision":"ESCALATE",
            "reason":"no healthy authorized route remains"}
