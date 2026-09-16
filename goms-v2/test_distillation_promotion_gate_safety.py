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
            c.execute("insert into entities(id,type,title,status,tags,metadata,created_at,updated_at) values('project_dead','project','Old Project','deleted','[]','{}','t','t')")
        self.run_script('distillation_promotion_gate.py')
        with closing(sqlite3.connect(self.db)) as c:
            row=c.execute("select decision,reasons from distillation_promotion_gate where candidate_id='c1'").fetchone()
        self.assertNotEqual(row[0],'AUTO_READY')
        self.assertIn('SUBJECT_ENTITY_INACTIVE',json.loads(row[1]))

    def test_dirty_auto_ready_gate_cannot_promote(self):
        self.seed_candidate(subject_mode='new',subject_title='Fresh Project')
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("insert into distillation_promotion_gate(candidate_id,decision,score,reasons,contradiction_count,checked_at,gate_fingerprint) values('c1','AUTO_READY',.95,'[]',0,'t',null)")
            c.execute("insert into distillation_graphshape_reviews(candidate_id,verdict,rationale,reviewer_model,reviewed_at) values('c1','ACCEPT','ok','reviewer','t')")
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

if __name__=='__main__': unittest.main(verbosity=2)
