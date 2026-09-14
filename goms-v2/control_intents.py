#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from goms_store import GomsStore, make_id, now

INTENT_STATUSES = {
    "DETECTED", "STAGED", "NEEDS_DECISION", "APPROVED", "EXECUTING",
    "VERIFYING", "RESOLVED", "REJECTED", "DEFERRED", "FAILED",
    "ESCALATED", "OUTCOME_UNKNOWN",
}
TERMINAL_STATUSES = {"RESOLVED", "REJECTED", "FAILED"}
EXECUTION_POLICIES = {"AUTO_AFTER_APPROVAL", "CONFIRM_HIGH_RISK", "HUMAN_ONLY"}
BOUNDED_ACTION_TYPES = {"checkpoint_branch", "resolve_attention"}
LEGAL_TRANSITIONS = {
    "DETECTED": {"STAGED", "FAILED"},
    "STAGED": {"NEEDS_DECISION", "FAILED"},
    "NEEDS_DECISION": {"APPROVED", "REJECTED", "DEFERRED", "ESCALATED"},
    "DEFERRED": {"NEEDS_DECISION", "REJECTED"},
    "ESCALATED": {"NEEDS_DECISION", "APPROVED", "REJECTED", "DEFERRED"},
    "APPROVED": {"EXECUTING", "REJECTED"},
    "EXECUTING": {"VERIFYING", "FAILED", "OUTCOME_UNKNOWN"},
    "VERIFYING": {"RESOLVED", "FAILED", "OUTCOME_UNKNOWN"},
    "OUTCOME_UNKNOWN": {"NEEDS_DECISION", "ESCALATED"},
    "RESOLVED": set(), "REJECTED": set(), "FAILED": set(),
}

JSON_FIELDS = {
    "provenance", "evidence_refs", "recommended_action", "alternatives",
    "verification_policy", "outcome",
}


def _loads(value, fallback):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return fallback
    return fallback if parsed is None else parsed


