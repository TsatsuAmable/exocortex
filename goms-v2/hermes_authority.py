#!/usr/bin/env python3
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MODES = ("OBSERVE", "OPERATE", "ADMIN", "RECOVERY", "EMERGENCY")
LEVEL = {mode: i for i, mode in enumerate(MODES)}


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AuthorityState:
    mode: str
    principal: str
    entered_at: str
    reason: str = ""


class HermesAuthority:
    """Local authority ceiling independent of GOMS availability."""

    def __init__(self, root=None):
        default = Path.home() / ".hermes" / "authority"
        self.root = Path(root or os.environ.get("HERMES_AUTHORITY_HOME", default)).expanduser()
        self.state_path = self.root / "state.json"
        self.audit_path = self.root / "audit.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)

    def current(self):
        if not self.state_path.exists():
            return AuthorityState("OBSERVE", "local-human", _now(), "default")
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        return AuthorityState(**raw)

    def enter(self, mode, *, principal, reason="", human_authorized=False):
        mode = str(mode).upper()
        if mode not in LEVEL:
            raise ValueError("invalid_authority_mode")
        if not str(principal or "").strip():
            raise ValueError("principal_required")
        old = self.current()
        elevated = LEVEL[mode] > LEVEL[old.mode]
        if elevated and not human_authorized:
            raise PermissionError("human_authorization_required")
        state = AuthorityState(mode, str(principal), _now(), str(reason or ""))
        self._atomic_state(state)
        self.audit("mode_change", target="hermes", result="entered",
                   detail={"from": old.mode, "to": mode, "reason": reason},
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

    def _atomic_state(self, state):
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.__dict__, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.state_path)
