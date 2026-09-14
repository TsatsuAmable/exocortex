#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from goms_store import GomsStore
from control_intents import ControlIntentService


class ControlIntentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="control-intents-")
        self.root = Path(self.tmp.name)
        self.store = GomsStore(self.root)
        self.svc = ControlIntentService(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def add_attention(self, attention_id="attn_1", severity="warning", actions=None):
        ts = "2026-09-14T09:00:00+00:00"
        with self.store.connect() as con:
            con.execute("""INSERT INTO attention_items
              (id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              VALUES(?,?,?,?,?,'open',?,?,?,?)""",
              (attention_id, "test", severity, "Review this", "Needs judgment",
               json.dumps(actions or []), "test-suite", ts, ts))

    def test_attention_materializes_one_control_intent(self):
        self.add_attention()
        intent_id = self.svc.ensure_for_attention("attn_1")
        self.assertEqual(intent_id, self.svc.ensure_for_attention("attn_1"))
        intent = self.svc.get(intent_id)
        self.assertEqual(intent["status"], "NEEDS_DECISION")
        self.assertEqual(intent["source_ref"], "attn_1")
        self.assertEqual(intent["title"], "Review this")
        self.assertEqual(intent["summary"], "Needs judgment")
        self.assertTrue(intent["decision_required"])

    def test_attention_link_and_id_are_stable(self):
        self.add_attention("attn_stable")
        first = self.svc.ensure_for_attention("attn_stable")
        second = ControlIntentService(self.root).ensure_for_attention("attn_stable")
        self.assertEqual(first, second)
        with self.store.connect() as con:
            row = con.execute(
                "SELECT intent_id FROM attention_control_intents WHERE attention_id=?",
                ("attn_stable",),
            ).fetchone()
        self.assertEqual(row["intent_id"], first)

    def test_missing_attention_is_rejected(self):
        with self.assertRaises(KeyError):
            self.svc.ensure_for_attention("missing")

    def test_illegal_transition_is_rejected_without_state_change(self):
        self.add_attention("attn_transition")
        intent_id = self.svc.ensure_for_attention("attn_transition")
        with self.assertRaises(ValueError):
            self.svc.transition(
                intent_id, "NEEDS_DECISION", "RESOLVED", {"actor": "tester"}
            )
        self.assertEqual(self.svc.get(intent_id)["status"], "NEEDS_DECISION")

    def test_decision_records_actor_payload_and_status(self):
        self.add_attention("attn_decision")
        intent_id = self.svc.ensure_for_attention("attn_decision")
        result = self.svc.decide(
            intent_id, "APPROVE", "human:test", {"reason": "bounded and reversible"}
        )
        self.assertEqual(result["status"], "APPROVED")
        intent = self.svc.get(intent_id)
        decision_events = [e for e in intent["events"] if e["event_type"] == "decision"]
        self.assertEqual(len(decision_events), 1)
        self.assertEqual(decision_events[0]["actor"], "human:test")
        self.assertEqual(decision_events[0]["detail"]["decision"], "APPROVE")
        self.assertEqual(decision_events[0]["detail"]["payload"]["reason"], "bounded and reversible")

    def test_repeated_reconcile_does_not_duplicate_creation_event(self):
        self.add_attention("attn_repeat")
        intent_id = self.svc.ensure_for_attention("attn_repeat")
        self.svc.ensure_for_attention("attn_repeat")
        intent = self.svc.get(intent_id)
        created = [e for e in intent["events"] if e["event_type"] == "created"]
        self.assertEqual(len(created), 1)

    def test_origin_and_execution_conversations_are_distinct(self):
        self.add_attention("attn_chat")
        intent_id = self.svc.ensure_for_attention("attn_chat")
        self.svc.link_conversation(
            intent_id, "origin", "conv-origin", "https://chatgpt.com/c/origin", "human:test", "supplied"
        )
        self.svc.link_conversation(
            intent_id, "execution", "conv-exec", "https://chatgpt.com/c/exec", "human:test", "observed"
        )
        intent = self.svc.get(intent_id)
        self.assertEqual(intent["origin_conversation_id"], "conv-origin")
        self.assertEqual(intent["origin_conversation_url"], "https://chatgpt.com/c/origin")
        self.assertEqual(intent["execution_conversation_id"], "conv-exec")
        self.assertEqual(intent["execution_conversation_url"], "https://chatgpt.com/c/exec")
        locators = intent["provenance"]["conversation_locators"]
        self.assertEqual(locators["origin"]["source"], "supplied")
        self.assertEqual(locators["execution"]["source"], "observed")

    def test_invalid_conversation_role_is_rejected(self):
        self.add_attention("attn_bad_role")
        intent_id = self.svc.ensure_for_attention("attn_bad_role")
        with self.assertRaises(ValueError):
            self.svc.link_conversation(
                intent_id, "primary", "conv", "https://chatgpt.com/c/x", "human:test", "supplied"
            )


    def test_conversation_locator_defaults_unverified_and_rejects_unknown_source(self):
        self.add_attention("attn_locator_source")
        intent_id = self.svc.ensure_for_attention("attn_locator_source")
        self.svc.link_conversation(
            intent_id, "execution", "conv", "https://chatgpt.com/c/x", "human:test"
        )
        intent = self.svc.get(intent_id)
        self.assertEqual(
            intent["provenance"]["conversation_locators"]["execution"]["source"],
            "unverified",
        )
        with self.assertRaises(ValueError):
            self.svc.link_conversation(
                intent_id, "execution", "conv", "https://chatgpt.com/c/x",
                "human:test", "guessed",
            )

    def test_execution_policy_defaults_are_risk_bounded(self):
        action = {"type": "checkpoint_branch", "target_id": "branch_1", "payload": {}}
        self.add_attention("attn_safe", "warning", [action])
        safe = self.svc.get(self.svc.ensure_for_attention("attn_safe"))
        self.assertEqual(safe["execution_policy"], "AUTO_AFTER_APPROVAL")
        self.assertEqual(safe["recommended_action"], action)

        self.add_attention("attn_critical", "critical", [action])
        critical = self.svc.get(self.svc.ensure_for_attention("attn_critical"))
        self.assertEqual(critical["risk_tier"], "high")
        self.assertEqual(critical["execution_policy"], "CONFIRM_HIGH_RISK")

        self.add_attention("attn_unbounded", "warning", ["inspect manually"])
        unbounded = self.svc.get(self.svc.ensure_for_attention("attn_unbounded"))
        self.assertEqual(unbounded["execution_policy"], "HUMAN_ONLY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
