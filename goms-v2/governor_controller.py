#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from governor import decide_reconciliation


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
    def _connect(self):
        con = sqlite3.connect(self.db, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def _ensure_schema(self):
        with self._connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS governor_reconciliations (
              resource_id TEXT PRIMARY KEY,
              disposition TEXT NOT NULL,
              reason TEXT NOT NULL DEFAULT '',
              attempt_count INTEGER NOT NULL DEFAULT 0,
              last_action TEXT,
              last_result TEXT NOT NULL DEFAULT '{}',
              observed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS governor_actions (
              id TEXT PRIMARY KEY,
              resource_id TEXT NOT NULL,
              generation INTEGER NOT NULL DEFAULT 0,
              action TEXT NOT NULL,
              status TEXT NOT NULL,
              attempt INTEGER NOT NULL,
              result TEXT NOT NULL DEFAULT '{}',
              started_at TEXT NOT NULL,
              completed_at TEXT
            );
            """)
    def _no_executor(self, action, resource):
        return {"ok": False, "detail": f"no executor registered for {action}"}

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
        needs_attention = decision["disposition"] in {
            "HUMAN_REQUIRED", "ESCALATE", "PROPOSE"
        }
        if not needs_attention:
            con.execute(
                "update attention_items set status='resolved',updated_at=? where id=?",
                (now(), attention_id),
            )
            return
        severity = "critical" if decision["disposition"] in {"HUMAN_REQUIRED", "ESCALATE"} else "warning"
        ts = now()
        title = f"Governor: {resource['name']} requires attention"
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
            title, decision["reason"], ts, ts,
        ))
    def _record_action(self, con, resource, action, attempt, result):
        started = now()
        action_id = stable_id(
            "govact", f"{resource['id']}|{resource['generation']}|{action}|{attempt}|{started}"
        )
        status = "SUCCESS" if result.get("ok") else "FAILED"
        con.execute("""
          insert into governor_actions(
            id,resource_id,generation,action,status,attempt,result,started_at,completed_at)
          values(?,?,?,?,?,?,?,?,?)
        """, (
            action_id, resource["id"], int(resource.get("generation") or 0),
            action, status, attempt, json.dumps(result, sort_keys=True), started, now(),
        ))

    def reconcile_all(self):
        output = []
        with self._connect() as con:
            resources = [dict(r) for r in con.execute(
                "select * from resources order by kind,name"
            ).fetchall()]
            for resource in resources:
                attempts = self._attempt_count(con, resource["id"])
                resource["attempt_count"] = attempts
                decision = decide_reconciliation(resource)
                result = None
                if decision["disposition"] == "AUTO_REPAIR":
                    attempt = attempts + 1
                    result = dict(self.executor(decision["action"], resource) or {})
                    self._record_action(con, resource, decision["action"], attempt, result)
                    attempts = attempt
                self._upsert_reconciliation(con, resource, decision, attempts, result)
                self._attention(con, resource, decision)
                output.append({**decision, "resource_id": resource["id"], "result": result})
            con.commit()
        return output
