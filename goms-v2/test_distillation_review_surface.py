#!/usr/bin/env python3
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from alerts import AlertService
from control_intents import ControlIntentService
from goms_store import GomsStore
import distillation_review_surface as surface


def add_review(c,cid,reasons,score=.85,subject='User',predicate='p',obj='Thing',created='2026-09-01T00:00:00Z'):
    c.execute('''insert into distillation_reconciliation_proposals(
      candidate_id,subject_title,predicate,object_title,status,created_at)
      values(?,?,?,?,?,?)''',(cid,subject,predicate,obj,'candidate',created))
    c.execute('''insert into distillation_promotion_gate(
      candidate_id,decision,score,reasons,contradiction_count,checked_at)
      values(?,?,?,?,0,?)''',(cid,'REVIEW',score,json.dumps(reasons),'2026-09-16T00:00:00Z'))


class ReviewSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='review-surface-')
        self.root=Path(self.tmp.name)
        self.store=GomsStore(self.root)
        self.db=self.root/'goms.sqlite3'

    def tearDown(self): self.tmp.cleanup()

    def test_summary_clusters_residue_and_limits_examples(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            add_review(c,'low1',['LOW_COMPOSITE_CONFIDENCE'])
            add_review(c,'low2',['LOW_COMPOSITE_CONFIDENCE'])
            add_review(c,'low3',['LOW_COMPOSITE_CONFIDENCE'])
            add_review(c,'id1',['SUBJECT_IDENTITY_UNRESOLVED','LOW_COMPOSITE_CONFIDENCE'])
            add_review(c,'shape1',['SENTENCE_SHAPED_OBJECT','LOW_COMPOSITE_CONFIDENCE'])
            summary=surface.build_review_summary(c,examples_per_cohort=2)
        self.assertEqual(summary['total'],5)
        counts={x['cohort']:x['count'] for x in summary['cohorts']}
        self.assertEqual(counts,{'IDENTITY_UNRESOLVED':1,'GRAPH_SHAPE':1,'LOW_CONFIDENCE':3})
        low=next(x for x in summary['cohorts'] if x['cohort']=='LOW_CONFIDENCE')
        self.assertEqual(len(low['examples']),2)
        self.assertEqual(summary['oldest'],'2026-09-01T00:00:00Z')

    def test_publish_is_single_resource_without_passive_attention_alert(self):
        summary={'total':7,'oldest':'2026-09-01T00:00:00Z','cohorts':[{'cohort':'LOW_CONFIDENCE','count':7,'examples':[]}]}
        with closing(sqlite3.connect(self.db)) as c, c:
            surface.publish_review_surface(c,summary,observed_at='2026-09-16T00:00:00Z')
            surface.publish_review_surface(c,summary,observed_at='2026-09-16T00:01:00Z')
            self.assertEqual(c.execute("select count(*) from resources where kind='AuthorityReviewQueue'").fetchone()[0],1)
            self.assertEqual(c.execute("select count(*) from attention_items where source='AuthorityReviewController' and status='open'").fetchone()[0],0)

    def test_publish_resolves_all_legacy_controller_attention_and_alerts(self):
        ts='2026-09-16T00:00:00+00:00'
        with self.store.connect() as c:
            c.execute('''insert into attention_items(
              id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              values('legacy-review','review','warning','Legacy review','Passive backlog','open','[]',
                     'AuthorityReviewController',?,?)''',(ts,ts))
        intent_id=ControlIntentService(self.root).ensure_for_attention('legacy-review')
        alert=AlertService(self.root,clock=lambda: datetime(2026,9,16,tzinfo=timezone.utc)).reconcile_intent(intent_id)
        self.assertEqual(alert['severity'],'ACTION_REQUIRED')
        with closing(sqlite3.connect(self.db)) as c, c:
            surface.publish_review_surface(c,{'total':1,'oldest':ts,'cohorts':[]},observed_at=ts)
            self.assertEqual(c.execute("select status from attention_items where id='legacy-review'").fetchone()[0],'resolved')
            state,severity=c.execute("select state,severity from alerts where id=?",(alert['id'],)).fetchone()
            self.assertEqual((state,severity),('RESOLVED','ACTION_REQUIRED'))

    def test_surface_dirty_when_missing_stale_or_review_count_changes(self):
        summary={'total':0,'oldest':None,'cohorts':[]}
        with closing(sqlite3.connect(self.db)) as c, c:
            self.assertTrue(surface.review_surface_needs_refresh(
                c,observed_at='2026-09-16T00:00:00+00:00',max_age_seconds=300))
            surface.publish_review_surface(c,summary,observed_at='2026-09-16T00:00:00+00:00')
            self.assertFalse(surface.review_surface_needs_refresh(
                c,observed_at='2026-09-16T00:04:59+00:00',max_age_seconds=300))
            add_review(c,'new-review',['LOW_COMPOSITE_CONFIDENCE'])
            self.assertTrue(surface.review_surface_needs_refresh(
                c,observed_at='2026-09-16T00:04:59+00:00',max_age_seconds=300))
            surface.publish_review_surface(c,surface.build_review_summary(c),
                                           observed_at='2026-09-16T00:04:59+00:00')
            self.assertTrue(surface.review_surface_needs_refresh(
                c,observed_at='2026-09-16T00:10:00+00:00',max_age_seconds=300))


if __name__=='__main__': unittest.main(verbosity=2)
