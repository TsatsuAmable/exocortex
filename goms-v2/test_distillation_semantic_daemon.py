#!/usr/bin/env python3
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

import distillation_reconcile_policy as reconcile_policy
import distillation_semantic_daemon as semantic_daemon


class ReconcilePolicyTests(unittest.TestCase):
    def test_selects_new_validated_durable_candidates_across_run_ids(self):
        with closing(sqlite3.connect(':memory:')) as c:
            c.row_factory=sqlite3.Row
            c.executescript('''
              create table distillation_candidates(id text primary key,run_id text,kind text,subject text,predicate text,object text,literal text,confidence real,evidence_ids text,status text,created_at text);
              create table distillation_validations(candidate_id text primary key,verdict text,validated_kind text,durability text,confidence real,rationale text);
              create table distillation_reconciliation_proposals(candidate_id text primary key,status text);
            ''')
            rows=[
              ('stream-ok','streaming-worker','decision',.9,'accept','project',.95,None),
              ('legacy-ok','old-run','objective',.9,'reclassify','enduring',.91,None),
              ('already','streaming-worker','task',.9,'accept','project',.94,'candidate'),
              ('session','streaming-worker','task',.9,'accept','session',.95,None),
              ('low','streaming-worker','task',.7,'accept','project',.95,None),
            ]
            for cid,run,kind,ec,verdict,dur,vc,pstatus in rows:
                c.execute("insert into distillation_candidates values(?,?,?,?,?,?,?,?,?,'candidate','2026-09-16T00:00:00Z')",(cid,run,kind,cid,'p',None,None,ec,'[]'))
                c.execute("insert into distillation_validations values(?,?,?,?,?,?)",(cid,verdict,kind,dur,vc,'r'))
                if pstatus: c.execute("insert into distillation_reconciliation_proposals values(?,?)",(cid,pstatus))
            selected=reconcile_policy.select_eligible_candidates(c,limit=20)
        self.assertEqual({x['id'] for x in selected},{'stream-ok','legacy-ok'})


class SemanticDaemonTests(unittest.TestCase):
    def test_stage_plan_prioritizes_oldest_upstream_gap(self):
        self.assertEqual(semantic_daemon.choose_stage({'unvalidated':3,'unreconciled':2,'gate_missing':2,'shape_missing':1,'promotable':1}),'validate')
        self.assertEqual(semantic_daemon.choose_stage({'unvalidated':0,'unreconciled':2,'gate_missing':2,'shape_missing':1,'promotable':1}),'reconcile')
        self.assertEqual(semantic_daemon.choose_stage({'unvalidated':0,'unreconciled':0,'gate_missing':2,'shape_missing':1,'promotable':1}),'gate')
        self.assertEqual(semantic_daemon.choose_stage({'unvalidated':0,'unreconciled':0,'gate_missing':0,'shape_missing':1,'promotable':1}),'shape')
        self.assertEqual(semantic_daemon.choose_stage({'unvalidated':0,'unreconciled':0,'gate_missing':0,'shape_missing':0,'promotable':1}),'promote')
        self.assertIsNone(semantic_daemon.choose_stage({'unvalidated':0,'unreconciled':0,'gate_missing':0,'shape_missing':0,'promotable':0}))


if __name__=='__main__': unittest.main(verbosity=2)
