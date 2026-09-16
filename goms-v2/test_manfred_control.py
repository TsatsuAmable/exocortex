#!/usr/bin/env python3
from contextlib import closing
import json
import sqlite3
import threading
import tempfile
import unittest
from pathlib import Path

from goms_store import GomsStore
from alerts import AlertService
from manfred_control import ManfredControl, authorized


class ManfredControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="manfred-control-")
        self.root = Path(self.tmp.name)
        self.store = GomsStore(self.root)
        self.ctl = ManfredControl(self.root / "goms.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_authorization_requires_exact_bearer_token(self):
        self.assertTrue(authorized("Bearer secret", "secret"))
        self.assertFalse(authorized("Bearer wrong", "secret"))
        self.assertFalse(authorized(None, "secret"))
    def test_brief_prioritizes_attention_human_governor_and_blocked_work(self):
        branch = self.store.create_branch(
            "Blocked branch", "test", status="BLOCKED", blocker="needs judgment")
        with closing(sqlite3.connect(self.root / "goms.sqlite3")) as c, c:
            c.execute("""insert into attention_items
              (id,resource_id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              values('attn_1',null,'governor','critical','Need approval','Human decision','open','[]','GovernorController','now','now')""")
            c.execute("""insert into governor_reconciliations
              (resource_id,disposition,reason,attempt_count,last_result,observed_at)
              values('res_human','HUMAN_REQUIRED','authorization required',0,'{}','now')""")
            c.commit()
        brief = self.ctl.build_brief()
        self.assertEqual(brief["attention"][0]["id"], "attn_1")
        self.assertEqual(brief["governor"][0]["disposition"], "HUMAN_REQUIRED")
        self.assertEqual(brief["branches"][0]["id"], branch)

    def test_brief_includes_compact_authority_review_summary(self):
        with closing(sqlite3.connect(self.root / "goms.sqlite3")) as c, c:
            c.execute("""insert into distillation_reconciliation_proposals(
              candidate_id,subject_title,predicate,object_title,status,created_at)
              values('review1','User','prefers','Concise answers','candidate','2026-09-01T00:00:00Z')""")
            c.execute("""insert into distillation_promotion_gate(
              candidate_id,decision,score,reasons,contradiction_count,checked_at)
              values('review1','REVIEW',.85,'["LOW_COMPOSITE_CONFIDENCE"]',0,'2026-09-16T00:00:00Z')""")
        brief=self.ctl.build_brief(reconcile=False)
        self.assertEqual(brief["authority_review"]["total"],1)
        self.assertEqual(brief["authority_review"]["cohorts"][0]["cohort"],"LOW_CONFIDENCE")

    def test_brief_reconciliation_materializes_canonical_alerts(self):
        with closing(sqlite3.connect(self.root / "goms.sqlite3")) as c, c:
            c.execute("""insert into attention_items
              (id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              values('attn_alert','test','warning','Needs attention','x','open','[]','test','now','now')""")
        brief = self.ctl.build_brief()
        intent_id = next(x["intent_id"] for x in brief["attention"] if x["id"] == "attn_alert")
        alerts = AlertService(self.root).list_active()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["intent_id"], intent_id)
        self.assertEqual(alerts[0]["severity"], "ACTION_REQUIRED")

    def test_resolve_attention_is_idempotent_and_recorded(self):
        with closing(sqlite3.connect(self.root / "goms.sqlite3")) as c, c:
            c.execute("""insert into attention_items
              (id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              values('attn_1','governor','warning','Review','x','open','[]','GovernorController','now','now')""")
            c.commit()
        command = {"idempotency_key":"cmd-1","type":"resolve_attention","target_id":"attn_1","payload":{}}
        first = self.ctl.execute_command(command)
        second = self.ctl.execute_command(command)
        self.assertTrue(first["ok"])
        self.assertEqual(first, second)
        with closing(sqlite3.connect(self.root / "goms.sqlite3")) as c, c:
            self.assertEqual(c.execute("select status from attention_items where id='attn_1'").fetchone()[0], "resolved")
            self.assertEqual(c.execute("select count(*) from manfred_commands where idempotency_key='cmd-1'").fetchone()[0], 1)
    def test_checkpoint_branch_uses_goms_transition_and_records_provenance(self):
        branch = self.store.create_branch("Active branch", "test", status="ACTIVE")
        command = {
            "idempotency_key":"cmd-2","type":"checkpoint_branch","target_id":branch,
            "payload":{"status":"PARKED","summary":"Human paused work","next_action":"await review"}
        }
        result = self.ctl.execute_command(command)
        self.assertTrue(result["ok"])
        with closing(sqlite3.connect(self.root / "goms.sqlite3")) as c, c:
            row = c.execute("select status,last_result,next_action from branches where id=?",(branch,)).fetchone()
            self.assertEqual(row, ("PARKED","Human paused work","await review"))
            status = c.execute("select status from manfred_commands where idempotency_key='cmd-2'").fetchone()[0]
            self.assertEqual(status, "SUCCESS")
        events = self.store.recent_events(5)
        self.assertTrue(any(e.get("op")=="checkpoint" and e.get("actor")=="manfred-control" for e in events))

    def test_unknown_command_is_rejected_and_recorded(self):
        result = self.ctl.execute_command({
            "idempotency_key":"cmd-3","type":"shell","target_id":"x","payload":{"cmd":"rm -rf /"}
        })
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unsupported_command")
        with closing(sqlite3.connect(self.root / "goms.sqlite3")) as c, c:
            self.assertEqual(c.execute("select status from manfred_commands where idempotency_key='cmd-3'").fetchone()[0], "REJECTED")

    def test_pending_duplicate_reports_in_progress_then_replays_final(self):
        with closing(sqlite3.connect(self.root / "goms.sqlite3")) as c, c:
            c.execute("""insert into attention_items
              (id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              values('attn_slow','test','warning','Slow','x','open','[]','test','now','now')""")
        entered = threading.Event()
        release = threading.Event()
        class SlowControl(ManfredControl):
            def _resolve_attention(self, attention_id, payload=None):
                entered.set(); release.wait(2)
                return super()._resolve_attention(attention_id, payload)
        ctl = SlowControl(self.root / "goms.sqlite3")
        command = {"idempotency_key":"cmd-slow","type":"resolve_attention",
                   "target_id":"attn_slow","payload":{}}
        holder = {}
        t = threading.Thread(target=lambda: holder.setdefault("result", ctl.execute_command(command)))
        t.start(); self.assertTrue(entered.wait(1))
        second = ctl.execute_command(command)
        self.assertEqual(second.get("error"), "command_in_progress")
        release.set(); t.join(2)
        self.assertTrue(holder["result"]["ok"])
        self.assertEqual(ctl.execute_command(command), holder["result"])

    def test_idempotency_key_reuse_for_different_command_is_rejected(self):
        with closing(sqlite3.connect(self.root / "goms.sqlite3")) as c, c:
            c.execute("""insert into attention_items
              (id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              values('attn_reuse','test','warning','Reuse','x','open','[]','test','now','now')""")
        first = {"idempotency_key":"same-key","type":"resolve_attention",
                 "target_id":"attn_reuse","payload":{}}
        self.assertTrue(self.ctl.execute_command(first)["ok"])
        branch = self.store.create_branch("Reuse branch", "test", status="ACTIVE")
        second = {"idempotency_key":"same-key","type":"checkpoint_branch",
                  "target_id":branch,"payload":{"status":"PARKED","summary":"no"}}
        result = self.ctl.execute_command(second)
        self.assertEqual(result.get("error"), "idempotency_key_reused")
        self.assertEqual(self.store.list_branches(project="test")[0]["status"], "ACTIVE")

    def test_critical_governor_attention_requires_human_attestation(self):
        with closing(sqlite3.connect(self.root / "goms.sqlite3")) as c, c:
            c.execute("""insert into attention_items
              (id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              values('attn_critical','governor','critical','Approval','x','open','[]','GovernorController','now','now')""")
        command = {"idempotency_key":"critical-1","type":"resolve_attention",
                   "target_id":"attn_critical","payload":{}}
        result = self.ctl.execute_command(command)
        self.assertEqual(result.get("error"), "human_attestation_required")


    def test_stale_pending_command_becomes_outcome_unknown(self):
        old = "2026-09-13T00:00:00+00:00"
        payload = {}
        with closing(sqlite3.connect(self.root / "goms.sqlite3")) as c, c:
            c.execute("""insert into manfred_commands(
              idempotency_key,command_type,target_id,payload,status,result,created_at,updated_at)
              values('stale-key','resolve_attention','attn_x',?,'PENDING','{}',?,?)""",
              (json.dumps(payload), old, old))
        result = self.ctl.execute_command({"idempotency_key":"stale-key","type":"resolve_attention",
                                           "target_id":"attn_x","payload":payload})
        self.assertEqual(result.get("error"), "command_outcome_unknown")
        with closing(sqlite3.connect(self.root / "goms.sqlite3")) as c:
            self.assertEqual(c.execute("select status from manfred_commands where idempotency_key='stale-key'").fetchone()[0], "UNKNOWN")



if __name__ == "__main__":
    unittest.main(verbosity=2)
