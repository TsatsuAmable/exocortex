#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from goms_store import GomsStore
from control_intents import ControlIntentService
from alerts import AlertService
from manfred_control import ManfredControl
from manfred_projection import build_projection


FULL_CAPS = {
    "ui_schema_versions": ["1.0"],
    "components": ["summary", "evidence", "decision", "link", "generic_object"],
    "actions": ["APPROVE", "REJECT", "DEFER", "CONFIRM", "ASK_CHATGPT", "OPEN_CHATGPT", "OPEN_ORIGIN"],
}


class ManfredProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="manfred-projection-")
        self.root = Path(self.tmp.name)
        self.store = GomsStore(self.root)
        self.svc = ControlIntentService(self.root)
        self.alerts = AlertService(self.root)
        self.control = ManfredControl(self.root / "goms.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def make_intent(self, attention_id="attn_projection", severity="warning"):
        branch = self.store.create_branch("Projection branch", "test", status="ACTIVE")
        action = {"type": "checkpoint_branch", "target_id": branch,
                  "payload": {"status": "PARKED", "summary": "Projection approved"}}
        ts = "2026-09-14T15:00:00+00:00"
        with self.store.connect() as con:
            con.execute("""INSERT INTO attention_items
              (id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              VALUES(?,?,?,?,?,'open',?,?,?,?)""",
              (attention_id, "test", severity, "Projection decision", "Choose safely",
               json.dumps([action]), "test-suite", ts, ts))
        intent_id = self.svc.ensure_for_attention(attention_id)
        return intent_id, branch

    def test_schema_1_projection_contains_decision_sections_and_actions(self):
        intent_id, _ = self.make_intent()
        projection = build_projection(self.control, FULL_CAPS)
        self.assertEqual(projection["schema_version"], "1.0")
        intent = next(x for x in projection["intents"] if x["id"] == intent_id)
        self.assertEqual(intent["ui"]["template"], "intent_detail")
        self.assertEqual([x["type"] for x in intent["ui"]["sections"][:2]], ["summary", "decision"])
        self.assertEqual([x["id"] for x in intent["ui"]["actions"]], ["APPROVE", "REJECT", "DEFER", "ASK_CHATGPT"])

    def test_conversation_locator_and_provenance_survive_projection(self):
        intent_id, _ = self.make_intent("attn_link")
        self.svc.link_conversation(
            intent_id, "execution", "conv-real", "https://chatgpt.com/c/real-locator",
            "human:test", "supplied")
        projection = build_projection(self.control, FULL_CAPS)
        intent = next(x for x in projection["intents"] if x["id"] == intent_id)
        link = next(x for x in intent["ui"]["sections"] if x["type"] == "link")
        self.assertEqual(link["data"]["execution"]["url"], "https://chatgpt.com/c/real-locator")
        self.assertEqual(link["data"]["execution"]["source"], "supplied")
        self.assertIn("OPEN_CHATGPT", [x["id"] for x in intent["ui"]["actions"]])

    def test_unsupported_component_falls_back_and_records_mismatch(self):
        intent_id, _ = self.make_intent("attn_evidence")
        with self.store.connect() as con:
            con.execute("UPDATE control_intents SET evidence_refs=? WHERE id=?",
                        (json.dumps([{"id": "ev_1", "claim": "observed"}]), intent_id))
        caps = dict(FULL_CAPS)
        caps["components"] = ["summary", "decision", "generic_object"]
        projection = build_projection(self.control, caps)
        intent = next(x for x in projection["intents"] if x["id"] == intent_id)
        fallback = next(x for x in intent["ui"]["sections"] if x.get("original_type") == "evidence")
        self.assertEqual(fallback["type"], "generic_object")
        mismatch = next(x for x in projection["capability_mismatches"] if x["intent_id"] == intent_id)
        self.assertEqual(mismatch["component"], "evidence")
        self.assertEqual(mismatch["fallback"], "generic_object")

    def test_actions_are_filtered_by_client_capabilities(self):
        intent_id, _ = self.make_intent("attn_filtered")
        caps = dict(FULL_CAPS)
        caps["actions"] = ["DEFER", "ASK_CHATGPT"]
        projection = build_projection(self.control, caps)
        intent = next(x for x in projection["intents"] if x["id"] == intent_id)
        self.assertEqual([x["id"] for x in intent["ui"]["actions"]], ["DEFER", "ASK_CHATGPT"])

    def test_brief_exposes_evidence_and_provenance_needed_by_projection(self):
        intent_id, _ = self.make_intent("attn_context")
        with self.store.connect() as con:
            con.execute("UPDATE control_intents SET evidence_refs=? WHERE id=?",
                        (json.dumps(["ev_alpha"]), intent_id))
        self.svc.link_conversation(
            intent_id, "origin", "conv-origin", "https://chatgpt.com/c/origin-real",
            "human:test", "observed")
        brief = self.control.build_brief()
        intent = next(x for x in brief["intents"] if x["id"] == intent_id)
        self.assertEqual(intent["evidence_refs"], ["ev_alpha"])
        self.assertEqual(intent["provenance"]["conversation_locators"]["origin"]["source"], "observed")

    def test_projection_includes_active_alerts_in_severity_order(self):
        normal_id, _ = self.make_intent("attn_alert_normal")
        critical_id, _ = self.make_intent("attn_alert_critical", severity="critical")
        with self.store.connect() as con:
            row = con.execute("SELECT provenance FROM control_intents WHERE id=?", (critical_id,)).fetchone()
            provenance = json.loads(row["provenance"] or "{}")
            provenance["category"] = "security"
            con.execute("UPDATE control_intents SET risk_tier='high',provenance=? WHERE id=?",
                        (json.dumps(provenance), critical_id))
        self.alerts.reconcile_intent(normal_id)
        self.alerts.reconcile_intent(critical_id)
        projection = build_projection(self.control, FULL_CAPS)
        self.assertEqual([x["severity"] for x in projection["alerts"][:2]],
                         ["CRITICAL", "ACTION_REQUIRED"])
        self.assertEqual({x["intent_id"] for x in projection["alerts"]},
                         {normal_id, critical_id})


if __name__ == "__main__":
    unittest.main(verbosity=2)
