#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from governor import decide_reconciliation

SCHEMA = Path(__file__).resolve().with_name("schema.sql")
MAX_EXECUTING_AGE_SECONDS = 300


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


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode()).hexdigest()[:24]
    return f"{prefix}_{digest}"


class GovernorController:
    def __init__(self, db: str | Path, executor: Callable | None = None):
        self.db = Path(db)
        self.executor = executor or self._no_executor
        self._ensure_schema()

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

    def _ensure_schema(self):
        with self._connect() as con:
            con.executescript(SCHEMA.read_text())

    def _no_executor(self, action, resource):
        return {"ok": False, "error": "no_executor_registered"}

    def _attempt_count(self, con, resource_id: str) -> int:
        row = con.execute(
            "select attempt_count from governor_reconciliations where resource_id=?",
            (resource_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    def _upsert_reconciliation(self, con, resource, decision, attempts, result=None):
        con.execute("""
          insert into governor_reconciliations(
            resource_id,disposition,reason,attempt_count,last_action,last_result,observed_at)
          values(?,?,?,?,?,?,?)
          on conflict(resource_id) do update set
            disposition=excluded.disposition, reason=excluded.reason,
            attempt_count=excluded.attempt_count, last_action=excluded.last_action,
            last_result=excluded.last_result, observed_at=excluded.observed_at
        """, (
            resource["id"], decision["disposition"], decision["reason"], attempts,
            decision.get("action"), json.dumps(result or {}, sort_keys=True), now(),
        ))

    def _attention(self, con, resource, decision):
        attention_id = stable_id("attn", "GovernorController|" + resource["id"])
        needs_attention = decision["disposition"] in {"HUMAN_REQUIRED", "ESCALATE", "PROPOSE"}
        if not needs_attention:
            con.execute("update attention_items set status='resolved',updated_at=? where id=?",
                        (now(), attention_id))
            return
        severity = "critical" if decision["disposition"] in {"HUMAN_REQUIRED", "ESCALATE"} else "warning"
        ts = now()
        con.execute("""
          insert into attention_items(
            id,resource_id,category,severity,title,summary,status,
            suggested_actions,source,created_at,updated_at)
          values(?,?,?,?,?,?,'open','[]','GovernorController',?,?)
          on conflict(id) do update set
            severity=excluded.severity,title=excluded.title,summary=excluded.summary,
            status='open',updated_at=excluded.updated_at
        """, (
            attention_id, resource["id"], "governor", severity,
            f"Governor: {resource['name']} requires attention", decision["reason"], ts, ts,
        ))

    def _persist_decision(self, resource, decision, attempts, result=None):
        with self._connect() as con:
            self._upsert_reconciliation(con, resource, decision, attempts, result)
            self._attention(con, resource, decision)

    def _claim_action(self, resource, decision):
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            executing = con.execute("""
              select id,started_at from governor_actions
              where resource_id=? and generation=? and status='EXECUTING' limit 1
            """, (resource["id"], int(resource.get("generation") or 0))).fetchone()
            attempts = self._attempt_count(con, resource["id"])
            current = dict(resource); current["attempt_count"] = attempts
            current_decision = decide_reconciliation(current)
            if current_decision["disposition"] != "AUTO_REPAIR":
                self._upsert_reconciliation(con, resource, current_decision, attempts)
                self._attention(con, resource, current_decision)
                return None, current_decision, attempts
            if executing:
                if _is_stale(executing["started_at"], MAX_EXECUTING_AGE_SECONDS):
                    con.execute("update governor_actions set status='STALE',completed_at=? where id=?",
                                (now(), executing["id"]))
                    escalation = {"disposition": "ESCALATE", "action": None,
                                  "reason": "stale executing repair requires adjudication"}
                    self._upsert_reconciliation(con, resource, escalation, attempts,
                                                {"stale_action_id": executing["id"]})
                    self._attention(con, resource, escalation)
                    return None, escalation, attempts
                waiting = {"disposition": "OBSERVE_WAIT", "action": None,
                           "reason": "repair action already executing"}
                return None, waiting, attempts
            attempt = attempts + 1
            action = current_decision["action"]
            action_id = stable_id(
                "govact", f"{resource['id']}|{resource.get('generation',0)}|{action}|{attempt}"
            )
            con.execute("""
              insert into governor_actions(
                id,resource_id,generation,action,status,attempt,result,started_at,completed_at)
              values(?,?,?,?,? ,?,'{}',?,null)
            """, (action_id, resource["id"], int(resource.get("generation") or 0),
                  action, "EXECUTING", attempt, now()))
            self._upsert_reconciliation(
                con, resource, current_decision, attempt, {"state": "EXECUTING", "action_id": action_id}
            )
            return action_id, current_decision, attempt

    def _finish_action(self, action_id, resource, decision, attempt, result):
        status = "SUCCESS" if result.get("ok") else "FAILED"
        with self._connect() as con:
            con.execute("""
              update governor_actions set status=?,result=?,completed_at=? where id=?
            """, (status, json.dumps(result, sort_keys=True), now(), action_id))
            self._upsert_reconciliation(con, resource, decision, attempt, result)
            self._attention(con, resource, decision)
        return status

    def reconcile_all(self):
        with self._connect() as con:
            resources = [dict(r) for r in con.execute(
                "select * from resources order by kind,name"
            ).fetchall()]
        output = []
        for resource in resources:
            with self._connect() as con:
                attempts = self._attempt_count(con, resource["id"])
            current = dict(resource); current["attempt_count"] = attempts
            decision = decide_reconciliation(current)
            if decision["disposition"] != "AUTO_REPAIR":
                self._persist_decision(resource, decision, attempts)
                output.append({**decision, "resource_id": resource["id"], "result": None})
                continue

            action_id, effective, attempt = self._claim_action(resource, decision)
            if not action_id:
                output.append({**effective, "resource_id": resource["id"], "result": None})
                continue
            try:
                result = dict(self.executor(effective["action"], resource) or {})
            except Exception:
                result = {"ok": False, "error": "executor_failed"}
            try:
                self._finish_action(action_id, resource, effective, attempt, result)
            except sqlite3.Error:
                result = {"ok": False, "error": "repair_outcome_unknown", "action_id": action_id}
            output.append({**effective, "resource_id": resource["id"], "result": result})
        return output
