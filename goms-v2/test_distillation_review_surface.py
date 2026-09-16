#!/usr/bin/env python3
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

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

    def test_publish_is_single_resource_and_single_attention(self):
        summary={'total':7,'oldest':'2026-09-01T00:00:00Z','cohorts':[{'cohort':'LOW_CONFIDENCE','count':7,'examples':[]}]}
        with closing(sqlite3.connect(self.db)) as c, c:
            surface.publish_review_surface(c,summary,observed_at='2026-09-16T00:00:00Z')
            surface.publish_review_surface(c,summary,observed_at='2026-09-16T00:01:00Z')
            self.assertEqual(c.execute("select count(*) from resources where kind='AuthorityReviewQueue'").fetchone()[0],1)
            self.assertEqual(c.execute("select count(*) from attention_items where source='AuthorityReviewController' and status='open'").fetchone()[0],1)


if __name__=='__main__': unittest.main(verbosity=2)
