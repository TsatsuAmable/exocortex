#!/usr/bin/env python3
from dataclasses import dataclass

from distillation_temporal_authority import TemporalProfile, _FUNCTIONAL_PREDICATES

LOW_COMPOSITE_CONFIDENCE='LOW_COMPOSITE_CONFIDENCE'


def review_reason_for_score(score, threshold=0.88):
    return LOW_COMPOSITE_CONFIDENCE if float(score) < float(threshold) else None


def predicate_is_functional(predicate):
    return str(predicate or '').strip().lower() in _FUNCTIONAL_PREDICATES


def _same_value(row, proposed_object_id, proposed_literal):
    old_object=row.get('object_id') if hasattr(row,'get') else row['object_id']
    old_literal=row.get('literal_value') if hasattr(row,'get') else row['literal_value']
    if proposed_object_id or old_object:
        return (proposed_object_id or None)==(old_object or None)
    return str(proposed_literal or '').strip()==str(old_literal or '').strip()


@dataclass(frozen=True)
class ConflictAssessment:
    contradiction_count: int
    reasons: tuple[str, ...]


def assess_existing_values(existing_assertions, predicate, proposed_object_id, proposed_literal,
                           temporal_profile: TemporalProfile):
    differing=[row for row in existing_assertions
               if not _same_value(row,proposed_object_id,proposed_literal)]
    if not differing or not predicate_is_functional(predicate):
        return ConflictAssessment(0,())
    if temporal_profile.mode == 'OBSERVATION':
        return ConflictAssessment(0,())
    if temporal_profile.mode == 'CURRENT_STATE' and temporal_profile.observed_at:
        newest=max((str((r.get('valid_from') if hasattr(r,'get') else r['valid_from']) or '')
                    for r in differing),default='')
        if not newest or str(temporal_profile.observed_at) > newest:
            return ConflictAssessment(0,('TEMPORAL_SUPERSESSION',))
        return ConflictAssessment(len(differing),('STALE_STATE_UPDATE',))
    return ConflictAssessment(len(differing),('POTENTIAL_CONTRADICTION',))
