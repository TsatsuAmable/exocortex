#!/usr/bin/env python3
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

import distillation_reconcile_policy as reconcile_policy
import distillation_graphshape_policy as graphshape_policy
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


class GraphShapePolicyTests(unittest.TestCase):
    def test_selects_only_missing_auto_ready_reviews_with_limit(self):
        with closing(sqlite3.connect(':memory:')) as c:
            c.row_factory=sqlite3.Row
            c.executescript('''
              create table distillation_reconciliation_proposals(candidate_id text primary key,status text,canonical_kind text,subject_mode text,subject_id text,subject_type text,subject_title text,predicate text,object_mode text,object_id text,object_type text,object_title text,literal text);
              create table distillation_promotion_gate(candidate_id text primary key,decision text,score real,reasons text);
              create table distillation_graphshape_reviews(candidate_id text primary key,verdict text);
            ''')
            for i in range(5):
                cid=f'c{i}'
                c.execute("insert into distillation_reconciliation_proposals values(?,?,?,?,?,?,?,?,?,?,?,?,?)",(cid,'candidate','decision','new',None,'idea',cid,'p','literal',None,None,None,'x'))
                c.execute("insert into distillation_promotion_gate values(?,?,?,?)",(cid,'AUTO_READY',.9,'[]'))
            c.execute("insert into distillation_graphshape_reviews values('c0','ACCEPT')")
            rows=graphshape_policy.select_pending_shape_reviews(c,limit=2)
        self.assertEqual([r['candidate_id'] for r in rows],['c1','c2'])


class SemanticDaemonTests(unittest.TestCase):
    def test_stage_plan_rotates_fairly_across_active_backlogs(self):
        counts={'unvalidated':3,'unreconciled':2,'gate_missing':2,'review_actionable':4,'shape_missing':1,'promotable':1,'surface_dirty':1}
        self.assertEqual([semantic_daemon.choose_stage(counts,cursor=i) for i in range(6)],
                         ['validate','reconcile','gate','adjudicate','shape','promote'])
        self.assertEqual(semantic_daemon.choose_stage({'unvalidated':3,'unreconciled':2,'gate_missing':0,'review_actionable':0,'shape_missing':0,'promotable':0,'surface_dirty':0},cursor=2),'validate')
        self.assertEqual(semantic_daemon.choose_stage({'unvalidated':3,'unreconciled':2,'gate_missing':0,'review_actionable':0,'shape_missing':0,'promotable':0,'surface_dirty':0},cursor=1),'reconcile')
        self.assertIsNone(semantic_daemon.choose_stage({'unvalidated':0,'unreconciled':0,'gate_missing':0,'review_actionable':0,'shape_missing':0,'promotable':0,'surface_dirty':0},cursor=6))


    def test_actionable_review_gets_fair_turn(self):
        counts={"unvalidated":0,"unreconciled":0,"gate_missing":0,"review_actionable":9,"shape_missing":3,"promotable":2,"surface_dirty":0}
        self.assertEqual(semantic_daemon.choose_stage(counts,cursor=3),"adjudicate")

    def test_surface_refresh_is_independent_of_actionable_adjudication(self):
        counts={"unvalidated":0,"unreconciled":0,"gate_missing":0,"review_actionable":0,
                "shape_missing":0,"promotable":0,"surface_dirty":1}
        self.assertEqual(semantic_daemon.choose_stage(counts,cursor=0),"surface")
        self.assertEqual(semantic_daemon.SCRIPTS['surface'],'distillation_review_surface.py')


    def test_dirty_review_surface_gets_independent_turn(self):
        counts={"unvalidated":0,"unreconciled":0,"gate_missing":0,"review_actionable":0,"shape_missing":0,"promotable":0,"surface_dirty":1}
        self.assertEqual(semantic_daemon.choose_stage(counts,cursor=0),"surface")

    def test_stage_plan_can_pause_promotion_without_pausing_upstream(self):
        counts={"unvalidated":0,"unreconciled":0,"gate_missing":0,"review_actionable":0,"shape_missing":0,"promotable":7,"surface_dirty":0}
        self.assertIsNone(semantic_daemon.choose_stage(counts,cursor=6,promotion_enabled=False))
        counts["shape_missing"]=3
        self.assertEqual(semantic_daemon.choose_stage(counts,cursor=6,promotion_enabled=False),"shape")

if __name__=='__main__': unittest.main(verbosity=2)
