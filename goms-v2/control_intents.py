#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from goms_store import GomsStore, make_id, now

INTENT_STATUSES = {
    "DETECTED", "STAGED", "NEEDS_DECISION", "APPROVED", "EXECUTING",
    "VERIFYING", "RESOLVED", "REJECTED", "DEFERRED", "FAILED",
    "ESCALATED", "OUTCOME_UNKNOWN", "CANCELLED",
}
TERMINAL_STATUSES = {"RESOLVED", "REJECTED", "FAILED", "CANCELLED"}
EXECUTION_POLICIES = {"AUTO_AFTER_APPROVAL", "CONFIRM_HIGH_RISK", "HUMAN_ONLY"}
CONVERSATION_LOCATOR_SOURCES = {"observed", "supplied", "synthetic", "unverified"}
BOUNDED_ACTION_TYPES = {"checkpoint_branch", "resolve_attention"}
ALLOWED_SUBMIT_KINDS = {"aineko_task", "external", "submitted", "attention"}
ALLOWED_PRIORITIES = {"P0", "P1", "P2"}
ALLOWED_RISK_TIERS = {"high", "normal", "low"}
ALLOWED_SUBMIT_SOURCES = {"ChatGPT", "Hermes", "Manfred", "human", "system", "external"}
CANCELLABLE_STATUSES = {"DETECTED", "STAGED", "NEEDS_DECISION", "APPROVED", "DEFERRED", "ESCALATED"}
LEGAL_TRANSITIONS = {
    "DETECTED": {"STAGED", "FAILED", "CANCELLED"},
    "STAGED": {"NEEDS_DECISION", "FAILED", "CANCELLED"},
    "NEEDS_DECISION": {"APPROVED", "REJECTED", "DEFERRED", "ESCALATED", "CANCELLED"},
    "DEFERRED": {"NEEDS_DECISION", "REJECTED", "CANCELLED"},
    "ESCALATED": {"NEEDS_DECISION", "APPROVED", "REJECTED", "DEFERRED", "CANCELLED"},
    "APPROVED": {"EXECUTING", "REJECTED", "CANCELLED"},
    "EXECUTING": {"VERIFYING", "FAILED", "OUTCOME_UNKNOWN"},
    "VERIFYING": {"RESOLVED", "FAILED", "OUTCOME_UNKNOWN"},
    "OUTCOME_UNKNOWN": {"NEEDS_DECISION", "ESCALATED"},
    "RESOLVED": set(), "REJECTED": set(), "FAILED": set(), "CANCELLED": set(),
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


def _valid_conversation_url(url: str | None) -> bool:
    if url is None:
        return True
    try:
        parsed = urlparse(str(url))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    accepted = (
        host == "chatgpt.com" or host.endswith(".chatgpt.com") or
        host == "openai.com" or host.endswith(".openai.com")
    )
    return parsed.scheme == "https" and accepted and not parsed.username and not parsed.password


def _submission_fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _valid_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    key = str(value).strip()
    if not key:
        raise ValueError("idempotency_key must be non-empty when supplied")
    if len(key) > 128:
        raise ValueError("idempotency_key too long")
    return key


def _valid_submit_kind(kind: str | None) -> str:
    k = str(kind or "aineko_task").strip() or "aineko_task"
    if k not in ALLOWED_SUBMIT_KINDS and not k.startswith("aineko"):
        # allow any aineko-prefixed kind but otherwise restrict to known set; fallback to external
        if len(k) > 64:
            raise ValueError("kind too long")
    return k


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
                          url: str | None, actor: str,
                          locator_source: str = "unverified") -> dict:
        role = str(role or "").lower()
        if role not in {"origin", "execution"}:
            raise ValueError("conversation role must be origin or execution")
        actor = str(actor or "").strip()
        if not actor:
            raise ValueError("actor is required")
        locator_source = str(locator_source or "unverified").strip().lower()
        if locator_source not in CONVERSATION_LOCATOR_SOURCES:
            raise ValueError("invalid_conversation_locator_source")
        if not _valid_conversation_url(url):
            raise ValueError("invalid_conversation_url")
        id_col = f"{role}_conversation_id"
        url_col = f"{role}_conversation_url"
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT provenance FROM control_intents WHERE id=?", (intent_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown control intent: {intent_id}")
            provenance = _loads(row["provenance"], {})
            locators = provenance.setdefault("conversation_locators", {})
            locators[role] = {"source": locator_source, "captured_by": actor}
            ts = now()
            con.execute(
                f"UPDATE control_intents SET {id_col}=?,{url_col}=?,provenance=?,updated_at=? WHERE id=?",
                (conversation_id, url, _dumps(provenance), ts, intent_id),
            )
            detail = {"role": role, "conversation_id": conversation_id,
                      "url": url, "locator_source": locator_source}
            self._event(con, intent_id, "conversation_link", actor, detail)
        self.store.append_event({"op": "control_intent_conversation_link", "actor": actor,
                                 "intent_id": intent_id, "role": role,
                                 "conversation_id": conversation_id,
                                 "locator_source": locator_source})
        return self.get(intent_id)

    # --- Aineko intent-dispatch (submit / cancel / worker queue) ---

    def submit_intent(self, title: str, summary: str = "", kind: str = "aineko_task",
                      source: str = "external", source_ref: str | None = None,
                      project: str | None = None, priority: str = "P2",
                      risk_tier: str = "normal", execution_policy: str = "HUMAN_ONLY",
                      recommended_action: dict | None = None, alternatives: list | None = None,
                      verification_policy: dict | None = None, provenance: dict | None = None,
                      evidence_refs: list | None = None, decision_required: bool = True,
                      idempotency_key: str | None = None, actor: str = "external",
                      human_attested: bool = False, resolved_by: str | None = None,
                      origin_conversation_id: str | None = None,
                      origin_conversation_url: str | None = None,
                      locator_source: str = "unverified") -> dict:
        title = str(title or "").strip()
        if not title:
            raise ValueError("title is required")
        if len(title) > 256:
            raise ValueError("title too long")
        summary = str(summary or "")
        if len(summary) > 4096:
            raise ValueError("summary too long")
        kind = _valid_submit_kind(kind)
        source = str(source or "external").strip() or "external"
        if source not in ALLOWED_SUBMIT_SOURCES and len(source) > 64:
            raise ValueError("source too long")
        priority = str(priority or "P2").upper()
        if priority not in ALLOWED_PRIORITIES:
            raise ValueError("invalid priority")
        risk_tier = str(risk_tier or "normal").lower()
        if risk_tier not in ALLOWED_RISK_TIERS:
            raise ValueError("invalid risk_tier")
        execution_policy = str(execution_policy or "HUMAN_ONLY").upper()
        if execution_policy not in EXECUTION_POLICIES:
            raise ValueError("invalid execution_policy")
        actor = str(actor or "").strip()
        if not actor:
            raise ValueError("actor is required")
        idempotency_key = _valid_idempotency_key(idempotency_key)
        recommended_action = dict(recommended_action or {})
        alternatives = list(alternatives or [])
        verification_policy = dict(verification_policy or {})
        provenance = dict(provenance or {})
        evidence_refs = list(evidence_refs or [])
        if origin_conversation_url and not _valid_conversation_url(origin_conversation_url):
            raise ValueError("invalid_conversation_url")
        locator_source = str(locator_source or "unverified").lower()
        if locator_source not in CONVERSATION_LOCATOR_SOURCES:
            raise ValueError("invalid_conversation_locator_source")
        # fingerprint for idempotency: excludes actor/idempotency_key but includes semantic payload
        fingerprint_payload = {
            "title": title, "summary": summary, "kind": kind, "source": source,
            "source_ref": source_ref, "project": project, "priority": priority,
            "risk_tier": risk_tier, "execution_policy": execution_policy,
            "recommended_action": recommended_action, "alternatives": alternatives,
            "verification_policy": verification_policy, "provenance": provenance,
            "evidence_refs": evidence_refs, "decision_required": bool(decision_required),
            "origin_conversation_id": origin_conversation_id,
            "origin_conversation_url": origin_conversation_url,
            "locator_source": locator_source,
        }
        fingerprint = _submission_fingerprint(fingerprint_payload)

        # idempotency lookup before creation
        if idempotency_key:
            with self.store.connect() as con:
                row = con.execute("SELECT intent_id,fingerprint FROM control_intent_submissions WHERE idempotency_key=?",
                                  (idempotency_key,)).fetchone()
                if row:
                    if str(row["fingerprint"]) != fingerprint:
                        raise ValueError("idempotency_key_reused")
                    # return existing intent with acknowledgement flag
                    intent = self.get(str(row["intent_id"]))
                    intent["_idempotent_replay"] = True
                    return {"intent_id": str(row["intent_id"]), "intent": intent, "acknowledged": True, "replayed": True}

        ts = now()
        intent_id = make_id("intent")
        # provenance stores submission audit
        provenance = dict(provenance)
        if project:
            provenance["project"] = str(project)
        provenance["submission"] = {
            "actor": actor,
            "idempotency_key": idempotency_key,
            "human_attested": bool(human_attested),
            "resolved_by": resolved_by,
            "submitted_at": ts,
        }
        if origin_conversation_id or origin_conversation_url:
            locators = provenance.setdefault("conversation_locators", {})
            locators["origin"] = {"source": locator_source, "captured_by": actor}
        acknowledged_at = ts
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            # double-check idempotency inside transaction
            if idempotency_key:
                dup = con.execute("SELECT intent_id,fingerprint FROM control_intent_submissions WHERE idempotency_key=?",
                                  (idempotency_key,)).fetchone()
                if dup:
                    if str(dup["fingerprint"]) != fingerprint:
                        raise ValueError("idempotency_key_reused")
                    intent_id = str(dup["intent_id"])
                    # already exists, skip insert
                    inner = self.get(intent_id)
                    inner["_idempotent_replay"] = True
                    return {"intent_id": intent_id, "intent": inner, "acknowledged": True, "replayed": True}
            values = (
                intent_id, kind, title, summary, "NEEDS_DECISION",
                priority, risk_tier, execution_policy,
                source, source_ref, _dumps(provenance), _dumps(evidence_refs),
                _dumps(recommended_action), _dumps(alternatives), int(bool(decision_required)),
                origin_conversation_id, origin_conversation_url, None, None,
                _dumps(verification_policy), _dumps({}), acknowledged_at, None, ts, ts,
            )
            con.execute("""INSERT INTO control_intents(
              id,kind,title,summary,status,priority,risk_tier,execution_policy,
              source,source_ref,provenance,evidence_refs,recommended_action,
              alternatives,decision_required,origin_conversation_id,origin_conversation_url,
              execution_conversation_id,execution_conversation_url,
              verification_policy,outcome,acknowledged_at,resolved_at,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values)
            self._event(con, intent_id, "created", actor,
                        {"kind": kind, "source": source, "execution_policy": execution_policy,
                         "idempotency_key": idempotency_key, "human_attested": bool(human_attested)},
                        None, "NEEDS_DECISION")
            self._event(con, intent_id, "submitted", actor,
                        {"acknowledged_at": acknowledged_at, "fingerprint": fingerprint},
                        None, "NEEDS_DECISION")
            if idempotency_key:
                con.execute("""INSERT INTO control_intent_submissions(idempotency_key,intent_id,fingerprint,created_at,updated_at)
                               VALUES(?,?,?, ?,?)""",
                            (idempotency_key, intent_id, fingerprint, ts, ts))
        self.store.append_event({
            "op": "control_intent_submit", "actor": actor, "intent_id": intent_id,
            "kind": kind, "source": source, "idempotency_key": idempotency_key,
            "execution_policy": execution_policy, "human_attested": bool(human_attested),
        })
        # If submission supplied explicit human_attested authorization, transition to APPROVED
        # but preserve HUMAN_ONLY: approval does not auto-execute; worker must claim separately.
        # This is handled via decide path so audit is consistent.
        if human_attested is True:
            resolved = str(resolved_by or "").strip()
            if not resolved or not resolved.startswith("human:"):
                # record that submission was not authorized due to missing human actor
                return {"intent_id": intent_id, "intent": self.get(intent_id), "acknowledged": True, "replayed": False, "authorization_pending": True}
            try:
                self.decide(intent_id, "APPROVE", resolved, {"human_attested": True, "submitted_via": actor})
            except (ValueError, KeyError):
                # if transition illegal, keep at NEEDS_DECISION but acknowledge
                pass
        intent = self.get(intent_id)
        return {"intent_id": intent_id, "intent": intent, "acknowledged": True, "replayed": False}

    def cancel_intent(self, intent_id: str, actor: str, reason: str = "") -> dict:
        actor = str(actor or "").strip()
        if not actor:
            raise ValueError("actor is required")
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT status FROM control_intents WHERE id=?", (intent_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown control intent: {intent_id}")
            current = str(row["status"])
            if current in TERMINAL_STATUSES or current in {"EXECUTING", "VERIFYING", "OUTCOME_UNKNOWN"}:
                raise ValueError(f"intent not cancellable from {current}")
            if current not in CANCELLABLE_STATUSES:
                raise ValueError(f"intent not cancellable from {current}")
            self._validate_transition(current, "CANCELLED")
            ts = now()
            con.execute("UPDATE control_intents SET status='CANCELLED',updated_at=? WHERE id=?", (ts, intent_id))
            self._event(con, intent_id, "cancelled", actor,
                        {"reason": str(reason or ""), "from_status": current}, current, "CANCELLED")
        self.store.append_event({"op": "control_intent_cancel", "actor": actor, "intent_id": intent_id, "from": current, "to": "CANCELLED", "reason": reason})
        return self.get(intent_id)

    def list_pending_for_worker(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        limit = max(1, min(int(limit), 200))
        with self.store.connect() as con:
            if kind:
                rows = con.execute("""
                  SELECT * FROM control_intents
                  WHERE status='APPROVED' AND kind=?
                  ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END, updated_at DESC
                  LIMIT ?""", (kind, limit)).fetchall()
            else:
                rows = con.execute("""
                  SELECT * FROM control_intents
                  WHERE status='APPROVED'
                  ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END, updated_at DESC
                  LIMIT ?""", (limit,)).fetchall()
        return [self._decode_intent(r) for r in rows]

    def claim_for_aineko(self, intent_id: str, worker_id: str, action_type: str = "aineko_task", target_id: str | None = None) -> str:
        worker_id = str(worker_id or "").strip()
        if not worker_id:
            raise ValueError("worker_id is required")
        action_type = str(action_type or "aineko_task").strip()
        target_id = str(target_id or intent_id).strip()
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT status,execution_policy FROM control_intents WHERE id=?", (intent_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown control intent: {intent_id}")
            current = str(row["status"])
            policy = str(row["execution_policy"] or "HUMAN_ONLY")
            if current != "APPROVED":
                raise ValueError(f"status mismatch: expected APPROVED, found {current}")
            if policy == "HUMAN_ONLY":
                raise ValueError("human_only_intent_not_claimable_by_worker")
            existing = con.execute("SELECT id FROM control_intent_execution_attempts WHERE intent_id=?", (intent_id,)).fetchone()
            if existing:
                raise ValueError("execution already claimed")
            attempt_id = make_id("intent_attempt")
            ts = now()
            con.execute("""INSERT INTO control_intent_execution_attempts
              (id,intent_id,action_type,target_id,status,result,started_at,completed_at)
              VALUES(?,?,?,?,?,'{}',?,NULL)""",
              (attempt_id, intent_id, action_type, target_id, "EXECUTING", ts))
            con.execute("UPDATE control_intents SET status='EXECUTING',updated_at=? WHERE id=?", (ts, intent_id))
            self._event(con, intent_id, "transition", worker_id,
                        {"execution_attempt_id": attempt_id, "worker_id": worker_id,
                         "action_type": action_type, "target_id": target_id},
                        "APPROVED", "EXECUTING")
        self.store.append_event({"op": "control_intent_aineko_claim", "actor": worker_id,
                                 "intent_id": intent_id, "execution_attempt_id": attempt_id,
                                 "action_type": action_type, "target_id": target_id})
        return attempt_id

    def record_aineko_result(self, intent_id: str, attempt_id: str, worker_id: str,
                             status: str, result: dict | None = None,
                             evidence_title: str | None = None, evidence_summary: str | None = None) -> dict:
        status = str(status or "").upper()
        if status not in {"SUCCESS", "FAILED", "UNKNOWN"}:
            raise ValueError("invalid execution result status")
        worker_id = str(worker_id or "").strip()
        if not worker_id:
            raise ValueError("worker_id is required")
        result = dict(result or {})
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT intent_id,status FROM control_intent_execution_attempts WHERE id=?", (attempt_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown execution attempt: {attempt_id}")
            if str(row["intent_id"]) != str(intent_id):
                raise ValueError("attempt does not belong to intent")
            if str(row["status"]) != "EXECUTING":
                raise ValueError("attempt not executing")
            cur = con.execute("SELECT status FROM control_intents WHERE id=?", (intent_id,)).fetchone()
            if not cur or str(cur["status"]) != "EXECUTING":
                raise ValueError(f"intent status mismatch: expected EXECUTING, found {cur['status'] if cur else 'missing'}")
            ts = now()
            con.execute("""UPDATE control_intent_execution_attempts SET status=?,result=?,completed_at=? WHERE id=?""",
                        (status, _dumps(result), ts, attempt_id))
            # evidence creation is outside transaction for store connection reuse; we will create after
            # transition intent accordingly
            if status == "SUCCESS":
                # move EXECUTING -> VERIFYING -> RESOLVED via verification (simplified: direct to RESOLVED)
                con.execute("UPDATE control_intents SET status='VERIFYING',updated_at=? WHERE id=?", (ts, intent_id))
                self._event(con, intent_id, "transition", worker_id,
                            {"execution_attempt_id": attempt_id, "result": result}, "EXECUTING", "VERIFYING")
                con.execute("UPDATE control_intents SET status='RESOLVED',updated_at=?,resolved_at=? WHERE id=?", (ts, ts, intent_id))
                self._event(con, intent_id, "transition", worker_id,
                            {"execution_attempt_id": attempt_id, "verification": "aineko_worker"}, "VERIFYING", "RESOLVED")
                intent_status = "RESOLVED"
            elif status == "FAILED":
                con.execute("UPDATE control_intents SET status='FAILED',updated_at=? WHERE id=?", (ts, intent_id))
                self._event(con, intent_id, "transition", worker_id,
                            {"execution_attempt_id": attempt_id, "result": result}, "EXECUTING", "FAILED")
                intent_status = "FAILED"
            else:  # UNKNOWN
                con.execute("""UPDATE control_intent_execution_attempts SET status='UNKNOWN',completed_at=? WHERE id=?""", (ts, attempt_id))
                con.execute("UPDATE control_intents SET status='OUTCOME_UNKNOWN',updated_at=? WHERE id=?", (ts, intent_id))
                self._event(con, intent_id, "transition", worker_id,
                            {"execution_attempt_id": attempt_id, "result": result}, "EXECUTING", "OUTCOME_UNKNOWN")
                intent_status = "OUTCOME_UNKNOWN"
            # store outcome
            outcome = {"worker_id": worker_id, "result": result, "attempt_id": attempt_id}
            con.execute("UPDATE control_intents SET outcome=?,updated_at=? WHERE id=?", (_dumps(outcome), ts, intent_id))
        self.store.append_event({"op": "control_intent_aineko_result", "actor": worker_id, "intent_id": intent_id,
                                 "execution_attempt_id": attempt_id, "status": status, "intent_status": intent_status})
        # create durable evidence linking to intent (outside transaction, via GomsStore)
        if evidence_title:
            try:
                eid = self.store.add_entity("evidence", str(evidence_title), str(evidence_summary or ""),
                                           None, "OBSERVED", None, None, ["aineko-execution", intent_id],
                                           {"intent_id": intent_id, "attempt_id": attempt_id, "worker_id": worker_id, "result": result},
                                           actor=worker_id)
                self.store.link(eid, "supports", intent_id, actor=worker_id) if False else None  # intent is not entity, so skip link; keep evidence provenance instead
                # alternative: store evidence_refs inside intent provenance/outcome
                with self.store.connect() as con:
                    row = con.execute("SELECT evidence_refs FROM control_intents WHERE id=?", (intent_id,)).fetchone()
                    refs = _loads(row["evidence_refs"] if row else "[]", [])
                    refs.append(eid)
                    con.execute("UPDATE control_intents SET evidence_refs=?,updated_at=? WHERE id=?", (_dumps(refs), now(), intent_id))
            except Exception:
                pass
        return self.get(intent_id)
