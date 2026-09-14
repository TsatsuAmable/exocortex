#!/usr/bin/env python3
import json
import tempfile
import threading
import unittest
from pathlib import Path

from control_intents import ControlIntentService
from alerts import AlertService
from goms_store import GomsStore
from manfred_control import ManfredControl


class IntentExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="intent-execution-")
        self.root = Path(self.tmp.name)
        self.store = GomsStore(self.root)
        self.ctl = ManfredControl(self.root / "goms.sqlite3")
        self.svc = ControlIntentService(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def make_checkpoint_intent(self, attention_id="attn_exec", severity="warning"):
        branch = self.store.create_branch("Execution branch", "test", status="ACTIVE")
        action = {"type": "checkpoint_branch", "target_id": branch,
                  "payload": {"status": "PARKED", "summary": "Approved by intent"}}
        ts = "2026-09-14T09:00:00+00:00"
        with self.store.connect() as con:
            con.execute("""INSERT INTO attention_items
              (id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              VALUES(?,?,?,?,?,'open',?,?,?,?)""",
              (attention_id, "test", severity, "Execution approval", "Run bounded action",
               json.dumps([action]), "test-suite", ts, ts))
        intent_id = self.svc.ensure_for_attention(attention_id)
        return intent_id, branch

    def command(self, key, command_type, intent_id, **payload):
        body = {"resolved_by": "human:test", **payload}
        return self.ctl.execute_command({
            "idempotency_key": key,
            "type": command_type,
            "target_id": intent_id,
            "payload": body,
        })

    def test_auto_after_approval_executes_verifies_and_resolves_once(self):
        intent_id, branch = self.make_checkpoint_intent()
        first = self.command("approve-1", "approve_intent", intent_id)
        replay = self.command("approve-1", "approve_intent", intent_id)
        different_key = self.command("approve-2", "approve_intent", intent_id)
        self.assertTrue(first["ok"])
        self.assertEqual(first, replay)
        self.assertEqual(first["intent_status"], "RESOLVED")
        self.assertEqual(different_key["error"], "intent_not_decidable")
        with self.store.connect() as con:
            self.assertEqual(con.execute("SELECT status FROM branches WHERE id=?", (branch,)).fetchone()[0], "PARKED")
            self.assertEqual(con.execute("SELECT count(*) FROM checkpoints WHERE branch_id=?", (branch,)).fetchone()[0], 1)
        intent = self.svc.get(intent_id)
        self.assertEqual(intent["status"], "RESOLVED")
        execution_events = [e for e in intent["events"] if e["to_status"] == "EXECUTING"]
        self.assertEqual(len(execution_events), 1)
        with self.store.connect() as con:
            attempt = con.execute("SELECT id,status FROM control_intent_execution_attempts WHERE intent_id=?",
                                  (intent_id,)).fetchone()
        self.assertIsNotNone(attempt)
        self.assertEqual(attempt["status"], "SUCCESS")
        self.assertEqual(first["execution_attempt_id"], attempt["id"])

    def test_terminal_intent_outcomes_close_active_alerts(self):
        alerts = AlertService(self.root)
        resolved_id, _ = self.make_checkpoint_intent("attn_alert_resolve")
        resolved_alert = alerts.reconcile_intent(resolved_id)
        result = self.command("approve-alert-resolve", "approve_intent", resolved_id)
        self.assertEqual(result["intent_status"], "RESOLVED")
        self.assertEqual(alerts.get(resolved_alert["id"])["state"], "RESOLVED")

        rejected_id, _ = self.make_checkpoint_intent("attn_alert_reject")
        rejected_alert = alerts.reconcile_intent(rejected_id)
        rejected = self.command("reject-alert", "reject_intent", rejected_id)
        self.assertEqual(rejected["intent_status"], "REJECTED")
        self.assertEqual(alerts.get(rejected_alert["id"])["state"], "RESOLVED")

    def test_concurrent_different_keys_execute_only_once(self):
        intent_id, branch = self.make_checkpoint_intent("attn_concurrent")
        entered = threading.Event()
        release = threading.Event()
        base = ManfredControl(self.root / "goms.sqlite3")

        def slow_checkpoint(target, payload):
            entered.set()
            release.wait(2)
            return base._checkpoint_branch(target, payload)

        ctl = ManfredControl(self.root / "goms.sqlite3",
                             intent_executors={"checkpoint_branch": slow_checkpoint})
        results = {}
        first = threading.Thread(target=lambda: results.setdefault("a", ctl.execute_command({
            "idempotency_key": "concurrent-a", "type": "approve_intent",
            "target_id": intent_id, "payload": {"resolved_by": "human:test"}})))
        first.start()
        self.assertTrue(entered.wait(1))
        results["b"] = ctl.execute_command({
            "idempotency_key": "concurrent-b", "type": "approve_intent",
            "target_id": intent_id, "payload": {"resolved_by": "human:test"}})
        release.set()
        first.join(2)
        self.assertTrue(results["a"]["ok"])
        self.assertIn(results["b"]["error"], {"intent_in_progress", "intent_not_decidable"})
        with self.store.connect() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM checkpoints WHERE branch_id=?",
                                         (branch,)).fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT count(*) FROM control_intent_execution_attempts WHERE intent_id=?",
                                         (intent_id,)).fetchone()[0], 1)

    def test_high_risk_approval_waits_for_confirmation(self):
        intent_id, branch = self.make_checkpoint_intent("attn_high", "critical")
        approved = self.command("approve-high", "approve_intent", intent_id)
        self.assertTrue(approved["ok"])
        self.assertTrue(approved["confirmation_required"])
        self.assertEqual(self.svc.get(intent_id)["status"], "APPROVED")
        self.assertEqual(self.store.list_branches(project="test")[0]["status"], "ACTIVE")

        confirmed = self.command("confirm-high", "confirm_intent", intent_id)
        self.assertTrue(confirmed["ok"])
        self.assertEqual(confirmed["intent_status"], "RESOLVED")
        with self.store.connect() as con:
            self.assertEqual(con.execute("SELECT status FROM branches WHERE id=?", (branch,)).fetchone()[0], "PARKED")
            self.assertEqual(con.execute("SELECT count(*) FROM checkpoints WHERE branch_id=?", (branch,)).fetchone()[0], 1)

    def test_human_only_approval_never_executes(self):
        ts = "2026-09-14T09:00:00+00:00"
        with self.store.connect() as con:
            con.execute("""INSERT INTO attention_items
              (id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              VALUES('attn_manual','test','warning','Manual','Manual only','open','[]','test',?,?)""", (ts, ts))
        intent_id = self.svc.ensure_for_attention("attn_manual")
        approved = self.command("approve-manual", "approve_intent", intent_id)
        self.assertTrue(approved["ok"])
        self.assertTrue(approved["human_only"])
        self.assertEqual(self.svc.get(intent_id)["status"], "APPROVED")
        self.assertFalse(approved["execution_started"])

    def test_rejected_and_deferred_intents_do_not_execute(self):
        rejected_id, rejected_branch = self.make_checkpoint_intent("attn_reject")
        rejected = self.command("reject-1", "reject_intent", rejected_id)
        self.assertTrue(rejected["ok"])
        self.assertEqual(self.svc.get(rejected_id)["status"], "REJECTED")

        deferred_id, deferred_branch = self.make_checkpoint_intent("attn_defer")
        deferred = self.command("defer-1", "defer_intent", deferred_id)
        self.assertTrue(deferred["ok"])
        self.assertEqual(self.svc.get(deferred_id)["status"], "DEFERRED")
        late_approve = self.command("defer-approve", "approve_intent", deferred_id)
        self.assertEqual(late_approve["error"], "intent_not_decidable")
        with self.store.connect() as con:
            self.assertEqual(con.execute("SELECT status FROM branches WHERE id=?", (rejected_branch,)).fetchone()[0], "ACTIVE")
            self.assertEqual(con.execute("SELECT status FROM branches WHERE id=?", (deferred_branch,)).fetchone()[0], "ACTIVE")

    def test_executor_exception_marks_intent_failed_without_side_effect(self):
        intent_id, branch = self.make_checkpoint_intent("attn_boom")

        def explode(_target, _payload):
            raise RuntimeError("boom")

        ctl = ManfredControl(
            self.root / "goms.sqlite3",
            intent_executors={"checkpoint_branch": explode},
        )
        result = ctl.execute_command({
            "idempotency_key": "approve-boom", "type": "approve_intent",
            "target_id": intent_id, "payload": {"resolved_by": "human:test"},
        })
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "intent_execution_failed")
        self.assertEqual(self.svc.get(intent_id)["status"], "FAILED")
        with self.store.connect() as con:
            self.assertEqual(con.execute("SELECT status FROM branches WHERE id=?", (branch,)).fetchone()[0], "ACTIVE")

    def test_stale_executing_intent_becomes_outcome_unknown_without_rerun(self):
        intent_id, branch = self.make_checkpoint_intent("attn_stale")
        with self.store.connect() as con:
            con.execute("UPDATE control_intents SET status='EXECUTING',updated_at=? WHERE id=?",
                        ("2026-09-13T00:00:00+00:00", intent_id))
        result = self.command("approve-stale", "approve_intent", intent_id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "intent_outcome_unknown")
        self.assertEqual(self.svc.get(intent_id)["status"], "OUTCOME_UNKNOWN")
        with self.store.connect() as con:
            self.assertEqual(con.execute("SELECT status FROM branches WHERE id=?", (branch,)).fetchone()[0], "ACTIVE")
            self.assertEqual(con.execute("SELECT count(*) FROM checkpoints WHERE branch_id=?", (branch,)).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
