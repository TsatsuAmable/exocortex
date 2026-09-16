#!/usr/bin/env python3
import json
import sqlite3
import unittest

import canonical_temporal_migrate as mig


class CanonicalTemporalMigrationTests(unittest.TestCase):
    def _db(self):
        c=sqlite3.connect(':memory:')
        c.executescript('''
          create table entities(id text primary key,metadata text,created_at text);
          create table distillation_candidates(id text primary key,evidence_ids text);
          create table distillation_validations(candidate_id text primary key,durability text);
          create table distillation_reconciliation_proposals(candidate_id text primary key,canonical_kind text,status text);
          create table semantic_assertions(
            id text primary key,subject_id text,predicate text,object_id text,literal_value text,
            confidence real,epistemic_status text,valid_from text,valid_to text,source_entity_id text,
            source_ref text,supersedes text,metadata text,created_at text,updated_at text);
        ''')
        return c

    def _seed(self,c,cid,kind,created,subject,predicate,literal):
        eid='e_'+cid
        c.execute('insert into entities values(?,?,?)',(eid,json.dumps({'create_time':created}),'2026-01-01T00:00:00+00:00'))
        c.execute('insert into distillation_candidates values(?,?)',(cid,json.dumps([eid])))
        c.execute('insert into distillation_validations values(?,?)',(cid,'project'))
        c.execute('insert into distillation_reconciliation_proposals values(?,?,?)',(cid,kind,'promoted'))
        c.execute('insert into semantic_assertions values(?,?,?,?,?,1.0,?,null,null,null,?,null,?, ?, ?)',
                  ('a_'+cid,subject,predicate,None,literal,'validated_extracted','distillation://'+cid,'{}','2026-09-16T00:00:00+00:00','2026-09-16T00:00:00+00:00'))

    def test_migration_preserves_rows_but_separates_history_and_nonfactual(self):
        c=self._db()
        self._seed(c,'metric','metric',10,'build','has_failures','4 failed tests')
        self._seed(c,'proposal','proposal',20,'user','proposes','idea x')
        self._seed(c,'objective','objective',30,'user','has_objective','write paper')
        before=c.execute('select count(*) from semantic_assertions').fetchone()[0]
        report=mig.migrate(c,'2026-09-16T05:00:00+00:00',apply=True)
        after=c.execute('select count(*) from semantic_assertions').fetchone()[0]
        self.assertEqual(before,after)
        metric=c.execute("select epistemic_status,valid_from,valid_to from semantic_assertions where id='a_metric'").fetchone()
        self.assertEqual(metric,('historical_observation','1970-01-01T00:00:10+00:00','1970-01-01T00:00:10+00:00'))
        proposal=c.execute("select epistemic_status,valid_to from semantic_assertions where id='a_proposal'").fetchone()
        self.assertEqual(proposal,('quarantined_nonfactual','1970-01-01T00:00:20+00:00'))
        self.assertEqual(c.execute("select status from distillation_reconciliation_proposals where candidate_id='proposal'").fetchone()[0],'quarantined')
        objective=c.execute("select epistemic_status,valid_from,valid_to from semantic_assertions where id='a_objective'").fetchone()
        self.assertEqual(objective,('validated_extracted','1970-01-01T00:00:30+00:00',None))
        self.assertEqual(report['modes'],{'OBSERVATION':1,'NONFACTUAL':1,'CURRENT_STATE':1})


if __name__=='__main__': unittest.main(verbosity=2)
