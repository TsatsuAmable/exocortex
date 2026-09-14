#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from goms_store import GomsStore
from manfred_control import ManfredControl
from control_intent_reconciler import reconcile_attention_intents


class ControlIntentReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="intent-reconcile-")
        self.root = Path(self.tmp.name)
        self.store = GomsStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def add_attention(self, attention_id: str, status: str = "open"):
        ts = "2026-09-14T09:00:00+00:00"
        with self.store.connect() as con:
            con.execute("""INSERT INTO attention_items
              (id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?)""",
              (attention_id, "test", "warning", f"Attention {attention_id}", "Needs judgment",
               status, json.dumps([]), "test-suite", ts, ts))

    def test_open_attention_materializes_once(self):
        self.add_attention("attn_open")
        first = reconcile_attention_intents(self.root)
        second = reconcile_attention_intents(self.root)
        self.assertEqual(first, {"created": 1, "existing": 0, "closed": 0})
        self.assertEqual(second, {"created": 0, "existing": 1, "closed": 0})
        with self.store.connect() as con:
            rows = con.execute("SELECT attention_id,intent_id FROM attention_control_intents").fetchall()
            intents = con.execute("SELECT id,status FROM control_intents").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0]["status"], "NEEDS_DECISION")

    def test_resolved_attention_does_not_create_a_second_intent(self):
        self.add_attention("attn_resolve")
        reconcile_attention_intents(self.root)
        with self.store.connect() as con:
            con.execute("UPDATE attention_items SET status='resolved' WHERE id='attn_resolve'")
        result = reconcile_attention_intents(self.root)
        self.assertEqual(result, {"created": 0, "existing": 0, "closed": 1})
        with self.store.connect() as con:
            count = con.execute("SELECT count(*) FROM control_intents").fetchone()[0]
        self.assertEqual(count, 1)

    def test_build_brief_reconciles_before_projection(self):
        self.add_attention("attn_brief")
        brief = ManfredControl(self.root / "goms.sqlite3").build_brief()
        self.assertEqual(len(brief["attention"]), 1)
        self.assertTrue(brief["attention"][0]["intent_id"].startswith("intent_attn_"))
        self.assertEqual(len(brief["intents"]), 1)
        self.assertEqual(brief["intents"][0]["id"], brief["attention"][0]["intent_id"])
        self.assertEqual(brief["intents"][0]["status"], "NEEDS_DECISION")

    def test_resolved_unlinked_attention_is_ignored(self):
        self.add_attention("attn_old", status="resolved")
        result = reconcile_attention_intents(self.root)
        self.assertEqual(result, {"created": 0, "existing": 0, "closed": 0})
        with self.store.connect() as con:
            count = con.execute("SELECT count(*) FROM control_intents").fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
