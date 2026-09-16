#!/usr/bin/env python3
import json
import sqlite3
import unittest

import distillation_temporal_authority as ta


class TemporalClassificationTests(unittest.TestCase):
    def test_metric_and_outcome_are_historical_observations(self):
        for kind in ('metric','outcome'):
            d=ta.classify_temporal(kind,'project')
            self.assertEqual(d.mode,'OBSERVATION')
            self.assertTrue(d.auto_eligible)

    def test_proposals_and_adjacent_possibles_are_not_canonical_facts(self):
        for kind in ('proposal','adjacent_possible'):
            d=ta.classify_temporal(kind,'project')
            self.assertEqual(d.mode,'NONFACTUAL')
            self.assertFalse(d.auto_eligible)

    def test_principle_is_commitment_and_mutable_project_state_is_current(self):
        self.assertEqual(ta.classify_temporal('principle','enduring').mode,'COMMITMENT')
        self.assertEqual(ta.classify_temporal('bug','enduring').mode,'CURRENT_STATE')
        self.assertEqual(ta.classify_temporal('preference','enduring').mode,'CURRENT_STATE')
        self.assertEqual(ta.classify_temporal('constraint','project').mode,'CURRENT_STATE')
        self.assertEqual(ta.classify_temporal('constraint','enduring').mode,'COMMITMENT')

    def test_unknown_kind_requires_review(self):
        d=ta.classify_temporal('mystery','project')
        self.assertEqual(d.mode,'REVIEW')
        self.assertFalse(d.auto_eligible)


class EvidenceTimeTests(unittest.TestCase):
    def test_normalizes_unix_and_iso_timestamps(self):
        self.assertEqual(ta.normalize_timestamp(0),'1970-01-01T00:00:00+00:00')
        self.assertEqual(ta.normalize_timestamp('1970-01-01T00:00:01Z'),'1970-01-01T00:00:01+00:00')

    def test_uses_earliest_supporting_evidence_timestamp(self):
        c=sqlite3.connect(':memory:')
        c.execute('create table entities(id text primary key,metadata text,created_at text)')
        c.execute('insert into entities values(?,?,?)',('e1',json.dumps({'create_time':20}),'2026-01-01T00:00:00+00:00'))
        c.execute('insert into entities values(?,?,?)',('e2',json.dumps({'create_time':10}),'2026-01-01T00:00:00+00:00'))
        self.assertEqual(ta.evidence_observed_at(c,['e1','e2']),'1970-01-01T00:00:10+00:00')


class TemporalProfileTests(unittest.TestCase):
    def test_current_state_without_evidence_time_is_not_auto_eligible(self):
        c=sqlite3.connect(':memory:')
        c.execute('create table entities(id text primary key,metadata text,created_at text)')
        profile=ta.authority_profile(c,'objective','project',[])
        self.assertEqual(profile.mode,'CURRENT_STATE')
        self.assertFalse(profile.auto_eligible)
        self.assertIn('MISSING_OBSERVED_AT',profile.reasons)

    def test_observation_becomes_closed_historical_interval(self):
        c=sqlite3.connect(':memory:')
        c.execute('create table entities(id text primary key,metadata text,created_at text)')
        c.execute('insert into entities values(?,?,?)',('e',json.dumps({'create_time':10}),'2026-01-01T00:00:00+00:00'))
        profile=ta.authority_profile(c,'metric','project',['e'])
        fields=ta.assertion_fields(profile)
        self.assertEqual(fields['epistemic_status'],'historical_observation')
        self.assertEqual(fields['valid_from'],'1970-01-01T00:00:10+00:00')
        self.assertEqual(fields['valid_to'],fields['valid_from'])

    def test_current_state_is_open_interval(self):
        c=sqlite3.connect(':memory:')
        c.execute('create table entities(id text primary key,metadata text,created_at text)')
        c.execute('insert into entities values(?,?,?)',('e',json.dumps({'create_time':10}),'2026-01-01T00:00:00+00:00'))
        profile=ta.authority_profile(c,'decision','project',['e'])
        fields=ta.assertion_fields(profile)
        self.assertEqual(fields['epistemic_status'],'validated_extracted')
        self.assertEqual(fields['valid_from'],'1970-01-01T00:00:10+00:00')
        self.assertIsNone(fields['valid_to'])

    def test_nonfactual_existing_assertion_is_quarantined_not_deleted(self):
        profile=ta.TemporalProfile('NONFACTUAL',None,False,('NONFACTUAL_KIND',))
        fields=ta.existing_assertion_remediation_fields(profile,'2026-09-16T00:00:00+00:00')
        self.assertEqual(fields['epistemic_status'],'quarantined_nonfactual')
        self.assertEqual(fields['valid_to'],'2026-09-16T00:00:00+00:00')

    def test_only_exact_duplicate_is_superseded_for_nonfunctional_predicate(self):
        self.assertTrue(ta.should_supersede('has_objective','obj1','x','obj1','x'))
        self.assertFalse(ta.should_supersede('has_objective','obj1','x','obj2','y'))

    def test_functional_predicate_supersedes_changed_value(self):
        self.assertTrue(ta.should_supersede('preferred_language_style',None,'formal',None,'friendly'))


