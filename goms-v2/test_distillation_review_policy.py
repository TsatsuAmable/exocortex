#!/usr/bin/env python3
import unittest

from distillation_temporal_authority import TemporalProfile
from distillation_review_policy import (
    LOW_COMPOSITE_CONFIDENCE,
    assess_existing_values,
    review_reason_for_score,
    requires_hard_review,
)


def extracted(value, valid_from='2026-09-15T00:00:00+00:00'):
    return {
        'object_id': None,
        'literal_value': value,
        'valid_from': valid_from,
        'epistemic_status': 'validated_extracted',
        'source_ref': 'distillation://old',
    }


class ReviewPolicyTests(unittest.TestCase):
    def test_score_only_review_is_explainable(self):
        self.assertEqual(review_reason_for_score(0.87), LOW_COMPOSITE_CONFIDENCE)
        self.assertIsNone(review_reason_for_score(0.88))

    def test_multivalued_relation_is_not_a_contradiction(self):
        existing=[{'object_id':'obj_old','literal_value':None,'valid_from':None,
                   'epistemic_status':'explicit','source_ref':'human://x'}]
        profile=TemporalProfile('CURRENT_STATE','2026-09-16T00:00:00+00:00',True,())
        result=assess_existing_values(existing,'has_objective','obj_new',None,profile)
        self.assertEqual(result.contradiction_count,0)
        self.assertEqual(result.reasons,())

    def test_newer_functional_distillation_state_is_safe_supersession(self):
        existing=[extracted('failed')]
        profile=TemporalProfile('CURRENT_STATE','2026-09-16T00:00:00+00:00',True,())
        result=assess_existing_values(existing,'status',None,'passed',profile)
        self.assertEqual(result.contradiction_count,0)
        self.assertEqual(result.reasons,('TEMPORAL_SUPERSESSION',))

    def test_explicit_functional_state_requires_authority_review(self):
        existing=[{'object_id':None,'literal_value':'human-set','valid_from':'2026-09-15T00:00:00+00:00',
                   'epistemic_status':'explicit','source_ref':'human://decision'}]
        profile=TemporalProfile('CURRENT_STATE','2026-09-16T00:00:00+00:00',True,())
        result=assess_existing_values(existing,'status',None,'model-set',profile)
        self.assertEqual(result.contradiction_count,1)
        self.assertEqual(result.reasons,('AUTHORITY_CONFLICT',))
        self.assertTrue(requires_hard_review(result.reasons))

    def test_legacy_functional_state_without_valid_from_requires_authority_review(self):
        existing=[extracted('old',valid_from=None)]
        profile=TemporalProfile('CURRENT_STATE','2026-09-16T00:00:00+00:00',True,())
        result=assess_existing_values(existing,'status',None,'new',profile)
        self.assertEqual(result.contradiction_count,1)
        self.assertEqual(result.reasons,('AUTHORITY_CONFLICT',))

    def test_exact_duplicate_reason_is_hard_review_regardless_of_score(self):
        self.assertTrue(requires_hard_review(('SUBJECT_DUPLICATE_EXISTING',)))
        self.assertTrue(requires_hard_review(('OBJECT_DUPLICATE_EXISTING',)))
        self.assertTrue(requires_hard_review(('SUBJECT_DUPLICATE_AMBIGUOUS',)))

    def test_stale_functional_state_requires_review(self):
        existing=[extracted('passed',valid_from='2026-09-16T00:00:00+00:00')]
        profile=TemporalProfile('CURRENT_STATE','2026-09-15T00:00:00+00:00',True,())
        result=assess_existing_values(existing,'status',None,'failed',profile)
        self.assertEqual(result.contradiction_count,1)
        self.assertEqual(result.reasons,('STALE_STATE_UPDATE',))


if __name__=='__main__':
    unittest.main(verbosity=2)
