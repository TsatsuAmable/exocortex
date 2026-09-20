#!/usr/bin/env python3
import json, shutil, subprocess, urllib.request

def _cmd_ok(argv, timeout=3):
    try:
        return subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=timeout).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False

def _http_ok(url, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except Exception:
        return False

def discover_fabric():
    """Best-effort live routes. Absence is data, never an exception."""
    routes=[]
    # Remote Commander is configured locally and health is independently probed.
    rc_configured = _http_ok("http://127.0.0.1:8771/", timeout=1)
    routes.append({"name":"remote_commander","kind":"remote_execution",
                   "available":rc_configured,"authorized":True,"healthy":rc_configured,
                   "required_mode":"OPERATE"})
    tailscale = shutil.which("tailscale") or "/usr/local/bin/tailscale"
    ts_ok = _cmd_ok([tailscale, "status"], 3)
    routes.append({"name":"tailscale_fabric","kind":"network_fabric",
                   "available":bool(shutil.which("tailscale") or __import__("pathlib").Path(tailscale).exists()),
                   "authorized":True,"healthy":ts_ok,"required_mode":"OPERATE"})
    # Known Exocortex worker route: only advertise executable when queue/service is present.
    queue_ok = _http_ok("http://127.0.0.1:8766/health", timeout=1)
    routes.append({"name":"distillation_worker_pool","kind":"worker",
                   "available":queue_ok,"authorized":True,"healthy":queue_ok,
                   "required_mode":"OPERATE"})
    return routes
