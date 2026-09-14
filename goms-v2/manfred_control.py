#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from goms_store import GomsStore, BRANCH_STATUSES, make_id
from control_intents import ControlIntentService
from control_intent_reconciler import reconcile_attention_intents
from alerts import AlertService

TERMINAL_COMMAND_STATUSES = {"SUCCESS", "REJECTED", "FAILED", "UNKNOWN"}
MAX_PENDING_AGE_SECONDS = 300
MAX_INTENT_EXECUTION_AGE_SECONDS = 300


def _is_stale(timestamp: str | None, max_age_seconds: int) -> bool:
    if not timestamp:
        return True
    try:
        value = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return True
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - value).total_seconds() > max_age_seconds


def now():
    return datetime.now(timezone.utc).isoformat()


def authorized(header: str | None, token: str) -> bool:
    try:
        supplied = str(header or "").encode("utf-8", "surrogatepass")
        expected = f"Bearer {token}".encode("utf-8", "surrogatepass")
        return bool(header) and hmac.compare_digest(supplied, expected)
    except (TypeError, UnicodeError):
        return False


def command_fingerprint(command_type: str, target_id: str, payload) -> str:
    raw = json.dumps({"type": command_type, "target_id": target_id, "payload": payload},
                     sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class ManfredControl:
    def __init__(self, db_path: str | Path, intent_executors: dict | None = None):
        self.db = Path(db_path)
        self.store = GomsStore(self.db.parent)
        self.intents = ControlIntentService(self.db.parent)
        self.alerts = AlertService(self.db.parent)
        defaults = {
            "checkpoint_branch": self._checkpoint_branch,
            "resolve_attention": self._resolve_attention,
        }
        self.intent_executors = defaults if intent_executors is None else dict(intent_executors)

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.db, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def build_brief(self, limit: int = 50, *, reconcile: bool = True) -> dict:
        limit = max(1, min(int(limit), 200))
        if reconcile:
            reconcile_attention_intents(self.db.parent)
            for intent in self.intents.list_open(limit=limit):
                self.alerts.reconcile_intent(intent["id"])
        with self._connect() as con:
            con.execute("BEGIN")
            attention = [dict(r) for r in con.execute("""
              SELECT a.id,a.resource_id,a.category,a.severity,a.title,a.summary,
                     a.source,a.updated_at,m.intent_id
              FROM attention_items a
              LEFT JOIN attention_control_intents m ON m.attention_id=a.id
              WHERE a.status='open'
              ORDER BY CASE a.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                       a.updated_at DESC LIMIT ?
            """, (limit,)).fetchall()]
            governor = [dict(r) for r in con.execute("""
              SELECT resource_id,disposition,reason,attempt_count,last_result,observed_at
              FROM governor_reconciliations
              WHERE disposition IN ('HUMAN_REQUIRED','ESCALATE')
              ORDER BY observed_at DESC LIMIT ?
            """, (limit,)).fetchall()]
            branches = [dict(r) for r in con.execute("""
              SELECT id,title,project,status,objective,last_result,unresolved,
                     next_action,blocker,worker,updated_at
              FROM branches WHERE status IN ('BLOCKED','ACTIVE','DELEGATED')
              ORDER BY CASE status WHEN 'BLOCKED' THEN 0 WHEN 'ACTIVE' THEN 1 ELSE 2 END,
                       updated_at DESC LIMIT ?
            """, (limit,)).fetchall()]
            intents = [dict(r) for r in con.execute("""
              SELECT id,kind,title,summary,status,priority,risk_tier,execution_policy,
                     source,source_ref,provenance,evidence_refs,recommended_action,alternatives,
                     decision_required,origin_conversation_id,origin_conversation_url,
                     execution_conversation_id,execution_conversation_url,
                     verification_policy,outcome,updated_at
              FROM control_intents
              WHERE status NOT IN ('RESOLVED','REJECTED','FAILED')
              ORDER BY CASE status WHEN 'NEEDS_DECISION' THEN 0 WHEN 'ESCALATED' THEN 1
                                   WHEN 'EXECUTING' THEN 2 WHEN 'VERIFYING' THEN 3
                                   WHEN 'APPROVED' THEN 4 ELSE 5 END,
                       CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
                       updated_at DESC LIMIT ?
            """, (limit,)).fetchall()]
        for row in branches:
            try:
                unresolved = json.loads(row.get("unresolved") or "[]")
                row["unresolved"] = unresolved if isinstance(unresolved, list) else []
            except json.JSONDecodeError:
                row["unresolved"] = []
                row["projection_warning"] = "invalid_unresolved_json"
        for row in intents:
            for field, fallback in (("provenance", {}), ("evidence_refs", []),
                                    ("recommended_action", {}), ("alternatives", []),
                                    ("verification_policy", {}), ("outcome", {})):
                try:
                    row[field] = json.loads(row.get(field) or json.dumps(fallback))
                except json.JSONDecodeError:
                    row[field] = fallback
                    row["projection_warning"] = f"invalid_{field}_json"
            row["decision_required"] = bool(row.get("decision_required"))
        return {"attention": attention, "governor": governor,
                "branches": branches, "intents": intents}

    def _claim_command(self, key: str, ctype: str, target: str, payload):
        fingerprint = command_fingerprint(ctype, target, payload)
        payload_json = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("""
              SELECT command_type,target_id,payload,status,result,updated_at
              FROM manfred_commands WHERE idempotency_key=?
            """, (key,)).fetchone()
            if row:
                try:
                    stored_payload = json.loads(row["payload"] or "{}")
                except json.JSONDecodeError:
                    stored_payload = None
                stored_fp = command_fingerprint(row["command_type"], row["target_id"], stored_payload)
                if stored_fp != fingerprint:
                    return "MISMATCH", {"ok": False, "error": "idempotency_key_reused"}
                if row["status"] in TERMINAL_COMMAND_STATUSES:
                    try:
                        return "REPLAY", json.loads(row["result"] or "{}")
                    except json.JSONDecodeError:
                        return "REPLAY", {"ok": False, "error": "corrupt_recorded_result"}
                if row["status"] == "PENDING" and _is_stale(row["updated_at"], MAX_PENDING_AGE_SECONDS):
                    result = {"ok": False, "error": "command_outcome_unknown"}
                    con.execute("""update manfred_commands set status='UNKNOWN',result=?,updated_at=?
                                   where idempotency_key=?""",
                                (json.dumps(result, sort_keys=True), now(), key))
                    return "REPLAY", result
                return "PENDING", {"ok": False, "error": "command_in_progress"}
            ts = now()
            con.execute("""
              INSERT INTO manfred_commands(
                idempotency_key,command_type,target_id,payload,status,result,created_at,updated_at)
              VALUES(?,?,?,?,?,'{}',?,?)
            """, (key, ctype, target, payload_json, "PENDING", ts, ts))
            return "CLAIMED", None

    def _record_finish(self, key: str, status: str, result: dict):
        last_error = None
        for attempt in range(3):
            try:
                with self._connect() as con:
                    con.execute("""
                      UPDATE manfred_commands SET status=?,result=?,updated_at=?
                      WHERE idempotency_key=?
                    """, (status, json.dumps(result, sort_keys=True), now(), key))
                return
            except sqlite3.OperationalError as exc:
                last_error = exc
                time.sleep(0.05 * (attempt + 1))
        raise last_error or RuntimeError("unable to record command outcome")

    def execute_command(self, command: dict) -> dict:
        if not isinstance(command, dict):
            return {"ok": False, "error": "invalid_command"}
        key = str(command.get("idempotency_key") or "").strip()
        ctype = str(command.get("type") or "").strip()
        target = str(command.get("target_id") or "").strip()
        payload = command.get("payload", {})
        if not key:
            return {"ok": False, "error": "missing_idempotency_key"}
        if not isinstance(payload, dict):
            payload = {"_invalid_payload": True}
        try:
            claim, replay = self._claim_command(key, ctype, target, payload)
        except sqlite3.Error:
            return {"ok": False, "error": "command_claim_failed"}
        if claim != "CLAIMED":
            return replay

        try:
            if payload.get("_invalid_payload"):
                result = {"ok": False, "error": "invalid_payload"}
            elif ctype == "resolve_attention":
                result = self._resolve_attention(target, payload)
            elif ctype == "checkpoint_branch":
                result = self._checkpoint_branch(target, payload)
            elif ctype in {"approve_intent", "reject_intent", "defer_intent", "confirm_intent"}:
                result = self._execute_intent_command(ctype, target, payload)
            elif ctype in {"mark_alert_delivered", "mark_alert_seen", "acknowledge_alert"}:
                result = self._execute_alert_command(ctype, target, payload)
            else:
                result = {"ok": False, "error": "unsupported_command"}
            if result.get("ok"):
                status = "SUCCESS"
            elif result.get("error") == "intent_execution_failed":
                status = "FAILED"
            elif result.get("error") == "intent_outcome_unknown":
                status = "UNKNOWN"
            else:
                status = "REJECTED"
        except Exception:
            result = {"ok": False, "error": "command_failed"}
            status = "FAILED"
        if ctype in {"approve_intent", "reject_intent", "confirm_intent"} \
                and result.get("intent_status") in {"RESOLVED", "REJECTED", "FAILED"}:
            try:
                self.alerts.resolve_for_intent(target, actor="system:manfred-control")
            except Exception:
                result = {**result, "alert_cleanup_pending": True}
        try:
            self._record_finish(key, status, result)
        except sqlite3.Error:
            return {"ok": False, "error": "command_outcome_unknown"}
        return result

    def _execute_alert_command(self, ctype: str, alert_id: str, payload: dict) -> dict:
        actor = str(payload.get("actor") or "").strip()
        if not actor:
            return {"ok": False, "error": "actor_required"}
        if ctype in {"mark_alert_delivered", "mark_alert_seen"} and not actor.startswith("device:"):
            return {"ok": False, "error": "device_actor_required"}
        if ctype == "acknowledge_alert" and not actor.startswith("human:"):
            return {"ok": False, "error": "human_actor_required"}
        try:
            if ctype == "mark_alert_delivered":
                alert = self.alerts.record_delivery(alert_id, actor)
            elif ctype == "mark_alert_seen":
                alert = self.alerts.record_seen(alert_id, actor)
            else:
                alert = self.alerts.acknowledge(alert_id, actor)
        except KeyError:
            return {"ok": False, "error": "alert_not_found"}
        except ValueError:
            return {"ok": False, "error": "alert_state_invalid"}
        return {"ok": True, "alert_id": alert_id, "alert_state": alert["state"],
                "intent_id": alert["intent_id"]}

    def _execute_intent_command(self, ctype: str, intent_id: str, payload: dict) -> dict:
        try:
            intent = self.intents.get(intent_id)
        except KeyError:
            return {"ok": False, "error": "intent_not_found"}

        current = str(intent["status"])
        if current in {"EXECUTING", "VERIFYING"}:
            if _is_stale(intent.get("updated_at"), MAX_INTENT_EXECUTION_AGE_SECONDS):
                try:
                    self.intents.mark_active_execution_unknown(intent_id)
                    self.intents.transition(
                        intent_id, current, "OUTCOME_UNKNOWN",
                        {"actor": "system:manfred-control", "reason": "stale_execution"},
                    )
                except (KeyError, ValueError):
                    pass
                return {"ok": False, "error": "intent_outcome_unknown",
                        "intent_id": intent_id, "intent_status": "OUTCOME_UNKNOWN"}
            return {"ok": False, "error": "intent_in_progress", "intent_id": intent_id}

        actor = str(payload.get("resolved_by") or "").strip()
        if not actor:
            return {"ok": False, "error": "resolved_by_required"}

        if ctype == "reject_intent":
            return self._decide_without_execution(intent_id, "REJECT", actor, payload)
        if ctype == "defer_intent":
            return self._decide_without_execution(intent_id, "DEFER", actor, payload)
        if ctype == "approve_intent":
            if current not in {"NEEDS_DECISION", "ESCALATED"}:
                return {"ok": False, "error": "intent_not_decidable"}
            try:
                approved = self.intents.decide(intent_id, "APPROVE", actor, payload)
            except (KeyError, ValueError):
                return {"ok": False, "error": "intent_not_decidable"}
            policy = str(approved["execution_policy"])
            if policy == "HUMAN_ONLY":
                return {"ok": True, "intent_id": intent_id, "intent_status": "APPROVED",
                        "human_only": True, "execution_started": False}
            if policy == "CONFIRM_HIGH_RISK":
                return {"ok": True, "intent_id": intent_id, "intent_status": "APPROVED",
                        "confirmation_required": True, "execution_started": False}
            return self._run_intent_execution(intent_id, actor, payload)
        if ctype == "confirm_intent":
            if current != "APPROVED" or str(intent["execution_policy"]) != "CONFIRM_HIGH_RISK":
                return {"ok": False, "error": "intent_not_confirmable"}
            return self._run_intent_execution(intent_id, actor, payload)
        return {"ok": False, "error": "unsupported_command"}

    def _decide_without_execution(self, intent_id: str, decision: str,
                                  actor: str, payload: dict) -> dict:
        intent = self.intents.get(intent_id)
        if str(intent["status"]) not in {"NEEDS_DECISION", "ESCALATED"}:
            return {"ok": False, "error": "intent_not_decidable"}
        try:
            updated = self.intents.decide(intent_id, decision, actor, payload)
        except (KeyError, ValueError):
            return {"ok": False, "error": "intent_not_decidable"}
        return {"ok": True, "intent_id": intent_id, "intent_status": updated["status"],
                "execution_started": False}

    def _run_intent_execution(self, intent_id: str, actor: str, command_payload: dict) -> dict:
        try:
            intent = self.intents.get(intent_id)
            if str(intent["status"]) != "APPROVED":
                return {"ok": False, "error": "intent_not_executable"}
            action = intent.get("recommended_action") or {}
            action_type = str(action.get("type") or "")
            target_id = str(action.get("target_id") or "")
            action_payload = action.get("payload") or {}
            if not isinstance(action_payload, dict) or action_type not in self.intent_executors:
                return {"ok": False, "error": "intent_executor_not_allowed"}
            action_payload = dict(action_payload)
            for field in ("human_attested", "resolved_by"):
                if field in command_payload:
                    action_payload[field] = command_payload[field]

            try:
                attempt_id = self.intents.claim_execution(
                    intent_id, actor, action_type, target_id)
            except (KeyError, ValueError):
                return {"ok": False, "error": "intent_not_executable"}
            try:
                effect = self.intent_executors[action_type](target_id, action_payload)
            except Exception as exc:
                failure = {"reason": "executor_exception", "exception": type(exc).__name__}
                self.intents.finish_execution_attempt(attempt_id, "FAILED", failure)
                self.intents.transition(intent_id, "EXECUTING", "FAILED",
                                        {"actor": actor, **failure,
                                         "execution_attempt_id": attempt_id})
                return {"ok": False, "error": "intent_execution_failed",
                        "intent_id": intent_id, "intent_status": "FAILED",
                        "execution_attempt_id": attempt_id}
            if not isinstance(effect, dict) or effect.get("ok") is not True:
                failure = {"reason": "executor_rejected",
                           "result": effect if isinstance(effect, dict) else {}}
                self.intents.finish_execution_attempt(attempt_id, "FAILED", failure)
                self.intents.transition(intent_id, "EXECUTING", "FAILED",
                                        {"actor": actor, **failure,
                                         "execution_attempt_id": attempt_id})
                return {"ok": False, "error": "intent_execution_failed",
                        "intent_id": intent_id, "intent_status": "FAILED",
                        "execution_attempt_id": attempt_id}

            self.intents.transition(intent_id, "EXECUTING", "VERIFYING",
                                    {"actor": actor, "effect": effect,
                                     "execution_attempt_id": attempt_id})
            if not self._verify_intent_action(action_type, target_id, action_payload):
                failure = {"reason": "verification_failed", "effect": effect}
                self.intents.finish_execution_attempt(attempt_id, "FAILED", failure)
                self.intents.transition(intent_id, "VERIFYING", "FAILED",
                                        {"actor": actor, **failure,
                                         "execution_attempt_id": attempt_id})
                return {"ok": False, "error": "intent_verification_failed",
                        "intent_id": intent_id, "intent_status": "FAILED",
                        "execution_attempt_id": attempt_id}
            self.intents.finish_execution_attempt(attempt_id, "SUCCESS", effect)
            self.intents.transition(intent_id, "VERIFYING", "RESOLVED",
                                    {"actor": actor, "verification": "canonical_state",
                                     "execution_attempt_id": attempt_id})
            return {"ok": True, "intent_id": intent_id, "intent_status": "RESOLVED",
                    "execution_started": True, "execution_attempt_id": attempt_id,
                    "effect": effect}
        except (KeyError, ValueError):
            return {"ok": False, "error": "intent_not_executable"}

    def _verify_intent_action(self, action_type: str, target_id: str, payload: dict) -> bool:
        with self._connect() as con:
            if action_type == "checkpoint_branch":
                row = con.execute("SELECT status FROM branches WHERE id=?", (target_id,)).fetchone()
                return bool(row) and str(row["status"]) == str(payload.get("status") or "").upper()
            if action_type == "resolve_attention":
                row = con.execute("SELECT status FROM attention_items WHERE id=?", (target_id,)).fetchone()
                return bool(row) and str(row["status"]) == "resolved"
        return False

    def _resolve_attention(self, attention_id: str, payload: dict | None = None) -> dict:
        payload = payload or {}
        with self._connect() as con:
            row = con.execute("SELECT status,source,severity FROM attention_items WHERE id=?",
                              (attention_id,)).fetchone()
            if not row:
                return {"ok": False, "error": "target_not_found"}
            if row["source"] == "GovernorController" and row["severity"] == "critical":
                if payload.get("human_attested") is not True or not str(payload.get("resolved_by") or "").strip():
                    return {"ok": False, "error": "human_attestation_required"}
            con.execute("UPDATE attention_items SET status='resolved',updated_at=? WHERE id=?",
                        (now(), attention_id))
        return {"ok": True, "type": "resolve_attention", "target_id": attention_id}

    def _checkpoint_branch(self, branch_id: str, payload: dict) -> dict:
        status = str(payload.get("status") or "").upper()
        if status not in BRANCH_STATUSES:
            return {"ok": False, "error": "invalid_branch_status"}
        unresolved = payload.get("unresolved") or []
        if not isinstance(unresolved, list) or not all(isinstance(x, str) for x in unresolved):
            return {"ok": False, "error": "invalid_unresolved"}
        summary = payload.get("summary", "")
        next_action = payload.get("next_action", "")
        blocker = payload.get("blocker", "")
        if not all(isinstance(x, str) for x in (summary, next_action, blocker)):
            return {"ok": False, "error": "invalid_payload"}
        checkpoint_id = self.store.checkpoint(
            branch_id, status, summary, unresolved=unresolved,
            next_action=next_action, blocker=blocker,
            source="manfred-control", actor="manfred-control",
        )
        return {"ok": True, "type": "checkpoint_branch", "target_id": branch_id,
                "checkpoint_id": checkpoint_id, "status": status}
