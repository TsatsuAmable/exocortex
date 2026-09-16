#!/usr/bin/env python3
import unittest

from distillation_temporal_authority import TemporalProfile
from distillation_review_policy import (
    LOW_COMPOSITE_CONFIDENCE,
    assess_existing_values,
    review_reason_for_score,
)


class ReviewPolicyTests(unittest.TestCase):
    def test_score_only_review_is_explainable(self):
        self.assertEqual(review_reason_for_score(0.87), LOW_COMPOSITE_CONFIDENCE)
        self.assertIsNone(review_reason_for_score(0.88))

    def test_multivalued_relation_is_not_a_contradiction(self):
        existing=[{'object_id':'obj_old','literal_value':None,'valid_from':'2026-09-01T00:00:00+00:00'}]
        profile=TemporalProfile('CURRENT_STATE','2026-09-16T00:00:00+00:00',True,())
        result=assess_existing_values(existing,'has_objective','obj_new',None,profile)
        self.assertEqual(result.contradiction_count,0)
        self.assertEqual(result.reasons,())

    def test_newer_functional_state_is_supersession_not_contradiction(self):
        existing=[{'object_id':None,'literal_value':'failed','valid_from':'2026-09-15T00:00:00+00:00'}]
        profile=TemporalProfile('CURRENT_STATE','2026-09-16T00:00:00+00:00',True,())
        result=assess_existing_values(existing,'status',None,'passed',profile)
        self.assertEqual(result.contradiction_count,0)
        self.assertEqual(result.reasons,('TEMPORAL_SUPERSESSION',))

    def test_stale_functional_state_requires_review(self):
        existing=[{'object_id':None,'literal_value':'passed','valid_from':'2026-09-16T00:00:00+00:00'}]
        profile=TemporalProfile('CURRENT_STATE','2026-09-15T00:00:00+00:00',True,())
        result=assess_existing_values(existing,'status',None,'failed',profile)
        self.assertEqual(result.contradiction_count,1)
        self.assertEqual(result.reasons,('STALE_STATE_UPDATE',))


if __name__=='__main__':
    unittest.main(verbosity=2)
