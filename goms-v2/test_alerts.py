#!/usr/bin/env python3
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from goms_store import GomsStore
from control_intents import ControlIntentService
from alerts import AlertService


class FakeClock:
    def __init__(self):
        self.current = datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.current

    def advance(self, seconds):
        self.current += timedelta(seconds=seconds)


class AlertServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alerts-")
        self.root = Path(self.tmp.name)
        self.store = GomsStore(self.root)
        self.intents = ControlIntentService(self.root)
        self.clock = FakeClock()
        self.alerts = AlertService(self.root, clock=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def add_attention(self, attention_id, severity="warning", category="test"):
        ts = self.clock().isoformat()
        with self.store.connect() as con:
            con.execute("""INSERT INTO attention_items
              (id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              VALUES(?,?,?,?,?,'open','[]',?,?,?)""",
              (attention_id, category, severity, "Review this", "Needs judgment",
               "test-suite", ts, ts))
        return self.intents.ensure_for_attention(attention_id)

    def set_alert_policy(self, intent_id, **policy):
        intent = self.intents.get(intent_id)
        provenance = dict(intent.get("provenance") or {})
        provenance["alert_policy"] = policy
        with self.store.connect() as con:
            con.execute(
                "UPDATE control_intents SET provenance=?,updated_at=? WHERE id=?",
                (json.dumps(provenance), self.clock().isoformat(), intent_id),
            )

    def alert_rows(self, dedupe_key=None):
        with self.store.connect() as con:
            if dedupe_key:
                return [dict(r) for r in con.execute(
                    "SELECT * FROM alerts WHERE dedupe_key=? ORDER BY raised_at,id",
                    (dedupe_key,),
                ).fetchall()]
            return [dict(r) for r in con.execute("SELECT * FROM alerts ORDER BY raised_at,id").fetchall()]

    def test_reconcile_creates_one_active_action_required_alert_per_dedupe_key(self):
        intent_id = self.add_attention("attn_one")
        first = self.alerts.reconcile_intent(intent_id)
        second = self.alerts.reconcile_intent(intent_id)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["severity"], "ACTION_REQUIRED")
        self.assertEqual(first["state"], "RAISED")
        self.assertEqual(first["dedupe_key"], f"intent:{intent_id}")
        self.assertEqual(len(self.alert_rows(first["dedupe_key"])), 1)

    def test_explicit_urgent_and_critical_boundary_mapping(self):
        urgent_id = self.add_attention("attn_urgent")
        self.set_alert_policy(urgent_id, severity="URGENT")
        urgent = self.alerts.reconcile_intent(urgent_id)
        self.assertEqual(urgent["severity"], "URGENT")

        critical_id = self.add_attention("attn_critical", severity="critical", category="security")
        critical = self.alerts.reconcile_intent(critical_id)
        self.assertEqual(critical["severity"], "CRITICAL")

    def test_info_policy_remains_canonical_without_becoming_action_required(self):
        intent_id = self.add_attention("attn_info")
        self.set_alert_policy(intent_id, severity="INFO")
        alert = self.alerts.reconcile_intent(intent_id)
        self.assertEqual(alert["severity"], "INFO")

    def test_machine_owned_execution_defaults_to_info(self):
        intent_id = self.add_attention("attn_executing")
        with self.store.connect() as con:
            con.execute("UPDATE control_intents SET status='EXECUTING' WHERE id=?", (intent_id,))
        alert = self.alerts.reconcile_intent(intent_id)
        self.assertEqual(alert["severity"], "INFO")
    def test_expiry_resolves_without_realerting_unchanged_intent(self):
        intent_id = self.add_attention("attn_expire")
        self.set_alert_policy(intent_id, ttl_seconds=60)
        alert = self.alerts.reconcile_intent(intent_id)
        self.assertIsNotNone(alert["expires_at"])
        self.clock.advance(61)
        self.assertIsNone(self.alerts.reconcile_intent(intent_id))
        rows = self.alert_rows(f"intent:{intent_id}")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "RESOLVED")
        self.assertEqual(rows[0]["resolution_reason"], "expired")
        self.assertIsNone(self.alerts.reconcile_intent(intent_id))
        self.assertEqual(len(self.alert_rows(f"intent:{intent_id}")), 1)

    def test_acknowledgement_does_not_resolve_underlying_intent(self):
        intent_id = self.add_attention("attn_ack")
        alert = self.alerts.reconcile_intent(intent_id)
        self.alerts.record_delivery(alert["id"], "device:manfred")
        self.alerts.record_seen(alert["id"], "device:manfred")
        acknowledged = self.alerts.acknowledge(alert["id"], "human:test")
        self.assertEqual(acknowledged["state"], "ACKNOWLEDGED")
        self.assertEqual(self.intents.get(intent_id)["status"], "NEEDS_DECISION")
    def test_resolve_for_intent_closes_active_alert(self):
        intent_id = self.add_attention("attn_resolve")
        alert = self.alerts.reconcile_intent(intent_id)
        resolved = self.alerts.resolve_for_intent(intent_id, actor="system:test")
        self.assertEqual(resolved, 1)
        self.assertEqual(self.alerts.get(alert["id"])["state"], "RESOLVED")
        self.assertIsNotNone(self.alerts.get(alert["id"])["resolved_at"])

    def test_escalation_is_rate_limited(self):
        intent_id = self.add_attention("attn_escalate")
        self.set_alert_policy(intent_id, escalation_seconds=300)
        alert = self.alerts.reconcile_intent(intent_id)
        self.assertEqual(alert["escalation_count"], 0)
        self.clock.advance(100)
        early = self.alerts.reconcile_intent(intent_id)
        self.assertEqual(early["id"], alert["id"])
        self.assertEqual(early["escalation_count"], 0)
        self.clock.advance(201)
        due = self.alerts.reconcile_intent(intent_id)
        self.assertEqual(due["id"], alert["id"])
        self.assertEqual(due["escalation_count"], 1)
        self.assertIsNotNone(due["last_escalated_at"])

    def test_resolved_attention_source_closes_alert_without_rewriting_intent(self):
        intent_id = self.add_attention("attn_source_cleared")
        alert = self.alerts.reconcile_intent(intent_id)
        with self.store.connect() as con:
            con.execute("UPDATE attention_items SET status='resolved',updated_at=? WHERE id=?",
                        (self.clock().isoformat(), "attn_source_cleared"))
        self.assertIsNone(self.alerts.reconcile_intent(intent_id))
        closed = self.alerts.get(alert["id"])
        self.assertEqual(closed["state"], "RESOLVED")
        self.assertEqual(closed["resolution_reason"], "source_cleared")
        self.assertEqual(self.intents.get(intent_id)["status"], "NEEDS_DECISION")

    def test_lifecycle_state_controls_default_severity_but_explicit_urgent_wins(self):
        intent_id = self.add_attention("attn_lifecycle_severity")
        first = self.alerts.reconcile_intent(intent_id)
        self.assertEqual(first["severity"], "ACTION_REQUIRED")
        with self.store.connect() as con:
            con.execute("UPDATE control_intents SET status='APPROVED',updated_at=? WHERE id=?",
                        (self.clock().isoformat(), intent_id))
        approved = self.alerts.reconcile_intent(intent_id)
        self.assertEqual(approved["severity"], "INFO")
        self.set_alert_policy(intent_id, severity="URGENT")
        explicit = self.alerts.reconcile_intent(intent_id)
        self.assertEqual(explicit["severity"], "URGENT")
