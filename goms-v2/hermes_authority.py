#!/usr/bin/env python3
from __future__ import annotations

"""Local Hermes authority ceiling, independent of GOMS availability.

Authority modes: OBSERVE < OPERATE < ADMIN < RECOVERY < EMERGENCY.

Elevated modes (ADMIN, RECOVERY, EMERGENCY) are granted as scoped,
expiring leases: they carry a TTL and automatically de-escalate to
OBSERVE when the lease expires. OPERATE remains persistent by default
when explicitly human-authorized, matching the accepted operating
baseline; an optional TTL can scope it when desired.

Every mode change, lease expiry, and audited action is appended to a
local append-only audit journal that survives GOMS being unavailable.
"""
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODES = ("OBSERVE", "OPERATE", "ADMIN", "RECOVERY", "EMERGENCY")
LEVEL = {mode: i for i, mode in enumerate(MODES)}

#: Default lease TTLs (seconds) for elevated modes. Zero or negative TTLs
#: are rejected. Elevated leases always expire; OPERATE persists by default.
DEFAULT_LEASE_SECONDS = {
    "ADMIN": 3600,
    "RECOVERY": 3600,
    "EMERGENCY": 900,
}


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AuthorityState:
    mode: str
    principal: str
    entered_at: str
    reason: str = ""
    expires_at: str | None = None
    scope: dict = field(default_factory=dict)


class HermesAuthority:
    """Local authority ceiling with lease semantics, independent of GOMS."""

    def __init__(self, root=None):
        default = Path.home() / ".hermes" / "authority"
        self.root = Path(root or os.environ.get("HERMES_AUTHORITY_HOME", default)).expanduser()
        self.state_path = self.root / "state.json"
        self.audit_path = self.root / "audit.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)

    def current(self):
        """Return the effective authority state, de-escalating expired leases."""
        if not self.state_path.exists():
            return AuthorityState("OBSERVE", "local-human", _now(), "default")
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        try:
            state = AuthorityState(**raw)
        except TypeError:
            # Unknown fields in a newer state file: keep the known contract.
            known = {k: raw[k] for k in
                     ("mode", "principal", "entered_at", "reason", "expires_at", "scope")
                     if k in raw}
            state = AuthorityState(**known)
        if state.expires_at and self._expired(state.expires_at):
            expired = AuthorityState("OBSERVE", state.principal, _now(),
                                     "lease_expired", None, state.scope or {})
            self._atomic_state(expired)
            self.audit("lease_expired", target="hermes", result="deescalated",
                       detail={"from": state.mode, "expired_at": state.expires_at},
                       principal=state.principal, mode=state.mode)
            return expired
        return state

    def enter(self, mode, *, principal, reason="", human_authorized=False,
              ttl_seconds=None, scope=None):
        mode = str(mode).upper()
        if mode not in LEVEL:
            raise ValueError("invalid_authority_mode")
        if not str(principal or "").strip():
            raise ValueError("principal_required")
        ttl_seconds = self._validate_ttl(mode, ttl_seconds)
        old = self.current()
        elevated = LEVEL[mode] > LEVEL[old.mode]
        if elevated and not human_authorized:
            raise PermissionError("human_authorization_required")
        if scope is not None and not isinstance(scope, dict):
            raise ValueError("scope_must_be_dict")
        expires_at = None
        if ttl_seconds is not None:
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
        state = AuthorityState(mode, str(principal), _now(), str(reason or ""),
                               expires_at, dict(scope or {}))
        self._atomic_state(state)
        self.audit("mode_change", target="hermes", result="entered",
                   detail={"from": old.mode, "to": mode, "reason": reason,
                           "ttl_seconds": ttl_seconds, "scope": state.scope,
                           "expires_at": expires_at},
                   principal=principal, mode=mode)
        return state

    def allows(self, required_mode):
        required_mode = str(required_mode).upper()
        if required_mode not in LEVEL:
            raise ValueError("invalid_authority_mode")
        return LEVEL[self.current().mode] >= LEVEL[required_mode]

    def require(self, required_mode):
        if not self.allows(required_mode):
            raise PermissionError(f"{required_mode.lower()}_authority_required")

    def audit(self, action, *, target, result, detail=None, principal=None, mode=None):
        state = self.current()
        record = {
            "at": _now(), "principal": principal or state.principal,
            "mode": mode or state.mode, "action": str(action),
            "target": str(target), "result": str(result),
            "detail": detail or {},
        }
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    @staticmethod
    def _validate_ttl(mode, ttl_seconds):
        if ttl_seconds is None:
            return DEFAULT_LEASE_SECONDS.get(mode)
        ttl_seconds = int(ttl_seconds)
        if ttl_seconds <= 0:
            raise ValueError("ttl_must_be_positive")
        return ttl_seconds

    @staticmethod
    def _expired(expires_at):
        try:
            expiry = datetime.fromisoformat(expires_at)
        except ValueError:
            return True
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expiry

    def _atomic_state(self, state):
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.__dict__, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.state_path)