def _dumps(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _attention_intent_id(attention_id: str) -> str:
    digest = hashlib.sha256(attention_id.encode("utf-8")).hexdigest()[:20]
    return f"intent_attn_{digest}"


def _priority(severity: str) -> str:
    return {"critical": "P0", "warning": "P1"}.get(str(severity).lower(), "P2")


def _risk_tier(severity: str) -> str:
    return "high" if str(severity).lower() == "critical" else "normal"


def _execution_policy(severity: str, bounded: dict | None) -> str:
    if not bounded:
        return "HUMAN_ONLY"
    if str(severity).lower() == "critical":
        return "CONFIRM_HIGH_RISK"
    return "AUTO_AFTER_APPROVAL"


def _bounded_action(actions) -> dict | None:
    if not isinstance(actions, list):
        return None
    for action in actions:
        if isinstance(action, dict) and action.get("type") in BOUNDED_ACTION_TYPES:
            return dict(action)
    return None


class ControlIntentService:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.store = GomsStore(self.root)

    def _event(self, con, intent_id: str, event_type: str, actor: str,
               detail: dict, from_status: str | None = None,
               to_status: str | None = None) -> str:
        event_id = make_id("intent_event")
        con.execute("""INSERT INTO control_intent_events
          (id,intent_id,event_type,from_status,to_status,actor,detail,created_at)
          VALUES(?,?,?,?,?,?,?,?)""",
          (event_id, intent_id, event_type, from_status, to_status,
           actor, _dumps(detail), now()))
        return event_id

    def ensure_for_attention(self, attention_id: str) -> str:
        attention_id = str(attention_id or "").strip()
        if not attention_id:
            raise KeyError("attention id is required")
        created = None
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            link = con.execute(
                "SELECT intent_id FROM attention_control_intents WHERE attention_id=?",
                (attention_id,),
            ).fetchone()
            if link:
                return str(link["intent_id"])
            row = con.execute("""SELECT id,resource_id,category,severity,title,summary,
                suggested_actions,source,created_at,updated_at
                FROM attention_items WHERE id=?""", (attention_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown attention item: {attention_id}")
            actions = _loads(row["suggested_actions"] or "[]", [])
            bounded = _bounded_action(actions)
            intent_id = _attention_intent_id(attention_id)
            ts = now()
            policy = _execution_policy(row["severity"], bounded)
            provenance = {
                "attention_id": attention_id,
                "attention_created_at": row["created_at"],
                "attention_updated_at": row["updated_at"],
                "resource_id": row["resource_id"],
                "category": row["category"],
            }
            values = (
                intent_id, "attention", row["title"], row["summary"], "NEEDS_DECISION",
                _priority(row["severity"]), _risk_tier(row["severity"]), policy,
                row["source"], attention_id, _dumps(provenance), "[]",
                _dumps(bounded or {}), _dumps(actions), 1, "{}", "{}", ts, ts,
            )
            con.execute("""INSERT INTO control_intents(
              id,kind,title,summary,status,priority,risk_tier,execution_policy,
              source,source_ref,provenance,evidence_refs,recommended_action,
              alternatives,decision_required,verification_policy,outcome,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values)
            con.execute("""INSERT INTO attention_control_intents(attention_id,intent_id,created_at)
                         VALUES(?,?,?)""", (attention_id, intent_id, ts))
            self._event(con, intent_id, "created", "system:attention-reconciler",
                        {"source_ref": attention_id, "execution_policy": policy},
                        None, "NEEDS_DECISION")
            created = intent_id
        self.store.append_event({
            "op": "control_intent_create",
            "actor": "system:attention-reconciler",
            "intent_id": created,
            "source_ref": attention_id,
        })
        return str(created)

    def _decode_intent(self, row) -> dict:
        item = dict(row)
        for field in JSON_FIELDS:
            fallback = [] if field in {"evidence_refs", "alternatives"} else {}
            item[field] = _loads(item.get(field), fallback)
        item["decision_required"] = bool(item.get("decision_required"))
        return item

    def get(self, intent_id: str) -> dict:
        with self.store.connect() as con:
            row = con.execute("SELECT * FROM control_intents WHERE id=?", (intent_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown control intent: {intent_id}")
            events = con.execute("""SELECT id,event_type,from_status,to_status,actor,detail,created_at
                FROM control_intent_events WHERE intent_id=? ORDER BY created_at,id""",
                (intent_id,)).fetchall()
        item = self._decode_intent(row)
        item["events"] = []
        for event in events:
            decoded = dict(event)
            decoded["detail"] = _loads(decoded.get("detail"), {})
            item["events"].append(decoded)
        return item

    def list_open(self, limit: int = 50) -> list[dict]:
        limit = max(1, min(int(limit), 200))
        placeholders = ",".join("?" for _ in TERMINAL_STATUSES)
        sql = f"""SELECT * FROM control_intents
            WHERE status NOT IN ({placeholders})
            ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
                     updated_at DESC LIMIT ?"""
        with self.store.connect() as con:
            rows = con.execute(sql, (*sorted(TERMINAL_STATUSES), limit)).fetchall()
        return [self._decode_intent(row) for row in rows]

    def _validate_transition(self, current: str, new_status: str) -> None:
        if current not in INTENT_STATUSES or new_status not in INTENT_STATUSES:
            raise ValueError("unknown intent status")
        if new_status not in LEGAL_TRANSITIONS[current]:
            raise ValueError(f"illegal transition: {current} -> {new_status}")

    def transition(self, intent_id: str, expected: str, new_status: str, detail: dict) -> dict:
        expected = str(expected).upper()
        new_status = str(new_status).upper()
        detail = dict(detail or {})
        actor = str(detail.get("actor") or "system")
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT status FROM control_intents WHERE id=?", (intent_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown control intent: {intent_id}")
            current = str(row["status"])
            if current != expected:
                raise ValueError(f"status mismatch: expected {expected}, found {current}")
            self._validate_transition(current, new_status)
            ts = now()
            resolved_at = ts if new_status == "RESOLVED" else None
            con.execute("""UPDATE control_intents SET status=?,updated_at=?,
                resolved_at=CASE WHEN ? IS NULL THEN resolved_at ELSE ? END WHERE id=?""",
                (new_status, ts, resolved_at, resolved_at, intent_id))
            self._event(con, intent_id, "transition", actor, detail, current, new_status)
        self.store.append_event({"op": "control_intent_transition", "actor": actor,
                                 "intent_id": intent_id, "from": current, "to": new_status})
        return self.get(intent_id)

    def claim_execution(self, intent_id: str, actor: str,
                        action_type: str, target_id: str) -> str:
        actor = str(actor or "").strip()
        if not actor:
            raise ValueError("actor is required")
        action_type = str(action_type or "").strip()
        target_id = str(target_id or "").strip()
        if not action_type or not target_id:
            raise ValueError("execution action and target are required")
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT status FROM control_intents WHERE id=?", (intent_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown control intent: {intent_id}")
            current = str(row["status"])
            if current != "APPROVED":
                raise ValueError(f"status mismatch: expected APPROVED, found {current}")
            existing = con.execute(
                "SELECT id FROM control_intent_execution_attempts WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
            if existing:
                raise ValueError("execution already claimed")
            attempt_id = make_id("intent_attempt")
            ts = now()
            con.execute("""INSERT INTO control_intent_execution_attempts
              (id,intent_id,action_type,target_id,status,result,started_at,completed_at)
              VALUES(?,?,?,?,?,'{}',?,NULL)""",
              (attempt_id, intent_id, action_type, target_id, "EXECUTING", ts))
            con.execute("UPDATE control_intents SET status='EXECUTING',updated_at=? WHERE id=?",
                        (ts, intent_id))
            self._event(con, intent_id, "transition", actor,
                        {"execution_attempt_id": attempt_id,
                         "action_type": action_type, "target_id": target_id},
                        "APPROVED", "EXECUTING")
        self.store.append_event({"op": "control_intent_execution_claim", "actor": actor,
                                 "intent_id": intent_id,
                                 "execution_attempt_id": attempt_id,
                                 "action_type": action_type, "target_id": target_id})
        return attempt_id

    def finish_execution_attempt(self, attempt_id: str, status: str, result: dict) -> None:
        status = str(status or "").upper()
        if status not in {"SUCCESS", "FAILED", "UNKNOWN"}:
            raise ValueError("invalid execution attempt status")
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT intent_id FROM control_intent_execution_attempts WHERE id=?",
                              (attempt_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown execution attempt: {attempt_id}")
            con.execute("""UPDATE control_intent_execution_attempts
              SET status=?,result=?,completed_at=? WHERE id=?""",
              (status, _dumps(result or {}), now(), attempt_id))
        self.store.append_event({"op": "control_intent_execution_finish",
                                 "actor": "system:manfred-control",
                                 "intent_id": row["intent_id"],
                                 "execution_attempt_id": attempt_id,
                                 "status": status})

    def mark_active_execution_unknown(self, intent_id: str) -> None:
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("""UPDATE control_intent_execution_attempts
              SET status='UNKNOWN',completed_at=?
              WHERE intent_id=? AND status='EXECUTING'""", (now(), intent_id))

    def decide(self, intent_id: str, decision: str, actor: str, payload: dict | None = None) -> dict:
        decision = str(decision or "").upper()
        targets = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "DEFER": "DEFERRED"}
        if decision not in targets:
            raise ValueError("unsupported decision")
        actor = str(actor or "").strip()
        if not actor:
            raise ValueError("actor is required")
        payload = dict(payload or {})
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT status FROM control_intents WHERE id=?", (intent_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown control intent: {intent_id}")
            current = str(row["status"])
            new_status = targets[decision]
            self._validate_transition(current, new_status)
            ts = now()
            con.execute("UPDATE control_intents SET status=?,updated_at=? WHERE id=?",
                        (new_status, ts, intent_id))
            detail = {"decision": decision, "payload": payload}
            self._event(con, intent_id, "decision", actor, detail, current, new_status)
        self.store.append_event({"op": "control_intent_decision", "actor": actor,
                                 "intent_id": intent_id, "decision": decision,
                                 "from": current, "to": new_status})
        return self.get(intent_id)

    def link_conversation(self, intent_id: str, role: str, conversation_id: str | None,
                          url: str | None, actor: str) -> dict:
        role = str(role or "").lower()
        if role not in {"origin", "execution"}:
            raise ValueError("conversation role must be origin or execution")
        actor = str(actor or "").strip()
        if not actor:
            raise ValueError("actor is required")
        id_col = f"{role}_conversation_id"
        url_col = f"{role}_conversation_url"
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            if not con.execute("SELECT 1 FROM control_intents WHERE id=?", (intent_id,)).fetchone():
                raise KeyError(f"Unknown control intent: {intent_id}")
            ts = now()
            con.execute(
                f"UPDATE control_intents SET {id_col}=?,{url_col}=?,updated_at=? WHERE id=?",
                (conversation_id, url, ts, intent_id),
            )
            detail = {"role": role, "conversation_id": conversation_id, "url": url}
            self._event(con, intent_id, "conversation_link", actor, detail)
        self.store.append_event({"op": "control_intent_conversation_link", "actor": actor,
                                 "intent_id": intent_id, "role": role,
                                 "conversation_id": conversation_id})
        return self.get(intent_id)
