#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone

from alerts import AlertService

SCHEMA_VERSION = "1.0"
ACTIONABLE_LOCATOR_SOURCES = {"observed", "supplied"}
AUTHORITY_ACTIONS = {"APPROVE", "REJECT", "DEFER", "CONFIRM"}
NAVIGATION_ACTIONS = {"ASK_CHATGPT", "OPEN_CHATGPT", "OPEN_ORIGIN"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strings(value) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def _locator_source(intent: dict, role: str) -> str:
    provenance = intent.get("provenance") if isinstance(intent.get("provenance"), dict) else {}
    locators = provenance.get("conversation_locators") if isinstance(provenance.get("conversation_locators"), dict) else {}
    locator = locators.get(role) if isinstance(locators.get(role), dict) else {}
    return str(locator.get("source") or "").strip().lower()

def _section(intent_id: str, desired_type: str, section_id: str, data: dict,
             supported: set[str], mismatches: list[dict], materiality: str) -> dict:
    if desired_type in supported:
        return {"id": section_id, "type": desired_type, "data": data}
    mismatches.append({
        "component": desired_type,
        "intent_id": intent_id,
        "fallback": "generic_object",
        "materiality": materiality,
    })
    return {
        "id": section_id,
        "type": "generic_object",
        "original_type": desired_type,
        "data": data,
    }


def _authority_actions(intent: dict) -> list[str]:
    status = str(intent.get("status") or "").upper()
    policy = str(intent.get("execution_policy") or "HUMAN_ONLY").upper()
    if status == "NEEDS_DECISION":
        return ["APPROVE", "REJECT", "DEFER"]
    if status == "APPROVED" and policy == "CONFIRM_HIGH_RISK":
        return ["CONFIRM", "DEFER"]
    return []


def _action(action_id: str) -> dict:
    return {
        "id": action_id,
        "kind": "authority" if action_id in AUTHORITY_ACTIONS else "navigation",
        "label": action_id.replace("_", " ").title(),
    }

def _navigation_actions(intent: dict) -> list[str]:
    actions = ["ASK_CHATGPT"]
    execution_url = str(intent.get("execution_conversation_url") or "").strip()
    origin_url = str(intent.get("origin_conversation_url") or "").strip()
    if execution_url and _locator_source(intent, "execution") in ACTIONABLE_LOCATOR_SOURCES:
        actions.append("OPEN_CHATGPT")
    if origin_url and _locator_source(intent, "origin") in ACTIONABLE_LOCATOR_SOURCES:
        actions.append("OPEN_ORIGIN")
    return actions


def _link_data(intent: dict) -> dict:
    result = {}
    for role in ("execution", "origin"):
        url = str(intent.get(f"{role}_conversation_url") or "").strip()
        conversation_id = intent.get(f"{role}_conversation_id")
        if url or conversation_id:
            result[role] = {
                "conversation_id": conversation_id,
                "url": url or None,
                "source": _locator_source(intent, role) or "unverified",
            }
    return result


def _project_intent(intent: dict, components: set[str], actions: set[str],
                    mismatches: list[dict]) -> dict:
    intent_id = str(intent.get("id") or "")
    summary = {
        "title": intent.get("title") or "",
        "summary": intent.get("summary") or "",
        "status": intent.get("status") or "",
        "priority": intent.get("priority") or "P2",
        "risk_tier": intent.get("risk_tier") or "normal",
        "execution_policy": intent.get("execution_policy") or "HUMAN_ONLY",
    }
    sections = [_section(intent_id, "summary", "summary", summary,
                         components, mismatches, "decision_context")]
    decision = {
        "status": intent.get("status") or "",
        "execution_policy": intent.get("execution_policy") or "HUMAN_ONLY",
        "decision_required": bool(intent.get("decision_required")),
        "recommended_action": intent.get("recommended_action") or {},
        "alternatives": intent.get("alternatives") or [],
    }
    sections.append(_section(intent_id, "decision", "decision", decision,
                             components, mismatches, "decision_context"))
    evidence = intent.get("evidence_refs") if isinstance(intent.get("evidence_refs"), list) else []
    if evidence:
        sections.append(_section(intent_id, "evidence", "evidence", {"items": evidence},
                                 components, mismatches, "contextual"))
    links = _link_data(intent)
    if links:
        sections.append(_section(intent_id, "link", "conversation_links", links,
                                 components, mismatches, "navigation"))

    requested_actions = _authority_actions(intent) + _navigation_actions(intent)
    projected_actions = [_action(action_id) for action_id in requested_actions if action_id in actions]
    canonical = dict(intent)
    canonical["ui"] = {
        "template": "intent_detail",
        "sections": sections,
        "actions": projected_actions,
    }
    return canonical


def build_projection(control, capabilities: dict) -> dict:
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    components = _strings(capabilities.get("components"))
    actions = _strings(capabilities.get("actions"))
    brief = control.build_brief(reconcile=False)
    mismatches: list[dict] = []
    intents = [
        _project_intent(intent, components, actions, mismatches)
        for intent in brief.get("intents", [])
        if isinstance(intent, dict)
    ]
    alerts = AlertService(control.db.parent).list_active()
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "intents": intents,
        "alerts": alerts,
        "capability_mismatches": mismatches,
    }
