#!/usr/bin/env python3
from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata

from distillation_temporal_authority import TemporalProfile, _FUNCTIONAL_PREDICATES

LOW_COMPOSITE_CONFIDENCE='LOW_COMPOSITE_CONFIDENCE'
_BLOCKED_ENTITY_STATUSES={'deleted','removed','superseded','quarantined'}
_HARD_REVIEW_REASONS={
    'SUBJECT_IDENTITY_UNRESOLVED','OBJECT_IDENTITY_UNRESOLVED',
    'SUBJECT_DUPLICATE_EXISTING','OBJECT_DUPLICATE_EXISTING',
    'SUBJECT_DUPLICATE_AMBIGUOUS','OBJECT_DUPLICATE_AMBIGUOUS',
    'POTENTIAL_CONTRADICTION','STALE_STATE_UPDATE','AUTHORITY_CONFLICT',
    'SENTENCE_SHAPED_SUBJECT','SENTENCE_SHAPED_OBJECT',
    'SUBJECT_ENTITY_INACTIVE','OBJECT_ENTITY_INACTIVE',
}


def review_reason_for_score(score, threshold=0.88):
    return LOW_COMPOSITE_CONFIDENCE if float(score) < float(threshold) else None


def requires_hard_review(reasons):
    return any(str(reason) in _HARD_REVIEW_REASONS for reason in reasons or ())


def predicate_is_functional(predicate):
    return str(predicate or '').strip().lower() in _FUNCTIONAL_PREDICATES


def normalize_entity_title(value):
    text=unicodedata.normalize('NFKC',str(value or '')).casefold()
    return ' '.join(''.join(ch if ch.isalnum() else ' ' for ch in text).split())


def entity_is_rebindable(entity):
    status=str((entity or {}).get('status') or '').strip().lower()
    return status not in _BLOCKED_ENTITY_STATUSES


def unique_entity_match(entity_index, title, proposed_type=None):
    key=normalize_entity_title(title)
    if not key:
        return None
    hits=[e for e in entity_index.get(key,()) if entity_is_rebindable(e)]
    if len(hits) != 1:
        return None
    hit=hits[0]
    if proposed_type and str(hit.get('type') or '').strip().lower() != str(proposed_type).strip().lower():
        return None
    return hit


def _value(row,key):
    if hasattr(row,'keys'):
        return row[key] if key in row.keys() else None
    if hasattr(row,'get'):
        return row.get(key)
    return None


def _same_value(row, proposed_object_id, proposed_literal):
    old_object=_value(row,'object_id')
    old_literal=_value(row,'literal_value')
    if proposed_object_id or old_object:
        return (proposed_object_id or None)==(old_object or None)
    return str(proposed_literal or '').strip()==str(old_literal or '').strip()


def _safe_distillation_lineage_target(row):
    return (
        str(_value(row,'epistemic_status') or '') == 'validated_extracted'
        and str(_value(row,'source_ref') or '').startswith('distillation://')
        and bool(_value(row,'valid_from'))
    )


@dataclass(frozen=True)
class ConflictAssessment:
    contradiction_count: int
    reasons: tuple


def assess_existing_values(existing_assertions, predicate, proposed_object_id, proposed_literal,
                           temporal_profile: TemporalProfile):
    differing=[row for row in existing_assertions
               if not _same_value(row,proposed_object_id,proposed_literal)]
    if not differing or not predicate_is_functional(predicate):
        return ConflictAssessment(0,())
    if temporal_profile.mode == 'OBSERVATION':
        return ConflictAssessment(0,())
    if temporal_profile.mode == 'CURRENT_STATE' and temporal_profile.observed_at:
        if any(not _safe_distillation_lineage_target(row) for row in differing):
            return ConflictAssessment(len(differing),('AUTHORITY_CONFLICT',))
        newest=max(str(_value(row,'valid_from')) for row in differing)
        if str(temporal_profile.observed_at) > newest:
            return ConflictAssessment(0,('TEMPORAL_SUPERSESSION',))
        return ConflictAssessment(len(differing),('STALE_STATE_UPDATE',))
    return ConflictAssessment(len(differing),('POTENTIAL_CONTRADICTION',))


def _reasons(raw):
    if isinstance(raw,(list,tuple)):
        return [str(x) for x in raw]
    try:
        value=json.loads(raw or '[]')
        return [str(x) for x in value] if isinstance(value,list) else []
    except (TypeError,json.JSONDecodeError):
        return []


def gate_fingerprint(row):
    get=lambda key: _value(row,key)
    def fnum(value):
        return None if value is None else round(float(value),6)
    payload={
      'decision':get('decision'),'score':fnum(get('score')),
      'reasons':sorted(_reasons(get('reasons'))),
      'subject_resolution':get('subject_resolution'),'object_resolution':get('object_resolution'),
      'contradiction_count':int(get('contradiction_count') or 0),
      'canonical_kind':get('canonical_kind'),'predicate':get('predicate'),'literal':get('literal'),
      'confidence':fnum(get('confidence')),'rationale':get('rationale'),
      'subject_mode':get('subject_mode'),'subject_id':get('subject_id'),'subject_type':get('subject_type'),
      'subject_title':get('subject_title'),'object_mode':get('object_mode'),'object_id':get('object_id'),
      'object_type':get('object_type'),'object_title':get('object_title'),'status':get('status'),
    }
    raw=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()
