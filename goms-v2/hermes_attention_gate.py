#!/usr/bin/env python3
from dataclasses import dataclass
from enum import Enum

class Decision(str, Enum):
    ACT = "ACT"
    DELEGATE = "DELEGATE"
    RECOVER = "RECOVER"
    ESCALATE = "ESCALATE"

@dataclass(frozen=True)
class Capability:
    name: str
    available: bool = True
    authorized: bool = True
    healthy: bool = True

@dataclass(frozen=True)
class AttentionDecision:
    decision: Decision
    route: str | None
    reason: str

def decide(*, capabilities=(), human_required=False, irreversible=False,
           physical_required=False, values_required=False, attempted_routes=()):
    """Pure attention gate: mechanical work stays inside the Exocortex."""
    if human_required or irreversible or physical_required or values_required:
        why = ("policy/authority" if human_required else "irreversible choice" if irreversible
               else "physical/secret interaction" if physical_required else "human values")
        return AttentionDecision(Decision.ESCALATE, None, why)
    viable = [c for c in capabilities if c.available and c.authorized and c.healthy]
    if viable:
        return AttentionDecision(Decision.ACT, viable[0].name, "authorized capability available")
    alternate = [c for c in capabilities if c.available and c.authorized and c.name not in attempted_routes]
    if alternate:
        return AttentionDecision(Decision.RECOVER, alternate[0].name, "alternate authorized route")
    return AttentionDecision(Decision.ESCALATE, None, "no authorized executable route demonstrated")
