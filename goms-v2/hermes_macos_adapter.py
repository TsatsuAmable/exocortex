#!/usr/bin/env python3
import subprocess
from dataclasses import dataclass

from hermes_authority import HermesAuthority


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class MacAuthorityAdapter:
    """macOS execution boundary governed by Hermes local authority state."""

    RECOVERY_ACTIONS = {
        "service_list": "OBSERVE",
        "service_restart": "RECOVERY",
        "service_bootstrap": "RECOVERY",
        "service_bootout": "RECOVERY",
    }

    def __init__(self, authority=None, runner=None):
        self.authority = authority or HermesAuthority()
        self.runner = runner or subprocess.run

    def run_user(self, argv, *, timeout=120):
        self.authority.require("OPERATE")
        return self._run(argv, "user_command", timeout=timeout)

    def run_admin(self, argv, *, timeout=120):
        self.authority.require("ADMIN")
        # This adapter never injects passwords or stores credentials. macOS owns elevation.
        return self._run(["sudo", "--", *argv], "admin_command", timeout=timeout)

    def recovery(self, action, *, label=None, plist=None, domain="gui", timeout=120):
        required = self.RECOVERY_ACTIONS.get(action)
        if not required:
            raise ValueError("unsupported_recovery_action")
        self.authority.require(required)
        uid_domain = f"{domain}/{__import__('os').getuid()}" if domain == "gui" else domain
        if action == "service_list":
            argv = ["launchctl", "list"]
        elif action == "service_restart":
            if not label:
                raise ValueError("label_required")
            argv = ["launchctl", "kickstart", "-k", f"{uid_domain}/{label}"]
        elif action == "service_bootstrap":
            if not plist:
                raise ValueError("plist_required")
            argv = ["launchctl", "bootstrap", uid_domain, str(plist)]
        else:
            if not label:
                raise ValueError("label_required")
            argv = ["launchctl", "bootout", f"{uid_domain}/{label}"]
        return self._run(argv, f"recovery:{action}", timeout=timeout)

    def _run(self, argv, action, *, timeout):
        argv = [str(x) for x in argv]
        target = argv[-1] if argv else ""
        try:
            cp = self.runner(argv, text=True, capture_output=True, timeout=timeout)
            result = CommandResult(cp.returncode, cp.stdout or "", cp.stderr or "")
            self.authority.audit(action, target=target,
                                 result="ok" if cp.returncode == 0 else "failed",
                                 detail={"argv": argv, "returncode": cp.returncode})
            return result
        except Exception as exc:
            self.authority.audit(action, target=target, result="error",
                                 detail={"argv": argv, "error": type(exc).__name__})
            raise
