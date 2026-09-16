#!/usr/bin/env python3
from contextlib import closing
import json
import sqlite3
import unittest

import distillation_review_reconciler as rr


def make_db():
    c=sqlite3.connect(':memory:')
    c.row_factory=sqlite3.Row
    c.executescript('''
      create table distillation_reconciliation_proposals(
        candidate_id text primary key,subject_mode text,subject_id text,subject_type text,subject_title text,
        object_mode text,object_id text,object_type text,object_title text,status text);
      create table distillation_promotion_gate(
        candidate_id text primary key,decision text,score real,reasons text,subject_resolution text,
        object_resolution text,contradiction_count integer,checked_at text);
      create table distillation_graphshape_reviews(candidate_id text primary key,verdict text);
    ''')
    return c


class ReviewReconcilerTests(unittest.TestCase):
    def test_exact_duplicate_rebinds_proposal_and_invalidates_gate(self):
        with closing(make_db()) as c:
            c.execute("insert into distillation_reconciliation_proposals values(?,?,?,?,?,?,?,?,?,?)",
                      ('c1','new',None,'project','Nemosyne','new',None,'idea','Roadmap','candidate'))
            c.execute("insert into distillation_promotion_gate values(?,?,?,?,?,?,?,?)",
                      ('c1','REVIEW',.85,json.dumps(['SUBJECT_DUPLICATE_EXISTING','OBJECT_DUPLICATE_EXISTING','LOW_COMPOSITE_CONFIDENCE']),
                       'project_nemosyne','idea_roadmap',0,'t1'))
            c.execute("insert into distillation_graphshape_reviews values('c1','REWRITE')")
            result=rr.reconcile_review_batch(c,limit=10,observed_at='t2')
            row=c.execute("select * from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()
            self.assertEqual((row['subject_mode'],row['subject_id']),('existing','project_nemosyne'))
            self.assertEqual((row['object_mode'],row['object_id']),('existing','idea_roadmap'))
            self.assertIsNone(c.execute("select 1 from distillation_promotion_gate where candidate_id='c1'").fetchone())
            self.assertIsNone(c.execute("select 1 from distillation_graphshape_reviews where candidate_id='c1'").fetchone())
            self.assertEqual(result['actions'],{'REBIND_ENTITY':1})

    def test_nonfactual_is_quarantined_without_deleting_gate(self):
        with closing(make_db()) as c:
            c.execute("insert into distillation_reconciliation_proposals values('c2','new',null,'idea','Maybe','literal',null,null,null,'candidate')")
            c.execute("insert into distillation_promotion_gate values(?,?,?,?,?,?,?,?)",
                      ('c2','REVIEW',.9,json.dumps(['NONFACTUAL_KIND']),None,None,0,'t1'))
            result=rr.reconcile_review_batch(c,limit=10,observed_at='t2')
            self.assertEqual(c.execute("select status from distillation_reconciliation_proposals where candidate_id='c2'").fetchone()[0],'quarantined')
            self.assertEqual(result['actions'],{'QUARANTINE_NONFACTUAL':1})

    def test_low_confidence_is_held_and_idempotent_for_same_gate_check(self):
        with closing(make_db()) as c:
            c.execute("insert into distillation_reconciliation_proposals values('c3','existing','u',null,'User','literal',null,null,null,'candidate')")
            c.execute("insert into distillation_promotion_gate values(?,?,?,?,?,?,?,?)",
                      ('c3','REVIEW',.85,json.dumps(['LOW_COMPOSITE_CONFIDENCE']),None,None,0,'t1'))
            first=rr.reconcile_review_batch(c,limit=10,observed_at='t2')
            c.execute("update distillation_promotion_gate set checked_at='t9' where candidate_id='c3'")
            second=rr.reconcile_review_batch(c,limit=10,observed_at='t3')
            self.assertEqual(first['actions'],{'HOLD':1})
            self.assertEqual(second['processed'],0)
            self.assertEqual(c.execute("select status from distillation_reconciliation_proposals where candidate_id='c3'").fetchone()[0],'candidate')
            audit=c.execute("select action,reason,gate_checked_at from distillation_review_adjudications where candidate_id='c3'").fetchone()
            self.assertEqual(tuple(audit),('HOLD','LOW_COMPOSITE_CONFIDENCE','t1'))


if __name__=='__main__': unittest.main(verbosity=2)
