#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from attention_market import AttentionMarket
from control_intents import ControlIntentService
from goms_store import GomsStore, make_id

SEVERITIES = {"INFO", "ACTION_REQUIRED", "URGENT", "CRITICAL"}
ACTIVE_STATES = {"RAISED", "DELIVERED", "SEEN", "ACKNOWLEDGED"}
TERMINAL_INTENT_STATES = {"RESOLVED", "REJECTED", "FAILED"}
DEFAULT_ESCALATION_SECONDS = {
    "INFO": 0,
    "ACTION_REQUIRED": 4 * 60 * 60,
    "URGENT": 30 * 60,
    "CRITICAL": 10 * 60,
}


def _parse(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _dumps(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _loads(value, fallback):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return fallback
    return fallback if parsed is None else parsed


class AlertService:
    def __init__(self, root: str | Path, clock=None):
        self.root = Path(root)
        self.store = GomsStore(self.root)
        self.intents = ControlIntentService(self.root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.market = AttentionMarket(self.root, clock=self.clock)

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _ts(self) -> str:
        return self._now().isoformat()

    def _decode(self, row) -> dict:
        item = dict(row)
        item["policy"] = _loads(item.get("policy"), {})
        item["escalation_count"] = int(item.get("escalation_count") or 0)
        return item

    def get(self, alert_id: str) -> dict:
        with self.store.connect() as con:
            row = con.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
        if not row:
            raise KeyError(f"Unknown alert: {alert_id}")
        return self._decode(row)

    def list_active(self) -> list[dict]:
        with self.store.connect() as con:
            rows = con.execute("""SELECT * FROM alerts WHERE state <> 'RESOLVED'
                ORDER BY CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'URGENT' THEN 1
                     WHEN 'ACTION_REQUIRED' THEN 2 ELSE 3 END, raised_at,id""").fetchall()
        return [self._decode(row) for row in rows]

    def _policy(self, intent: dict) -> dict:
        provenance = intent.get("provenance") or {}
        raw = provenance.get("alert_policy") if isinstance(provenance, dict) else None
        return dict(raw) if isinstance(raw, dict) else {}

    def _severity(self, intent: dict, policy: dict) -> str:
        explicit = str(policy.get("severity") or "").upper()
        if explicit in SEVERITIES:
            return explicit
        status = str(intent.get("status") or "").upper()
        if status in {"APPROVED", "EXECUTING", "VERIFYING"}:
            return "INFO"
        provenance = intent.get("provenance") or {}
        category = str(provenance.get("category") or "").lower() if isinstance(provenance, dict) else ""
        if status in {"NEEDS_DECISION", "ESCALATED"} \
                and intent.get("risk_tier") == "high" and category in {"security", "safety"}:
            return "CRITICAL"
        if status in {"NEEDS_DECISION", "ESCALATED"} \
                and bool(intent.get("decision_required", True)):
            return "ACTION_REQUIRED"
        return "INFO"

    def _timing(self, severity: str, policy: dict) -> tuple[int | None, int]:
        ttl_raw = policy.get("ttl_seconds")
        ttl = None if ttl_raw in (None, "") else max(0, int(ttl_raw))
        escalation_raw = policy.get("escalation_seconds")
        escalation = DEFAULT_ESCALATION_SECONDS[severity] if escalation_raw in (None, "") else max(0, int(escalation_raw))
        return ttl, escalation

    def _active_for_key(self, con, dedupe_key: str):
        return con.execute("""SELECT * FROM alerts
            WHERE dedupe_key=? AND state <> 'RESOLVED'
            ORDER BY raised_at DESC,id DESC LIMIT 1""", (dedupe_key,)).fetchone()

    def _latest_for_key(self, con, dedupe_key: str):
        return con.execute("""SELECT * FROM alerts WHERE dedupe_key=?
            ORDER BY raised_at DESC,id DESC LIMIT 1""", (dedupe_key,)).fetchone()

    def _attention_source_cleared(self, intent_id: str) -> bool:
        with self.store.connect() as con:
            row = con.execute("""SELECT ai.status FROM attention_control_intents aci
                JOIN attention_items ai ON ai.id=aci.attention_id
                WHERE aci.intent_id=?""", (intent_id,)).fetchone()
        return bool(row and str(row["status"]).lower() == "resolved")

    def _ledger(self, op: str, actor: str, alert: dict, **extra):
        event = {"op": op, "actor": actor, "alert_id": alert["id"],
                 "intent_id": alert["intent_id"], "state": alert["state"],
                 "severity": alert["severity"]}
        event.update(extra)
        self.store.append_event(event)

    def reconcile_intent(self, intent_id: str) -> dict | None:
        intent = self.intents.get(intent_id)
        if intent["status"] in TERMINAL_INTENT_STATES:
            self.resolve_for_intent(intent_id, actor="system:alert-reconciler")
            return None
        if self._attention_source_cleared(intent_id):
            self.resolve_for_intent(intent_id, actor="system:alert-reconciler",
                                    reason="source_cleared")
            return None
        policy = self._policy(intent)
        market = self.market.classify_intent(intent_id)
        if market is not None and not market["surface_now"]:
            self.resolve_for_intent(
                intent_id,
                actor="system:attention-market",
                reason=f"attention_market_{market['attention_class'].lower()}",
            )
            self.store.append_event({
                "op": "attention_market_suppressed",
                "actor": "system:attention-market",
                "intent_id": intent_id,
                "attention_id": market["attention_id"],
                "attention_class": market["attention_class"],
                "behavior": market["behavior"],
                "mode": market["mode"],
            })
            return None
        severity = self._severity(intent, policy)
        ttl_seconds, escalation_seconds = self._timing(severity, policy)
        dedupe_key = str(policy.get("dedupe_key") or f"intent:{intent_id}")
        now_dt, ts = self._now(), self._ts()
        ledger_event = None
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = self._active_for_key(con, dedupe_key)
            if row and _parse(row["expires_at"]) and _parse(row["expires_at"]) <= now_dt:
                con.execute("""UPDATE alerts SET state='RESOLVED',resolved_at=?,
                    resolution_reason='expired',updated_at=? WHERE id=?""", (ts, ts, row["id"]))
                expired = self._decode(con.execute("SELECT * FROM alerts WHERE id=?", (row["id"],)).fetchone())
                ledger_event = ("alert_resolved", "system:alert-reconciler", expired, {"reason": "expired"})
                row = None
            latest = self._latest_for_key(con, dedupe_key)
            if row is None and latest and latest["state"] == "RESOLVED" and latest["resolution_reason"] == "expired":
                resolved_at = _parse(latest["resolved_at"])
                intent_updated = _parse(intent.get("updated_at"))
                if resolved_at and (intent_updated is None or intent_updated <= resolved_at):
                    result = None
                else:
                    result = self._create(con, intent, dedupe_key, severity, policy,
                                          ttl_seconds, escalation_seconds, now_dt, ts)
            elif row is None:
                result = self._create(con, intent, dedupe_key, severity, policy,
                                      ttl_seconds, escalation_seconds, now_dt, ts)
            else:
                result = self._refresh_active(con, row, intent, severity, policy,
                                              escalation_seconds, now_dt, ts)
        if ledger_event:
            op, actor, alert, extra = ledger_event
            self._ledger(op, actor, alert, **extra)
        if result and result.pop("_created", False):
            self._ledger("alert_raised", "system:alert-reconciler", result)
        elif result and result.pop("_escalated", False):
            self._ledger("alert_escalated", "system:alert-reconciler", result,
                         escalation_count=result["escalation_count"])
        return result

    def _create(self, con, intent, dedupe_key, severity, policy,
                ttl_seconds, escalation_seconds, now_dt, ts):
        alert_id = make_id("alert")
        expires_at = (now_dt + timedelta(seconds=ttl_seconds)).isoformat() \
            if ttl_seconds is not None else None
        next_escalation_at = (now_dt + timedelta(seconds=escalation_seconds)).isoformat() \
            if escalation_seconds > 0 else None
        reason = str(policy.get("reason") or "canonical_intent_requires_attention")
        con.execute("""INSERT INTO alerts(
          id,intent_id,dedupe_key,severity,state,title,summary,reason,policy,
          escalation_count,last_escalated_at,next_escalation_at,expires_at,
          raised_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,0,NULL,?,?,?,?)""",
          (alert_id, intent["id"], dedupe_key, severity, "RAISED",
           intent.get("title") or "", intent.get("summary") or "", reason,
           _dumps(policy), next_escalation_at, expires_at, ts, ts))
        row = con.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
        result = self._decode(row)
        result["_created"] = True
        return result

    def _refresh_active(self, con, row, intent, severity, policy,
                        escalation_seconds, now_dt, ts):
        escalation_count = int(row["escalation_count"] or 0)
        last_escalated_at = row["last_escalated_at"]
        next_escalation_at = row["next_escalation_at"]
        escalated = False
        due = _parse(next_escalation_at)
        if row["state"] != "ACKNOWLEDGED" and escalation_seconds > 0 and due and due <= now_dt:
            escalation_count += 1
            last_escalated_at = ts
            next_escalation_at = (now_dt + timedelta(seconds=escalation_seconds)).isoformat()
            escalated = True
        con.execute("""UPDATE alerts SET severity=?,title=?,summary=?,policy=?,
            escalation_count=?,last_escalated_at=?,next_escalation_at=?,updated_at=?
            WHERE id=?""",
            (severity, intent.get("title") or "", intent.get("summary") or "",
             _dumps(policy), escalation_count, last_escalated_at,
             next_escalation_at, ts, row["id"]))
        refreshed = self._decode(con.execute(
            "SELECT * FROM alerts WHERE id=?", (row["id"],)).fetchone())
        if escalated:
            refreshed["_escalated"] = True
        return refreshed

    def record_delivery(self, alert_id: str, actor: str) -> dict:
        return self._mark(alert_id, "DELIVERED", actor)

    def record_seen(self, alert_id: str, actor: str) -> dict:
        return self._mark(alert_id, "SEEN", actor)

    def acknowledge(self, alert_id: str, actor: str) -> dict:
        if not str(actor or "").startswith("human:"):
            raise ValueError("alert acknowledgement requires human actor")
        return self._mark(alert_id, "ACKNOWLEDGED", actor)

    def _mark(self, alert_id: str, target: str, actor: str) -> dict:
        ts = self._ts()
        changed = False
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown alert: {alert_id}")
            current = str(row["state"])
            if current == "RESOLVED":
                raise ValueError("resolved alert cannot be updated")
            changed = self._apply_mark(con, row, target, ts)
            result = self._decode(con.execute(
                "SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone())
        if changed:
            self._ledger("alert_state", actor, result, from_state=current, to_state=result["state"])
        return result

    def _apply_mark(self, con, row, target: str, ts: str) -> bool:
        current = str(row["state"])
        if target == "DELIVERED":
            if current != "RAISED":
                return False
            con.execute("""UPDATE alerts SET state='DELIVERED',
                delivered_at=COALESCE(delivered_at,?),updated_at=? WHERE id=?""",
                (ts, ts, row["id"]))
            return True
        if target == "SEEN":
            if current not in {"RAISED", "DELIVERED"}:
                return False
            con.execute("""UPDATE alerts SET state='SEEN',
                delivered_at=COALESCE(delivered_at,?),seen_at=COALESCE(seen_at,?),
                updated_at=? WHERE id=?""", (ts, ts, ts, row["id"]))
            return True
        if target == "ACKNOWLEDGED":
            if current == "ACKNOWLEDGED":
                return False
            con.execute("""UPDATE alerts SET state='ACKNOWLEDGED',
                delivered_at=COALESCE(delivered_at,?),seen_at=COALESCE(seen_at,?),
                acknowledged_at=COALESCE(acknowledged_at,?),updated_at=? WHERE id=?""",
                (ts, ts, ts, ts, row["id"]))
            return True
        raise ValueError(f"unsupported alert state transition: {target}")

    def resolve_for_intent(self, intent_id: str, actor: str = "system:alert-reconciler",
                           reason: str = "intent_resolved") -> int:
        ts = self._ts()
        resolved = []
        with self.store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            rows = con.execute("""SELECT * FROM alerts
                WHERE intent_id=? AND state <> 'RESOLVED'""", (intent_id,)).fetchall()
            for row in rows:
                con.execute("""UPDATE alerts SET state='RESOLVED',resolved_at=?,
                    resolution_reason=?,updated_at=? WHERE id=?""",
                    (ts, reason, ts, row["id"]))
                resolved.append(self._decode(con.execute(
                    "SELECT * FROM alerts WHERE id=?", (row["id"],)).fetchone()))
        for alert in resolved:
            self._ledger("alert_resolved", actor, alert, reason=reason)
        return len(resolved)
