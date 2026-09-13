#!/usr/bin/env python3
import json

SAFE_ACTIONS = {"launchd_kickstart", "drain_replication"}
HUMAN_FAILURES = {"human_authorization_required", "human_judgment_required"}
MAX_AUTO_ATTEMPTS = 3


def _obj(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def decide_reconciliation(resource):
    spec = _obj(resource.get("spec"))
    status = _obj(resource.get("status"))
    generation = int(resource.get("generation") or 0)
    observed_generation = int(resource.get("observed_generation") or 0)
    desired = spec.get("desired_state")
    observed = status.get("observed_state")
    failure = status.get("failure_class")
    repair = spec.get("repair")
    attempts = int(resource.get("attempt_count") or 0)

    if generation > observed_generation:
        return {
            "disposition": "OBSERVE_WAIT", "action": None,
            "reason": "desired generation has not yet been observed",
        }
    if failure in HUMAN_FAILURES:
        return {
            "disposition": "HUMAN_REQUIRED", "action": None,
            "reason": f"human authorization boundary: {failure}",
        }
    if desired == observed:
        return {
            "disposition": "CONVERGED", "action": None,
            "reason": "observed state matches desired state",
        }
    if resource.get("authority") != "system":
        return {
            "disposition": "HUMAN_REQUIRED", "action": None,
            "reason": "resource authority does not permit autonomous mutation",
        }
    if attempts >= MAX_AUTO_ATTEMPTS:
        return {
            "disposition": "ESCALATE", "action": None,
            "reason": "automatic repair retry budget exhausted",
        }
    if repair in SAFE_ACTIONS:
        return {
            "disposition": "AUTO_REPAIR", "action": repair,
            "reason": f"bounded safe repair for drift {observed!r} -> {desired!r}",
        }
    return {
        "disposition": "PROPOSE", "action": None,
        "reason": "drift detected but no allow-listed repair is declared",
    }