class TemporalAuthorityRecordTests(unittest.TestCase):

    def test_temporal_gate_forces_review_when_not_auto_eligible(self):
        self.assertEqual(ta.temporal_gate_override(ta.TemporalProfile('NONFACTUAL',None,False,('NONFACTUAL_KIND',))),'REVIEW')
        self.assertEqual(ta.temporal_gate_override(ta.TemporalProfile('CURRENT_STATE',None,False,('MISSING_OBSERVED_AT',))),'REVIEW')
        self.assertIsNone(ta.temporal_gate_override(ta.TemporalProfile('CURRENT_STATE','2026-09-16T00:00:00+00:00',True,())))
    def test_records_protocol_owned_temporal_authority(self):
        c=sqlite3.connect(':memory:')
        ta.ensure_temporal_schema(c)
        profile=ta.TemporalProfile('CURRENT_STATE','2026-09-16T00:00:00+00:00',True,())
        ta.record_temporal_authority(c,'cand1',profile,'2026-09-16T01:00:00+00:00')
        row=c.execute('select candidate_id,temporal_mode,observed_at,auto_eligible,reasons from distillation_temporal_authority').fetchone()
        self.assertEqual(row,('cand1','CURRENT_STATE','2026-09-16T00:00:00+00:00',1,'[]'))



class SupersessionLineageTests(unittest.TestCase):
    def _db(self):
        c=sqlite3.connect(':memory:')
        c.execute('create table semantic_assertions(id text primary key,subject_id text,predicate text,object_id text,literal_value text,epistemic_status text,source_ref text,valid_from text,valid_to text,supersedes text)')
        return c

    def test_same_fact_reaffirmation_forms_temporal_chain(self):
        c=self._db()
        rows=[('a3','2026-09-12T00:00:00+00:00'),('a1','2026-09-10T00:00:00+00:00'),('a2','2026-09-11T00:00:00+00:00')]
        for aid,ts in rows:
            c.execute("insert into semantic_assertions values(?,?,?,?,?,'validated_extracted',?,?,?,?)",(aid,'s','has_objective','o',None,'distillation://x',ts,None,None))
        ta.reconcile_lineages(c,'s','has_objective')
        got={r[0]:r[1:] for r in c.execute('select id,valid_to,supersedes from semantic_assertions')}
        self.assertEqual(got['a1'],('2026-09-11T00:00:00+00:00',None))
        self.assertEqual(got['a2'],('2026-09-12T00:00:00+00:00','a1'))
        self.assertEqual(got['a3'],(None,'a2'))

    def test_multivalued_predicate_keeps_distinct_objects_active(self):
        c=self._db()
        c.execute("insert into semantic_assertions values('a1','s','has_objective','o1',null,'validated_extracted','distillation://x','2026-09-10T00:00:00+00:00',null,null)")
        c.execute("insert into semantic_assertions values('a2','s','has_objective','o2',null,'validated_extracted','distillation://y','2026-09-11T00:00:00+00:00',null,null)")
        ta.reconcile_lineages(c,'s','has_objective')
        self.assertEqual(c.execute('select count(*) from semantic_assertions where valid_to is null').fetchone()[0],2)

    def test_functional_predicate_chains_changed_values(self):
        c=self._db()
        c.execute("insert into semantic_assertions values('a1','s','preferred_language_style',null,'formal','validated_extracted','distillation://x','2026-09-10T00:00:00+00:00',null,null)")
        c.execute("insert into semantic_assertions values('a2','s','preferred_language_style',null,'friendly','validated_extracted','distillation://y','2026-09-11T00:00:00+00:00',null,null)")
        ta.reconcile_lineages(c,'s','preferred_language_style')
        self.assertEqual(c.execute("select valid_to from semantic_assertions where id='a1'").fetchone()[0],'2026-09-11T00:00:00+00:00')
        self.assertEqual(c.execute("select supersedes from semantic_assertions where id='a2'").fetchone()[0],'a1')


class ActiveVisibilityTests(unittest.TestCase):
    def test_open_or_future_interval_is_active_and_closed_history_is_not(self):
        at='2026-09-16T05:00:00+00:00'
        self.assertTrue(ta.assertion_is_active(None,at))
        self.assertTrue(ta.assertion_is_active('2026-09-16T06:00:00+00:00',at))
        self.assertFalse(ta.assertion_is_active('2026-09-16T05:00:00+00:00',at))
        self.assertFalse(ta.assertion_is_active('2026-09-16T04:00:00+00:00',at))

if __name__=='__main__': unittest.main(verbosity=2)
