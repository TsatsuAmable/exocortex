#!/usr/bin/env python3
from contextlib import closing
import plistlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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
              create table distillation_promotion_gate(candidate_id text primary key,decision text,score real,reasons text,gate_fingerprint text);
              create table distillation_graphshape_reviews(candidate_id text primary key,verdict text,gate_fingerprint text);
            ''')
            for i in range(5):
                cid=f'c{i}'
                c.execute("insert into distillation_reconciliation_proposals values(?,?,?,?,?,?,?,?,?,?,?,?,?)",(cid,'candidate','decision','new',None,'idea',cid,'p','literal',None,None,None,'x'))
                c.execute("insert into distillation_promotion_gate values(?,?,?,?,?)",(cid,'AUTO_READY',.9,'[]','fp-'+cid))
            c.execute("insert into distillation_graphshape_reviews values('c0','ACCEPT','fp-c0')")
            rows=graphshape_policy.select_pending_shape_reviews(c,limit=2)
        self.assertEqual([r['candidate_id'] for r in rows],['c1','c2'])

    def test_shape_review_must_match_current_gate_fingerprint(self):
        with closing(sqlite3.connect(':memory:')) as c:
            c.row_factory=sqlite3.Row
            c.executescript('''
              create table distillation_reconciliation_proposals(candidate_id text primary key,status text,canonical_kind text,subject_mode text,subject_id text,subject_type text,subject_title text,predicate text,object_mode text,object_id text,object_type text,object_title text,literal text);
              create table distillation_promotion_gate(candidate_id text primary key,decision text,score real,reasons text,gate_fingerprint text);
              create table distillation_graphshape_reviews(candidate_id text primary key,verdict text,gate_fingerprint text);
            ''')
            c.execute("insert into distillation_reconciliation_proposals values('c','candidate','decision','new',null,'idea','x','p','literal',null,null,null,'x')")
            c.execute("insert into distillation_promotion_gate values('c','AUTO_READY',.9,'[]','gate-new')")
            c.execute("insert into distillation_graphshape_reviews values('c','ACCEPT','gate-old')")
            rows=graphshape_policy.select_pending_shape_reviews(c,limit=2)
            self.assertEqual([r['candidate_id'] for r in rows],['c'])

    def test_shape_consensus_requires_two_accepts(self):
        verdict,rationale=graphshape_policy.aggregate_shape_verdicts([
            {'model':'reviewer-a','verdict':'ACCEPT'},
            {'model':'reviewer-b','verdict':'ACCEPT'},
        ])
        self.assertEqual(verdict,'ACCEPT')
        self.assertIn('reviewer-a',rationale)

    def test_shape_disagreement_is_non_authorizing(self):
        verdict,rationale=graphshape_policy.aggregate_shape_verdicts([
            {'model':'reviewer-a','verdict':'REJECT'},
            {'model':'reviewer-b','verdict':'ACCEPT'},
        ])
        self.assertNotEqual(verdict,'ACCEPT')
        self.assertIn('DISAGREEMENT',rationale)

    def test_single_successful_shape_reviewer_is_non_authorizing(self):
        verdict,rationale=graphshape_policy.aggregate_shape_verdicts([
            {'model':'reviewer-a','verdict':'ACCEPT'},
        ])
        self.assertNotEqual(verdict,'ACCEPT')
        self.assertIn('INSUFFICIENT',rationale)

    def test_duplicate_model_does_not_count_as_independent_consensus(self):
        verdict,rationale=graphshape_policy.aggregate_shape_verdicts([
            {'model':'reviewer-a','verdict':'ACCEPT'},
            {'model':'reviewer-a','verdict':'ACCEPT'},
        ])
        self.assertNotEqual(verdict,'ACCEPT')
        self.assertIn('INSUFFICIENT',rationale)

    def test_committee_complete_waits_for_two_distinct_reviewers_per_candidate(self):
        reviews={'c1':[{'model':'a','verdict':'ACCEPT'}], 'c2':[{'model':'a','verdict':'REWRITE'}]}
        self.assertFalse(graphshape_policy.committee_complete(reviews,['c1','c2']))
        reviews['c1'].append({'model':'b','verdict':'ACCEPT'})
        reviews['c2'].append({'model':'b','verdict':'REWRITE'})
        self.assertTrue(graphshape_policy.committee_complete(reviews,['c1','c2']))


class SemanticDaemonTests(unittest.TestCase):
    def test_stage_plan_rotates_fairly_across_active_backlogs(self):
        counts={'unvalidated':3,'unreconciled':2,'gate_missing':2,'review_actionable':4,
                'evidence_review_actionable':2,'shape_missing':1,'rewrite_actionable':1,
                'promotable':1,'surface_dirty':1}
        self.assertEqual([semantic_daemon.choose_stage(counts,cursor=i) for i in range(8)],
                         ['validate','reconcile','gate','adjudicate','evidence','shape','rewrite','promote'])
        self.assertEqual(semantic_daemon.choose_stage({'unvalidated':3,'unreconciled':2,'gate_missing':0,'review_actionable':0,'shape_missing':0,'promotable':0,'surface_dirty':0},cursor=2),'validate')
        self.assertEqual(semantic_daemon.choose_stage({'unvalidated':3,'unreconciled':2,'gate_missing':0,'review_actionable':0,'shape_missing':0,'promotable':0,'surface_dirty':0},cursor=1),'reconcile')
        self.assertIsNone(semantic_daemon.choose_stage({'unvalidated':0,'unreconciled':0,'gate_missing':0,'review_actionable':0,'shape_missing':0,'promotable':0,'surface_dirty':0},cursor=6))


    def test_backlog_aware_scheduler_drains_most_overloaded_stage(self):
        counts={"unvalidated":80,"unreconciled":30,"gate_missing":0,
                "review_actionable":250,"shape_missing":96,"rewrite_actionable":0,
                "promotable":0,"surface_dirty":0}
        self.assertEqual(
            semantic_daemon.choose_stage(counts,cursor=0,backlog_aware=True),
            "shape",
        )

    def test_backlog_aware_scheduler_preserves_round_robin_below_capacity(self):
        counts={"unvalidated":1,"unreconciled":1,"gate_missing":0,
                "review_actionable":1,"shape_missing":1,"rewrite_actionable":1,
                "promotable":0,"surface_dirty":0}
        self.assertEqual(
            semantic_daemon.choose_stage(counts,cursor=2,backlog_aware=True),
            "adjudicate",
        )

    def test_evidence_review_gets_own_turn(self):
        counts={"unvalidated":0,"unreconciled":0,"gate_missing":0,"review_actionable":0,
                "evidence_review_actionable":12,"shape_missing":0,"rewrite_actionable":0,
                "promotable":0,"surface_dirty":0}
        self.assertEqual(semantic_daemon.choose_stage(counts,cursor=4),"evidence")
        self.assertEqual(semantic_daemon.SCRIPTS["evidence"],"distillation_evidence_review.py")

    def test_actionable_review_gets_fair_turn(self):
        counts={"unvalidated":0,"unreconciled":0,"gate_missing":0,"review_actionable":9,
                "shape_missing":3,"rewrite_actionable":0,"promotable":2,"surface_dirty":0}
        self.assertEqual(semantic_daemon.choose_stage(counts,cursor=3),"adjudicate")

    def test_surface_refresh_is_independent_of_actionable_adjudication(self):
        counts={"unvalidated":0,"unreconciled":0,"gate_missing":0,"review_actionable":0,
                "shape_missing":0,"rewrite_actionable":0,"promotable":0,"surface_dirty":1}
        self.assertEqual(semantic_daemon.choose_stage(counts,cursor=0),"surface")
        self.assertEqual(semantic_daemon.SCRIPTS['surface'],'distillation_review_surface.py')


    def test_dirty_review_surface_gets_independent_turn(self):
        counts={"unvalidated":0,"unreconciled":0,"gate_missing":0,"review_actionable":0,
                "shape_missing":0,"rewrite_actionable":0,"promotable":0,"surface_dirty":1}
        self.assertEqual(semantic_daemon.choose_stage(counts,cursor=0),"surface")

    def test_stage_plan_can_pause_promotion_without_pausing_upstream(self):
        counts={"unvalidated":0,"unreconciled":0,"gate_missing":0,"review_actionable":0,
                "shape_missing":0,"rewrite_actionable":0,"promotable":7,"surface_dirty":0}
        self.assertIsNone(semantic_daemon.choose_stage(counts,cursor=6,promotion_enabled=False))
        counts["shape_missing"]=3
        self.assertEqual(semantic_daemon.choose_stage(counts,cursor=6,promotion_enabled=False),"shape")

    def test_run_stage_uses_daemon_interpreter(self):
        completed=SimpleNamespace(returncode=0,stdout='',stderr='')
        with mock.patch.object(semantic_daemon.subprocess,'run',return_value=completed) as run:
            semantic_daemon.run_stage('surface',root=Path('/tmp/goms'))
        self.assertEqual(run.call_args.args[0][0],sys.executable)

    def test_launchagent_resolves_python_from_modern_path(self):
        plist_path=Path(__file__).with_name('launchd')/'org.aineko.goms-distillation-semantic.plist'
        with plist_path.open('rb') as f:
            args=plistlib.load(f)['ProgramArguments']
        self.assertEqual(args[:2],['/usr/bin/env','python3'])

if __name__=='__main__': unittest.main(verbosity=2)
