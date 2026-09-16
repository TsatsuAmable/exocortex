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
      create table entities(id text primary key,type text,title text,status text);
      create table distillation_reconciliation_proposals(
        candidate_id text primary key,canonical_kind text,
        subject_mode text,subject_id text,subject_type text,subject_title text,
        predicate text,object_mode text,object_id text,object_type text,
        object_title text,literal text,confidence real,rationale text,
        status text,created_at text);
      create table distillation_promotion_gate(
        candidate_id text primary key,decision text,score real,reasons text,subject_resolution text,
        object_resolution text,contradiction_count integer,checked_at text);
      create table distillation_graphshape_reviews(candidate_id text primary key,verdict text);
    ''')
    return c


def proposal(c,cid='c1',subject_title='Nemosyne',subject_type='project',object_title='Roadmap',object_type='idea'):
    c.execute('''insert into distillation_reconciliation_proposals values(
      ?, 'constraint','new',null,?,?,'uses','new',null,?,?,null,.9,'rationale','candidate','2026-09-01T00:00:00Z')''',
      (cid,subject_type,subject_title,object_type,object_title))


def gate(c,cid='c1',subject_resolution='project_nemosyne',object_resolution='idea_roadmap',reasons=None,score=.85):
    reasons=reasons or ['SUBJECT_DUPLICATE_EXISTING','OBJECT_DUPLICATE_EXISTING','LOW_COMPOSITE_CONFIDENCE']
    rr.ensure_schema(c)
    c.execute("""insert into distillation_promotion_gate
      (candidate_id,decision,score,reasons,subject_resolution,object_resolution,contradiction_count,checked_at,gate_fingerprint)
      values(?,?,?,?,?,?,?,?,?)""",
      (cid,'REVIEW',score,json.dumps(reasons),subject_resolution,object_resolution,0,'t1','fp:'+cid))


class ReviewReconcilerTests(unittest.TestCase):
    def test_exact_duplicate_rebinds_only_current_unique_compatible_entities(self):
        with closing(make_db()) as c:
            proposal(c)
            c.executemany("insert into entities values(?,?,?,?)",[
                ('project_nemosyne','project','Nemosyne','active'),
                ('idea_roadmap','idea','Roadmap','active'),
            ])
            gate(c)
            c.execute("insert into distillation_graphshape_reviews(candidate_id,verdict) values('c1','REWRITE')")
            result=rr.reconcile_review_batch(c,limit=10,observed_at='t2')
            row=c.execute("select * from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()
            self.assertEqual((row['subject_mode'],row['subject_id']),('existing','project_nemosyne'))
            self.assertEqual((row['object_mode'],row['object_id']),('existing','idea_roadmap'))
            self.assertIsNone(c.execute("select 1 from distillation_promotion_gate where candidate_id='c1'").fetchone())
            self.assertIsNone(c.execute("select 1 from distillation_graphshape_reviews where candidate_id='c1'").fetchone())
            self.assertEqual(result['actions'],{'REBIND_ENTITY':1})

    def test_ambiguous_current_title_match_is_held_not_rebound(self):
        with closing(make_db()) as c:
            proposal(c,object_title='Other',object_type='idea')
            c.executemany("insert into entities values(?,?,?,?)",[
                ('project_nemosyne','project','Nemosyne','active'),
                ('project_nemosyne_2','project','Nemosyne!','active'),
            ])
            gate(c,object_resolution=None,reasons=['SUBJECT_DUPLICATE_EXISTING'])
            result=rr.reconcile_review_batch(c,limit=10,observed_at='t2')
            row=c.execute("select subject_mode,subject_id from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()
            self.assertEqual(tuple(row),('new',None))
            self.assertEqual(result['actions'],{'HOLD':1})

    def test_stale_resolution_id_is_held_not_rebound(self):
        with closing(make_db()) as c:
            proposal(c,object_title='Other',object_type='idea')
            c.execute("insert into entities values('project_nemosyne','project','Renamed project','active')")
            gate(c,object_resolution=None,reasons=['SUBJECT_DUPLICATE_EXISTING'])
            result=rr.reconcile_review_batch(c,limit=10,observed_at='t2')
            self.assertEqual(result['actions'],{'HOLD':1})
            self.assertEqual(c.execute("select subject_mode from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()[0],'new')

    def test_deleted_resolution_is_held_not_rebound(self):
        with closing(make_db()) as c:
            proposal(c,object_title='Other',object_type='idea')
            c.execute("insert into entities values('project_nemosyne','project','Nemosyne','deleted')")
            gate(c,object_resolution=None,reasons=['SUBJECT_DUPLICATE_EXISTING'])
            result=rr.reconcile_review_batch(c,limit=10,observed_at='t2')
            self.assertEqual(result['actions'],{'HOLD':1})

    def test_proposal_change_invalidates_shape_approval_and_requires_regate(self):
        with closing(make_db()) as c:
            c.execute("alter table distillation_promotion_gate add column gate_fingerprint text")
            c.execute("insert into distillation_reconciliation_proposals values('dirty','preference','existing','u',null,'User','status','literal',null,null,null,'old',.95,'r','candidate','t')")
            c.execute("insert into distillation_promotion_gate values('dirty','AUTO_READY',.95,'[]',null,null,0,'t','fp')")
            c.execute("insert into distillation_graphshape_reviews values('dirty','ACCEPT')")
            rr.ensure_schema(c)
            c.execute("update distillation_reconciliation_proposals set literal='new' where candidate_id='dirty'")
            self.assertIsNone(c.execute("select gate_fingerprint from distillation_promotion_gate where candidate_id='dirty'").fetchone()[0])
            self.assertIsNone(c.execute("select 1 from distillation_graphshape_reviews where candidate_id='dirty'").fetchone())

    def test_unicode_empty_normalization_cannot_rebind_unrelated_entity(self):
        with closing(make_db()) as c:
            proposal(c,subject_title='Проект',subject_type='project',object_title='Other',object_type='idea')
            c.execute("insert into entities values('project_other','project','用户','active')")
            gate(c,subject_resolution='project_other',object_resolution=None,reasons=['SUBJECT_DUPLICATE_EXISTING'])
            result=rr.reconcile_review_batch(c,limit=10,observed_at='t2')
            self.assertEqual(result['actions'],{'HOLD':1})
            row=c.execute("select subject_mode,subject_id from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()
            self.assertEqual(tuple(row),('new',None))

    def test_dirty_review_waits_for_regate_before_adjudication(self):
        with closing(make_db()) as c:
            c.execute("insert into distillation_reconciliation_proposals values('dirty-review','preference','existing','u',null,'User','p','literal',null,null,null,'old',.85,'r','candidate','t')")
            gate(c,'dirty-review',None,None,['LOW_COMPOSITE_CONFIDENCE'])
            self.assertEqual(rr.reconcile_review_batch(c,limit=1,observed_at='t2')['processed'],1)
            c.execute("update distillation_reconciliation_proposals set literal='new' where candidate_id='dirty-review'")
            self.assertIsNone(c.execute("select gate_fingerprint from distillation_promotion_gate where candidate_id='dirty-review'").fetchone()[0])
            self.assertEqual(rr.unadjudicated_review_count(c),0)
            self.assertEqual(rr.reconcile_review_batch(c,limit=1,observed_at='t3')['processed'],0)

    def test_changed_authority_payload_reopens_adjudication_even_if_gate_score_and_reason_same(self):
        with closing(make_db()) as c:
            c.execute("insert into distillation_reconciliation_proposals values('cx','preference','existing','u',null,'User','prefers','literal',null,null,null,'short',.85,'r1','candidate','2026-09-01T00:00:00Z')")
            gate(c,'cx',None,None,['LOW_COMPOSITE_CONFIDENCE'])
            first=rr.reconcile_review_batch(c,limit=10,observed_at='t2')
            c.execute("update distillation_reconciliation_proposals set predicate='avoids',literal='long',rationale='r2' where candidate_id='cx'")
            c.execute("update distillation_promotion_gate set checked_at='t9' where candidate_id='cx'")
            dirty=rr.reconcile_review_batch(c,limit=10,observed_at='t3')
            self.assertEqual(dirty['processed'],0)
            c.execute("update distillation_promotion_gate set checked_at='t9',gate_fingerprint='fp:cx:regated' where candidate_id='cx'")
            second=rr.reconcile_review_batch(c,limit=10,observed_at='t4')
            self.assertEqual(first['processed'],1)
            self.assertEqual(second['processed'],1)
            audits=c.execute("select before_state from distillation_review_adjudications where candidate_id='cx' order by adjudicated_at").fetchall()
            self.assertEqual(len(audits),2)
            self.assertIn('predicate',json.loads(audits[0][0]))
            self.assertIn('rationale',json.loads(audits[0][0]))

    def test_nonfactual_is_quarantined_without_deleting_gate(self):
        with closing(make_db()) as c:
            c.execute("insert into distillation_reconciliation_proposals values('c2','proposal','new',null,'idea','Maybe','p','literal',null,null,null,null,.9,'r','candidate','2026-09-01T00:00:00Z')")
            gate(c,'c2',None,None,['NONFACTUAL_KIND'],.9)
            result=rr.reconcile_review_batch(c,limit=10,observed_at='t2')
            self.assertEqual(c.execute("select status from distillation_reconciliation_proposals where candidate_id='c2'").fetchone()[0],'quarantined')
            self.assertEqual(result['actions'],{'QUARANTINE_NONFACTUAL':1})

    def test_low_confidence_is_held_and_idempotent_for_same_gate_fingerprint(self):
        with closing(make_db()) as c:
            c.execute("insert into distillation_reconciliation_proposals values('c3','preference','existing','u',null,'User','p','literal',null,null,null,null,.85,'r','candidate','2026-09-01T00:00:00Z')")
            gate(c,'c3',None,None,['LOW_COMPOSITE_CONFIDENCE'])
            first=rr.reconcile_review_batch(c,limit=10,observed_at='t2')
            c.execute("update distillation_promotion_gate set checked_at='t9' where candidate_id='c3'")
            second=rr.reconcile_review_batch(c,limit=10,observed_at='t3')
            self.assertEqual(first['actions'],{'HOLD':1})
            self.assertEqual(second['processed'],0)
            self.assertEqual(c.execute("select status from distillation_reconciliation_proposals where candidate_id='c3'").fetchone()[0],'candidate')
            self.assertIn('gate_fingerprint',[r[1] for r in c.execute('pragma table_info(distillation_promotion_gate)')])
            self.assertTrue(c.execute("select gate_fingerprint from distillation_promotion_gate where candidate_id='c3'").fetchone()[0])


    def test_legacy_gate_schema_can_load_current_schema_before_explicit_migration(self):
        from pathlib import Path
        with closing(sqlite3.connect(':memory:')) as c:
            schema=Path('schema.sql').read_text()
            c.executescript(schema)
            c.execute('drop table distillation_promotion_gate')
            c.execute('''create table distillation_promotion_gate(
              candidate_id text primary key,decision text,score real,reasons text,
              subject_resolution text,object_resolution text,contradiction_count integer,checked_at text)''')
            # Replaying current schema over a legacy live table must not reference
            # the new column before the explicit reconciler migration adds it.
            c.executescript(schema)
            self.assertNotIn('gate_fingerprint',[r[1] for r in c.execute('pragma table_info(distillation_promotion_gate)')])
            rr.ensure_schema(c)
            self.assertIn('gate_fingerprint',[r[1] for r in c.execute('pragma table_info(distillation_promotion_gate)')])
            trigger=c.execute("select name from sqlite_master where type='trigger' and name='distillation_review_proposal_fingerprint_dirty'").fetchone()
            self.assertIsNotNone(trigger)

    def test_unadjudicated_detection_uses_current_persisted_fingerprint(self):
        with closing(make_db()) as c:
            c.execute("insert into distillation_reconciliation_proposals values('c4','preference','existing','u',null,'User','p','literal',null,null,null,null,.85,'r','candidate','2026-09-01T00:00:00Z')")
            gate(c,'c4',None,None,['LOW_COMPOSITE_CONFIDENCE'])
            self.assertEqual(rr.unadjudicated_review_count(c),1)
            rr.reconcile_review_batch(c,limit=1,observed_at='t2')
            self.assertEqual(rr.unadjudicated_review_count(c),0)


    def test_legacy_shape_approval_is_unversioned_after_migration(self):
        with closing(make_db()) as c:
            proposal(c,cid='legacy-shape')
            gate(c,'legacy-shape',None,None,['LOW_COMPOSITE_CONFIDENCE'])
            c.execute("insert into distillation_graphshape_reviews(candidate_id,verdict) values('legacy-shape','ACCEPT')")
            rr.ensure_schema(c)
            cols=[r[1] for r in c.execute('pragma table_info(distillation_graphshape_reviews)')]
            self.assertIn('gate_fingerprint',cols)
            self.assertIsNone(c.execute("select gate_fingerprint from distillation_graphshape_reviews where candidate_id='legacy-shape'").fetchone()[0])

    def test_schema_migration_replaces_old_fingerprint_trigger(self):
        with closing(make_db()) as c:
            c.execute("alter table distillation_promotion_gate add column gate_fingerprint text")
            c.executescript("""create trigger distillation_review_proposal_fingerprint_dirty
              after update of literal on distillation_reconciliation_proposals begin
                update distillation_promotion_gate set gate_fingerprint=null where candidate_id=new.candidate_id;
              end;""")
            c.execute("insert into distillation_reconciliation_proposals values('legacy','preference','existing','u',null,'User','p','literal',null,null,null,'old',.9,'r','candidate','t')")
            c.execute("insert into distillation_promotion_gate values('legacy','AUTO_READY',.9,'[]',null,null,0,'t','fp')")
            c.execute("insert into distillation_graphshape_reviews values('legacy','ACCEPT')")
            rr.ensure_schema(c)
            sql=c.execute("select sql from sqlite_master where type='trigger' and name='distillation_review_proposal_fingerprint_dirty'").fetchone()[0].lower()
            self.assertIn('delete from distillation_graphshape_reviews',sql)
            c.execute("update distillation_reconciliation_proposals set literal='new' where candidate_id='legacy'")
            self.assertIsNone(c.execute("select 1 from distillation_graphshape_reviews where candidate_id='legacy'").fetchone())

if __name__=='__main__': unittest.main(verbosity=2)
