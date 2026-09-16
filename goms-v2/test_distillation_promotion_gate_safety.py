#!/usr/bin/env python3
from contextlib import closing
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import distillation_semantic_daemon as semantic_daemon

SCHEMA=Path('schema.sql').read_text()
HERE=Path(__file__).resolve().parent

class PromotionGateSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='gate-safety-')
        self.home=Path(self.tmp.name)
        self.root=self.home/'Library/Application Support/Aineko/GOMS'
        self.root.mkdir(parents=True)
        self.db=self.root/'goms.sqlite3'
        with closing(sqlite3.connect(self.db)) as c:
            c.executescript(SCHEMA)

    def tearDown(self): self.tmp.cleanup()

    def run_script(self,name):
        env=dict(os.environ); env['HOME']=str(self.home)
        return subprocess.run([sys.executable,str(HERE/name)],cwd=HERE,env=env,
                              text=True,capture_output=True,check=True)

    def seed_candidate(self,cid='c1',subject_mode='new',subject_id=None,
                       subject_type='project',subject_title='Project',literal='active'):
        evidence='evidence_gate_safety'
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("insert into entities(id,type,title,status,tags,metadata,created_at,updated_at) values(?,?,?,?,?,?,?,?)",
                      (evidence,'evidence','Gate evidence','active','[]',json.dumps({'create_time':'2026-09-16T00:00:00+00:00'}),'2026-09-16T00:00:00+00:00','2026-09-16T00:00:00+00:00'))
            c.execute("insert into distillation_candidates(id,run_id,kind,subject,predicate,literal,confidence,evidence_ids,status,created_at) values(?,?,?,?,?,?,?,?,?,?)",
                      (cid,'run','preference',subject_title,'status',literal,.95,json.dumps([evidence]),'candidate','2026-09-16T00:00:00+00:00'))
            c.execute("insert into distillation_validations(candidate_id,verdict,validated_kind,durability,confidence,rationale,validator_model) values(?,?,?,?,?,?,?)",
                      (cid,'accept','preference','project',.95,'valid','test-validator'))
            c.execute("insert into distillation_reconciliation_proposals(candidate_id,canonical_kind,subject_mode,subject_id,subject_type,subject_title,predicate,object_mode,literal,confidence,rationale,status,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (cid,'preference',subject_mode,subject_id,subject_type,subject_title,'status','literal',literal,.95,'r','candidate','2026-09-16T00:00:00+00:00'))

    def test_unicode_titles_never_collapse_into_false_exact_rebind(self):
        self.seed_candidate(subject_title='Проект',subject_type='project')
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("insert into entities(id,type,title,status,tags,metadata,created_at,updated_at) values('project_other','project','用户','active','[]','{}','t','t')")
        self.run_script('distillation_promotion_gate.py')
        with closing(sqlite3.connect(self.db)) as c:
            row=c.execute("select decision,subject_resolution,reasons from distillation_promotion_gate where candidate_id='c1'").fetchone()
        self.assertIsNone(row[1])
        self.assertNotIn('SUBJECT_DUPLICATE_EXISTING',json.loads(row[2]))

    def test_inactive_existing_entity_cannot_be_auto_ready(self):
        self.seed_candidate(subject_mode='existing',subject_id='project_dead',subject_title='Old Project')
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("insert into entities(id,type,title,status,tags,metadata,created_at,updated_at) values('project_dead','project','Old Project','inactive','[]','{}','t','t')")
        self.run_script('distillation_promotion_gate.py')
        with closing(sqlite3.connect(self.db)) as c:
            row=c.execute("select decision,reasons from distillation_promotion_gate where candidate_id='c1'").fetchone()
        self.assertNotEqual(row[0],'AUTO_READY')
        self.assertIn('SUBJECT_ENTITY_INACTIVE',json.loads(row[1]))

    def test_dirty_auto_ready_gate_cannot_promote(self):
        self.seed_candidate(subject_mode='new',subject_title='Fresh Project')
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("insert into distillation_promotion_gate(candidate_id,decision,score,reasons,contradiction_count,checked_at,gate_fingerprint) values('c1','AUTO_READY',.95,'[]',0,'t',null)")
            c.execute("""insert into distillation_graphshape_reviews(candidate_id,verdict,rationale,reviewer_model,reviewed_at,gate_fingerprint) select 'c1','ACCEPT','ok','reviewer','t',gate_fingerprint from distillation_promotion_gate where candidate_id='c1'""")
            c.execute("insert into distillation_temporal_authority(candidate_id,temporal_mode,observed_at,auto_eligible,reasons,checked_at) values('c1','CURRENT_STATE','2026-09-16T00:00:00+00:00',1,'[]','t')")
        counts=semantic_daemon.stage_counts(self.db)
        self.assertEqual(counts['gate_missing'],1)
        self.assertEqual(counts['promotable'],0)
        self.run_script('distillation_promote.py')
        with closing(sqlite3.connect(self.db)) as c:
            status=c.execute("select status from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()[0]
            assertions=c.execute("select count(*) from semantic_assertions where source_ref='distillation://c1'").fetchone()[0]
        self.assertEqual(status,'candidate')
        self.assertEqual(assertions,0)

    def test_promotion_rechecks_existing_entity_status_after_gate(self):
        self.seed_candidate(subject_mode='existing',subject_id='project_live',subject_title='Live Project')
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("insert into entities(id,type,title,status,tags,metadata,created_at,updated_at) values('project_live','project','Live Project','active','[]','{}','t','t')")
        self.run_script('distillation_promotion_gate.py')
        with closing(sqlite3.connect(self.db)) as c, c:
            gate=c.execute("select decision,gate_fingerprint from distillation_promotion_gate where candidate_id='c1'").fetchone()
            self.assertEqual(gate[0],'AUTO_READY'); self.assertTrue(gate[1])
            c.execute("""insert into distillation_graphshape_reviews(candidate_id,verdict,rationale,reviewer_model,reviewed_at,gate_fingerprint) select 'c1','ACCEPT','ok','reviewer','t',gate_fingerprint from distillation_promotion_gate where candidate_id='c1'""")
            c.execute("update entities set status='inactive' where id='project_live'")
        self.run_script('distillation_promote.py')
        with closing(sqlite3.connect(self.db)) as c:
            self.assertEqual(c.execute("select status from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()[0],'candidate')
            self.assertEqual(c.execute("select count(*) from semantic_assertions where source_ref='distillation://c1'").fetchone()[0],0)
            self.assertIsNone(c.execute("select gate_fingerprint from distillation_promotion_gate where candidate_id='c1'").fetchone()[0])
            self.assertIsNone(c.execute("select 1 from distillation_graphshape_reviews where candidate_id='c1'").fetchone())

    def test_promotion_rechecks_human_authority_after_gate(self):
        self.seed_candidate(subject_mode='existing',subject_id='project_live',subject_title='Live Project',literal='model-set')
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("insert into entities(id,type,title,status,tags,metadata,created_at,updated_at) values('project_live','project','Live Project','active','[]','{}','t','t')")
        self.run_script('distillation_promotion_gate.py')
        with closing(sqlite3.connect(self.db)) as c, c:
            gate=c.execute("select decision,gate_fingerprint from distillation_promotion_gate where candidate_id='c1'").fetchone()
            self.assertEqual(gate[0],'AUTO_READY'); self.assertTrue(gate[1])
            c.execute("""insert into distillation_graphshape_reviews(candidate_id,verdict,rationale,reviewer_model,reviewed_at,gate_fingerprint) select 'c1','ACCEPT','ok','reviewer','t',gate_fingerprint from distillation_promotion_gate where candidate_id='c1'""")
            c.execute("insert into semantic_assertions(id,subject_id,predicate,literal_value,epistemic_status,valid_from,valid_to,source_ref,created_at,updated_at) values('human_state','project_live','status','human-set','explicit','2026-09-15T00:00:00+00:00',null,'human://decision','t','t')")
        self.run_script('distillation_promote.py')
        with closing(sqlite3.connect(self.db)) as c:
            self.assertEqual(c.execute("select status from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()[0],'candidate')
            self.assertEqual(c.execute("select count(*) from semantic_assertions where source_ref='distillation://c1'").fetchone()[0],0)
            self.assertIsNone(c.execute("select gate_fingerprint from distillation_promotion_gate where candidate_id='c1'").fetchone()[0])
            self.assertIsNone(c.execute("select 1 from distillation_graphshape_reviews where candidate_id='c1'").fetchone())

    def test_promotion_rejects_temporal_profile_changed_after_gate(self):
        self.seed_candidate(subject_mode='existing',subject_id='project_live',subject_title='Live Project')
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("insert into entities(id,type,title,status,tags,metadata,created_at,updated_at) values('project_live','project','Live Project','active','[]','{}','t','t')")
        self.run_script('distillation_promotion_gate.py')
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("""insert into distillation_graphshape_reviews(candidate_id,verdict,rationale,reviewer_model,reviewed_at,gate_fingerprint) select 'c1','ACCEPT','ok','reviewer','t',gate_fingerprint from distillation_promotion_gate where candidate_id='c1'""")
            c.execute("update distillation_temporal_authority set observed_at='2026-09-17T00:00:00+00:00' where candidate_id='c1'")
        self.run_script('distillation_promote.py')
        with closing(sqlite3.connect(self.db)) as c:
            self.assertEqual(c.execute("select status from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()[0],'candidate')
            self.assertIsNone(c.execute("select gate_fingerprint from distillation_promotion_gate where candidate_id='c1'").fetchone()[0])

    def test_promotion_rejects_validation_changed_after_gate(self):
        self.seed_candidate(subject_mode='existing',subject_id='project_live',subject_title='Live Project')
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("insert into entities(id,type,title,status,tags,metadata,created_at,updated_at) values('project_live','project','Live Project','active','[]','{}','t','t')")
        self.run_script('distillation_promotion_gate.py')
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("""insert into distillation_graphshape_reviews(candidate_id,verdict,rationale,reviewer_model,reviewed_at,gate_fingerprint) select 'c1','ACCEPT','ok','reviewer','t',gate_fingerprint from distillation_promotion_gate where candidate_id='c1'""")
            c.execute("update distillation_validations set verdict='reject',confidence=.1 where candidate_id='c1'")
        self.run_script('distillation_promote.py')
        with closing(sqlite3.connect(self.db)) as c:
            self.assertEqual(c.execute("select status from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()[0],'candidate')
            self.assertIsNone(c.execute("select gate_fingerprint from distillation_promotion_gate where candidate_id='c1'").fetchone()[0])

    def test_observation_rechecks_bounded_human_authority_after_gate(self):
        self.seed_candidate(subject_mode='existing',subject_id='project_live',subject_title='Live Project',literal='observed-other')
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("insert into entities(id,type,title,status,tags,metadata,created_at,updated_at) values('project_live','project','Live Project','active','[]','{}','t','t')")
            c.execute("update distillation_reconciliation_proposals set canonical_kind='metric' where candidate_id='c1'")
            c.execute("update distillation_validations set validated_kind='metric' where candidate_id='c1'")
        self.run_script('distillation_promotion_gate.py')
        with closing(sqlite3.connect(self.db)) as c, c:
            gate=c.execute("select decision,gate_fingerprint from distillation_promotion_gate where candidate_id='c1'").fetchone()
            self.assertEqual(gate[0],'AUTO_READY'); self.assertTrue(gate[1])
            c.execute("""insert into distillation_graphshape_reviews(candidate_id,verdict,rationale,reviewer_model,reviewed_at,gate_fingerprint) select 'c1','ACCEPT','ok','reviewer','t',gate_fingerprint from distillation_promotion_gate where candidate_id='c1'""")
            c.execute("insert into semantic_assertions(id,subject_id,predicate,literal_value,epistemic_status,valid_from,valid_to,source_ref,created_at,updated_at) values('human_window','project_live','status','human-set','explicit','2026-09-15T00:00:00+00:00','2026-09-17T00:00:00+00:00','human://decision','t','t')")
        self.run_script('distillation_promote.py')
        with closing(sqlite3.connect(self.db)) as c:
            self.assertEqual(c.execute("select status from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()[0],'candidate')
            self.assertEqual(c.execute("select count(*) from semantic_assertions where source_ref='distillation://c1'").fetchone()[0],0)

    def test_new_subject_duplicate_created_after_gate_blocks_promotion(self):
        self.seed_candidate(subject_mode='new',subject_title='Fresh Project',subject_type='project')
        self.run_script('distillation_promotion_gate.py')
        with closing(sqlite3.connect(self.db)) as c, c:
            gate=c.execute("select decision,gate_fingerprint from distillation_promotion_gate where candidate_id='c1'").fetchone()
            self.assertEqual(gate[0],'AUTO_READY'); self.assertTrue(gate[1])
            c.execute("""insert into distillation_graphshape_reviews(candidate_id,verdict,rationale,reviewer_model,reviewed_at,gate_fingerprint) select 'c1','ACCEPT','ok','reviewer','t',gate_fingerprint from distillation_promotion_gate where candidate_id='c1'""")
            c.execute("insert into entities(id,type,title,status,tags,metadata,created_at,updated_at) values('project_racer','project','Fresh Project','active','[]','{}','t','t')")
        self.run_script('distillation_promote.py')
        with closing(sqlite3.connect(self.db)) as c:
            self.assertEqual(c.execute("select status from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()[0],'candidate')
            self.assertEqual(c.execute("select count(*) from semantic_assertions where source_ref='distillation://c1'").fetchone()[0],0)

    def test_failed_boundary_check_does_not_leave_new_entity(self):
        self.seed_candidate(subject_mode='new',subject_title='Transient Project',subject_type='project')
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("insert into entities(id,type,title,status,tags,metadata,created_at,updated_at) values('obj_live','idea','Live Object','active','[]','{}','t','t')")
            c.execute("update distillation_reconciliation_proposals set object_mode='existing',object_id='obj_live',object_type='idea',object_title='Live Object' where candidate_id='c1'")
        self.run_script('distillation_promotion_gate.py')
        with closing(sqlite3.connect(self.db)) as c, c:
            gate=c.execute("select decision,gate_fingerprint from distillation_promotion_gate where candidate_id='c1'").fetchone()
            self.assertEqual(gate[0],'AUTO_READY'); self.assertTrue(gate[1])
            c.execute("""insert into distillation_graphshape_reviews(candidate_id,verdict,rationale,reviewer_model,reviewed_at,gate_fingerprint) select 'c1','ACCEPT','ok','reviewer','t',gate_fingerprint from distillation_promotion_gate where candidate_id='c1'""")
            c.execute("update entities set status='inactive' where id='obj_live'")
        self.run_script('distillation_promote.py')
        expected='project_'+__import__('hashlib').sha256('Transient Project'.encode()).hexdigest()[:20]
        with closing(sqlite3.connect(self.db)) as c:
            self.assertIsNone(c.execute("select 1 from entities where id=?",(expected,)).fetchone())
            self.assertEqual(c.execute("select status from distillation_reconciliation_proposals where candidate_id='c1'").fetchone()[0],'candidate')

if __name__=='__main__': unittest.main(verbosity=2)
