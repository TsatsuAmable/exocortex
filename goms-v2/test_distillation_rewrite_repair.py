#!/usr/bin/env python3
from contextlib import closing
import sqlite3
import unittest

import distillation_rewrite_repair as rr


def make_db():
    c=sqlite3.connect(':memory:')
    c.row_factory=sqlite3.Row
    c.executescript("""
      create table entities(id text primary key,type text,title text,status text);
      create table distillation_reconciliation_proposals(
        candidate_id text primary key,canonical_kind text,
        subject_mode text,subject_id text,subject_type text,subject_title text,
        predicate text,object_mode text,object_id text,object_type text,
        object_title text,literal text,confidence real,rationale text,
        status text,created_at text);
      create table distillation_promotion_gate(
        candidate_id text primary key,decision text,score real,reasons text,
        subject_resolution text,object_resolution text,contradiction_count integer,
        checked_at text,gate_fingerprint text);
      create table distillation_graphshape_reviews(
        candidate_id text primary key,verdict text,rationale text,
        subject_title text,subject_type text,predicate text,
        object_title text,object_type text,literal text,
        reviewer_model text,reviewed_at text,gate_fingerprint text);
      create table distillation_graphshape_review_history(
        candidate_id text,reviewer_model text,verdict text,rationale text,
        subject_title text,subject_type text,predicate text,
        object_title text,object_type text,literal text,reviewed_at text);
    """)
    return c


def seed(c, *, cid='c1', second_predicate='requires'):
    c.execute("""insert into distillation_reconciliation_proposals values(
      ?,'constraint','new',null,'idea','Sentence shaped subject','should_have',
      'new',null,'idea','Sentence shaped object',null,.9,'r','candidate','t0')""",(cid,))
    c.execute("""insert into distillation_promotion_gate values(
      ?,'AUTO_READY',.91,'[]',null,null,0,'t1','fp1')""",(cid,))
    c.execute("""insert into distillation_graphshape_reviews values(
      ?,'REWRITE','CONSENSUS_REWRITE reviewer-a:REWRITE,reviewer-b:REWRITE',
      null,null,null,null,null,null,'committee:reviewer-a,reviewer-b','t2','fp1')""",(cid,))
    rows=[
      (cid,'reviewer-a','REWRITE','r','Nemosyne','project','requires','Representation compiler','component',None,'t2'),
      (cid,'reviewer-b','REWRITE','r','Nemosyne','project',second_predicate,'Representation compiler','component',None,'t2'),
    ]
    c.executemany("insert into distillation_graphshape_review_history values(?,?,?,?,?,?,?,?,?,?,?)",rows)


class RewriteRepairTests(unittest.TestCase):
    def test_exact_consensus_rewrite_reenters_gate_pipeline(self):
        with closing(make_db()) as c:
            seed(c)
            self.assertEqual(rr.actionable_rewrite_count(c),1)
            result=rr.repair_batch(c,limit=10,observed_at='t3')
            self.assertEqual(result['repaired'],1)
            p=c.execute("select * from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()
            self.assertEqual((p['subject_title'],p['subject_type'],p['predicate']),
                             ('Nemosyne','project','requires'))
            self.assertEqual((p['object_mode'],p['object_title'],p['object_type']),
                             ('new','Representation compiler','component'))
            self.assertIsNone(c.execute("select gate_fingerprint from distillation_promotion_gate where candidate_id='c1'").fetchone()[0])
            self.assertIsNone(c.execute("select 1 from distillation_graphshape_reviews where candidate_id='c1'").fetchone())
            audit=c.execute("select action,reason from distillation_rewrite_repairs where candidate_id='c1'").fetchone()
            self.assertEqual(tuple(audit),('APPLY_EXACT_CONSENSUS_REWRITE','CONSENSUS_REWRITE_IDENTICAL_SHAPE'))

    def test_disagreement_is_not_auto_rewritten(self):
        with closing(make_db()) as c:
            seed(c,second_predicate='supports')
            self.assertEqual(rr.actionable_rewrite_count(c),0)
            self.assertEqual(rr.repair_batch(c,limit=10)['repaired'],0)
            p=c.execute("select predicate from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()
            self.assertEqual(p[0],'should_have')

    def test_existing_subject_identity_is_not_rewritten(self):
        with closing(make_db()) as c:
            seed(c)
            c.execute("update distillation_reconciliation_proposals set subject_mode='existing',subject_id='p1' where candidate_id='c1'")
            self.assertEqual(rr.actionable_rewrite_count(c),0)


if __name__=='__main__':
    unittest.main(verbosity=2)
