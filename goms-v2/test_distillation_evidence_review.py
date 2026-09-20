#!/usr/bin/env python3
from contextlib import closing
import json
import sqlite3
import unittest
from unittest import mock

import distillation_evidence_review as er


def make_db():
    c=sqlite3.connect(':memory:')
    c.row_factory=sqlite3.Row
    c.executescript("""
      create table entities(
        id text primary key,type text,title text,summary text,status text,
        tags text,metadata text,created_at text,updated_at text);
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
      create table distillation_candidates(
        id text primary key,confidence real,evidence_ids text);
      create table distillation_validations(
        candidate_id text primary key,confidence real,verdict text,
        validated_kind text,durability text);
      create table distillation_temporal_authority(
        candidate_id text primary key,temporal_mode text,observed_at text,
        auto_eligible integer,reasons text,checked_at text);
      create table distillation_review_adjudications(
        candidate_id text,gate_fingerprint text,gate_checked_at text,
        action text,reason text,before_state text,after_state text,
        adjudicated_at text,primary key(candidate_id,gate_fingerprint));
      create table distillation_graphshape_reviews(
        candidate_id text primary key,verdict text,rationale text,
        subject_title text,subject_type text,predicate text,
        object_title text,object_type text,literal text,
        reviewer_model text,reviewed_at text,gate_fingerprint text);
    """)
    return c


def seed(c):
    c.execute("""insert into entities values(
      'e1','evidence','user evidence','I prefer Mac-first execution for this project.',
      'observed','[]','{}','2026-09-20T10:00:00Z','2026-09-20T10:00:00Z')""")
    c.execute("""insert into distillation_reconciliation_proposals values(
      'c1','preference','existing','user1','person','User','prefers',
      'literal',null,null,null,'Mac-first execution',.84,'r','candidate','t0')""")
    c.execute("""insert into distillation_promotion_gate values(
      'c1','REVIEW',.84,'["LOW_COMPOSITE_CONFIDENCE"]',
      null,null,0,'t1','base-fp')""")
    c.execute("insert into distillation_candidates values('c1',.84,'[\"e1\"]')")
    c.execute("""insert into distillation_validations values(
      'c1',.84,'accept','preference','enduring')""")
    c.execute("""insert into distillation_temporal_authority values(
      'c1','CURRENT_STATE','2026-09-20T10:00:00Z',1,'[]','t1')""")
    c.execute("""insert into distillation_review_adjudications values(
      'c1','base-fp','t1','HOLD','LOW_COMPOSITE_CONFIDENCE','{}','{}','t2')""")
    c.commit()


def generator_factory(verdicts):
    calls=[]
    def generate(prompt, *, models):
        model=models[0]
        calls.append(model)
        verdict,confidence=verdicts[model]
        return {
          'model':model,
          'parsed':{'items':[{
            'candidate_id':'c1','verdict':verdict,
            'confidence':confidence,'rationale':'evidence review'
          }]}
        }
    return generate,calls


class EvidenceReviewTests(unittest.TestCase):
    def test_unanimous_high_confidence_review_activates_gate(self):
        with closing(make_db()) as c:
            seed(c)
            gen,calls=generator_factory({'m1':('ACCEPT',.96),'m2':('ACCEPT',.94)})
            with mock.patch.object(er,'select_reviewer_models',return_value=['m1','m2']):
                result=er.review_batch(c,limit=5,generator=gen)
            self.assertEqual(result['activated'],1)
            self.assertEqual(calls,['m1','m2'])
            gate=c.execute("select decision,reasons,gate_fingerprint from distillation_promotion_gate where candidate_id='c1'").fetchone()
            self.assertEqual(gate['decision'],'AUTO_READY')
            reasons=json.loads(gate['reasons'])
            self.assertNotIn('LOW_COMPOSITE_CONFIDENCE',reasons)
            self.assertIn('EVIDENCE_SUFFICIENCY_CONSENSUS',reasons)
            self.assertNotEqual(gate['gate_fingerprint'],'base-fp')
            decision=c.execute("select decision,confidence from distillation_evidence_review_decisions where candidate_id='c1'").fetchone()
            self.assertEqual(decision['decision'],'ACCEPT')
            self.assertAlmostEqual(decision['confidence'],.94)

    def test_structured_failure_falls_through_to_more_qualified_reviewers(self):
        with closing(make_db()) as c:
            seed(c)
            calls=[]
            def generator(prompt, *, models):
                model=models[0]; calls.append(model)
                if model=='m1':
                    raise RuntimeError('structured output unavailable')
                return {'model':model,'parsed':{'items':[{
                    'candidate_id':'c1','verdict':'ACCEPT','confidence':.96,
                    'rationale':'direct evidence'}]}}
            with mock.patch.object(er,'select_reviewer_models',return_value=['m1','m2','m3']):
                result=er.review_batch(c,limit=5,generator=generator)
            self.assertEqual(result['activated'],1)
            self.assertEqual(calls,['m1','m2','m3'])
            self.assertIn('m1',result['model_errors'])
            reviewers=json.loads(c.execute(
                "select reviewer_models from distillation_evidence_review_decisions where candidate_id='c1'"
            ).fetchone()[0])
            self.assertEqual(reviewers,['m2','m3'])

    def test_transient_reviewer_failure_leaves_candidate_pending(self):
        with closing(make_db()) as c:
            seed(c)
            def generator(prompt, *, models):
                raise RuntimeError('provider unavailable')
            with mock.patch.object(er,'select_reviewer_models',return_value=['m1','m2','m3']):
                result=er.review_batch(c,limit=5,generator=generator)
            self.assertEqual(result['decisions']['PENDING'],1)
            self.assertIsNone(c.execute(
                "select 1 from distillation_evidence_review_decisions where candidate_id='c1'"
            ).fetchone())
            gate=c.execute("select decision,gate_fingerprint from distillation_promotion_gate where candidate_id='c1'").fetchone()
            self.assertEqual(tuple(gate),('REVIEW','base-fp'))

    def test_reject_keeps_gate_in_review(self):
        with closing(make_db()) as c:
            seed(c)
            gen,_=generator_factory({'m1':('ACCEPT',.96),'m2':('REJECT',.95)})
            with mock.patch.object(er,'select_reviewer_models',return_value=['m1','m2']):
                result=er.review_batch(c,limit=5,generator=gen)
            self.assertEqual(result['activated'],0)
            gate=c.execute("select decision,gate_fingerprint from distillation_promotion_gate where candidate_id='c1'").fetchone()
            self.assertEqual(tuple(gate),('REVIEW','base-fp'))
            decision=c.execute("select decision from distillation_evidence_review_decisions where candidate_id='c1'").fetchone()[0]
            self.assertEqual(decision,'REJECT')

    def test_insufficient_reviewers_cannot_authorize(self):
        verdict,confidence,reason=er.aggregate_reviews(
            [{'model':'m1','verdict':'ACCEPT','confidence':.99}],
            required=2,
        )
        self.assertEqual(verdict,'ABSTAIN')
        self.assertEqual(reason,'INSUFFICIENT_QUALIFIED_REVIEWERS')

    def test_low_confidence_consensus_requires_high_reviewer_confidence(self):
        verdict,confidence,reason=er.aggregate_reviews([
          {'model':'m1','verdict':'ACCEPT','confidence':.89},
          {'model':'m2','verdict':'ACCEPT','confidence':.95},
        ])
        self.assertEqual(verdict,'ABSTAIN')


if __name__=='__main__':
    unittest.main(verbosity=2)
