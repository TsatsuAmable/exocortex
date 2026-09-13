#!/usr/bin/env python3
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from governor_controller import GovernorController

ROOT = Path(__file__).resolve().parent


class GovernorControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="governor-test-")
        self.db = Path(self.tmp.name) / "goms.sqlite3"
        with sqlite3.connect(self.db) as c:
            c.executescript((ROOT / "schema.sql").read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def add_resource(self, *, name="replica", desired="healthy", observed="degraded",
                     failure="human_authorization_required", repair="drain_replication",
                     authority="system"):
        spec = {"desired_state": desired, "repair": repair}
        status = {"observed_state": observed, "failure_class": failure}
        with sqlite3.connect(self.db) as c:
            c.execute("""insert into resources(id,kind,name,spec,status,generation,observed_generation,
              controller,authority,metadata,created_at,updated_at)
              values('res_test','ReplicationQueue',?,?,?,?,1,'test',?,'{}','now','now')""",
              (name, json.dumps(spec), json.dumps(status), 1, authority))
            c.commit()

    def test_human_boundary_is_persisted_and_deduplicated_as_attention(self):
        self.add_resource()
        ctl = GovernorController(self.db)
        first = ctl.reconcile_all()
        second = ctl.reconcile_all()
        self.assertEqual(first[0]["disposition"], "HUMAN_REQUIRED")
        self.assertEqual(second[0]["disposition"], "HUMAN_REQUIRED")
        with sqlite3.connect(self.db) as c:
            row = c.execute("select disposition,attempt_count from governor_reconciliations where resource_id='res_test'").fetchone()
            self.assertEqual(row, ("HUMAN_REQUIRED", 0))
            self.assertEqual(c.execute("select count(*) from governor_actions").fetchone()[0], 0)
            attention = c.execute("select count(*) from attention_items where source='GovernorController' and status='open'").fetchone()[0]
            self.assertEqual(attention, 1)

    def test_safe_auto_repair_records_action_and_attempt(self):
        self.add_resource(name="routine", desired="loaded", observed="missing",
                          failure=None, repair="launchd_kickstart")
        calls = []
        def executor(action, resource):
            calls.append((action, resource["id"]))
            return {"ok": True, "detail": "kickstarted"}
        ctl = GovernorController(self.db, executor=executor)
        result = ctl.reconcile_all()[0]
        self.assertEqual(result["disposition"], "AUTO_REPAIR")
        self.assertEqual(calls, [("launchd_kickstart", "res_test")])
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("select attempt_count from governor_reconciliations where resource_id='res_test'").fetchone()[0], 1)
            self.assertEqual(c.execute("select status from governor_actions").fetchone()[0], "SUCCESS")
