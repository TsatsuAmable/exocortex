#!/usr/bin/env python3
from typing import Any

from hermes_authority import HermesAuthority
from hermes_attention_gate import Capability, decide
from hermes_macos_adapter import MacAuthorityAdapter


def _ok(**kwargs):
    return {"ok": True, **kwargs}


class HermesMachineTools:
    """Thin tool surface Hermes can call without coupling authority to GOMS."""

    def __init__(self, authority=None, adapter=None):
        self.authority = authority or HermesAuthority()
        self.adapter = adapter or MacAuthorityAdapter(self.authority)

    def authority_status(self):
        s = self.authority.current()
        return _ok(mode=s.mode, principal=s.principal,
                   entered_at=s.entered_at, reason=s.reason)

    def attention_gate(self, capabilities=None, human_required=False, irreversible=False,
                       physical_required=False, values_required=False, attempted_routes=None):
        caps = [Capability(**c) for c in (capabilities or [])]
        d = decide(capabilities=caps, human_required=human_required,
                   irreversible=irreversible, physical_required=physical_required,
                   values_required=values_required,
                   attempted_routes=tuple(attempted_routes or ()))
        self.authority.audit("attention_gate", target=d.route or "human",
                             result=d.decision.value,
                             detail={"reason": d.reason, "attempted_routes": attempted_routes or []})
        return _ok(decision=d.decision.value, route=d.route, reason=d.reason)

    def authority_enter(self, mode, *, principal, reason="", human_authorized=False):
        s = self.authority.enter(mode, principal=principal, reason=reason,
                                 human_authorized=human_authorized)
        return _ok(mode=s.mode, principal=s.principal, entered_at=s.entered_at)

    def machine_run(self, argv, *, admin=False, timeout=120):
        result = (self.adapter.run_admin(argv, timeout=timeout) if admin
                  else self.adapter.run_user(argv, timeout=timeout))
        return _ok(returncode=result.returncode, stdout=result.stdout,
                   stderr=result.stderr)

    def machine_recovery(self, action, *, label=None, plist=None, domain="gui",
                         timeout=120):
        result = self.adapter.recovery(action, label=label, plist=plist,
                                       domain=domain, timeout=timeout)
        return _ok(returncode=result.returncode, stdout=result.stdout,
                   stderr=result.stderr)


def register_tools(server, tools=None):
    surface = tools or HermesMachineTools()

    @server.tool(structured_output=True,
                 description="Read Hermes local machine-authority mode. Independent of GOMS.")
    def hermes_authority_status() -> dict[str, Any]:
        return surface.authority_status()

    @server.tool(structured_output=True,
                 description="Mandatory pre-escalation gate. Before asking the human to perform mechanical work, enumerate available authorized capability routes here. ACT/RECOVER means Hermes must continue itself; ESCALATE permits a human question only for the returned reason.")
    def hermes_attention_gate(capabilities: list[dict[str, Any]] | None = None,
                              human_required: bool = False,
                              irreversible: bool = False,
                              physical_required: bool = False,
                              values_required: bool = False,
                              attempted_routes: list[str] | None = None) -> dict[str, Any]:
        return surface.attention_gate(capabilities, human_required, irreversible,
                                      physical_required, values_required, attempted_routes)

    @server.tool(structured_output=True,
                 description="Enter a Hermes authority mode. Elevation requires explicit human authorization.")
    def hermes_authority_enter(mode: str, principal: str, reason: str = "",
                               human_authorized: bool = False) -> dict[str, Any]:
        try:
            return surface.authority_enter(mode, principal=principal, reason=reason,
                                           human_authorized=human_authorized)
        except (PermissionError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    @server.tool(structured_output=True,
                 description="Run an argv command within current OPERATE/ADMIN authority. No shell expansion.")
    def hermes_machine_run(argv: list[str], admin: bool = False,
                           timeout: int = 120) -> dict[str, Any]:
        try:
            return surface.machine_run(argv, admin=admin, timeout=timeout)
        except (PermissionError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    @server.tool(structured_output=True,
                 description="Run an allowlisted macOS control-plane recovery operation.")
    def hermes_machine_recovery(action: str, label: str | None = None,
                                plist: str | None = None, domain: str = "gui",
                                timeout: int = 120) -> dict[str, Any]:
        try:
            return surface.machine_recovery(action, label=label, plist=plist,
                                            domain=domain, timeout=timeout)
        except (PermissionError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    return surface
