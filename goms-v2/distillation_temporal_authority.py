#!/usr/bin/env python3
from dataclasses import dataclass
from datetime import datetime, timezone
import json


@dataclass(frozen=True)
class TemporalDecision:
    mode: str
    auto_eligible: bool
    reason: str


def classify_temporal(canonical_kind, durability):
    kind=str(canonical_kind or '').strip().lower()
    durability=str(durability or '').strip().lower()
    if kind in {'metric','outcome'}:
        return TemporalDecision('OBSERVATION',True,'point-in-time result or measurement')
    if kind in {'proposal','adjacent_possible'}:
        return TemporalDecision('NONFACTUAL',False,'proposal or possibility is not canonical fact')
    if kind == 'principle':
        return TemporalDecision('COMMITMENT',True,'governing principle remains active until superseded')
    if kind in {'constraint','requirement'} and durability == 'enduring':
        return TemporalDecision('COMMITMENT',True,'enduring governing constraint or requirement')
    if kind in {'objective','decision','capability','task','bug','scarcity','preference','constraint','requirement'}:
        return TemporalDecision('CURRENT_STATE',True,'mutable state remains active until superseded or closed')
    return TemporalDecision('REVIEW',False,'temporal authority is not protocol-defined for this kind')


def normalize_timestamp(value):
    if value is None or value == '':
        return None
    if isinstance(value,(int,float)) or (isinstance(value,str) and value.strip().replace('.','',1).isdigit()):
        return datetime.fromtimestamp(float(value),tz=timezone.utc).isoformat()
    text=str(value).strip()
    if text.endswith('Z'):
        text=text[:-1]+'+00:00'
    dt=datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def evidence_observed_at(connection, evidence_ids):
    observed=[]
    for evidence_id in evidence_ids or ():
        row=connection.execute('select metadata,created_at from entities where id=?',(evidence_id,)).fetchone()
        if not row:
            continue
        metadata=row[0] if not hasattr(row,'keys') else row['metadata']
        created_at=row[1] if not hasattr(row,'keys') else row['created_at']
        try:
            meta=json.loads(metadata or '{}')
        except Exception:
            meta={}
        raw=meta.get('create_time') or meta.get('update_time') or created_at
        try:
            ts=normalize_timestamp(raw)
        except Exception:
            ts=None
        if ts:
            observed.append(ts)
    return min(observed) if observed else None


@dataclass(frozen=True)
class TemporalProfile:
    mode: str
    observed_at: str | None
    auto_eligible: bool
    reasons: tuple[str, ...]


def authority_profile(connection, canonical_kind, durability, evidence_ids):
    decision=classify_temporal(canonical_kind,durability)
    observed_at=evidence_observed_at(connection,evidence_ids)
    reasons=[]
    if decision.mode == 'NONFACTUAL':
        reasons.append('NONFACTUAL_KIND')
    elif decision.mode == 'REVIEW':
        reasons.append('TEMPORAL_AUTHORITY_UNDEFINED')
    if decision.auto_eligible and not observed_at:
        reasons.append('MISSING_OBSERVED_AT')
    return TemporalProfile(
        decision.mode,
        observed_at,
        bool(decision.auto_eligible and observed_at),
        tuple(reasons),
    )


def assertion_fields(profile):
    if not profile.auto_eligible or not profile.observed_at:
        raise ValueError('assertion is not temporally admissible for automatic promotion')
    if profile.mode == 'OBSERVATION':
        return {
            'epistemic_status':'historical_observation',
            'valid_from':profile.observed_at,
            'valid_to':profile.observed_at,
        }
    if profile.mode in {'CURRENT_STATE','COMMITMENT'}:
        return {
            'epistemic_status':'validated_extracted',
            'valid_from':profile.observed_at,
            'valid_to':None,
        }
    raise ValueError(f'unsupported temporal mode: {profile.mode}')


def existing_assertion_remediation_fields(profile, fallback_at):
    if profile.mode == 'NONFACTUAL':
        observed=profile.observed_at or fallback_at
        return {'epistemic_status':'quarantined_nonfactual','valid_from':observed,'valid_to':observed}
    if profile.mode == 'REVIEW' or not profile.auto_eligible:
        observed=profile.observed_at or fallback_at
        return {'epistemic_status':'authority_review','valid_from':observed,'valid_to':observed}
    return assertion_fields(profile)


_FUNCTIONAL_PREDICATES={
    'preferred_language_style','has_line_count','merged_into_main_ratio',
    'has_passed','has_failures','status','state','current_version','loaded','failed',
}


def should_supersede(predicate, old_object_id, old_literal, new_object_id, new_literal):
    if str(predicate or '').strip().lower() in _FUNCTIONAL_PREDICATES:
        return True
    return (old_object_id or None)==(new_object_id or None) and str(old_literal or '')==str(new_literal or '')


def ensure_temporal_schema(connection):
    connection.execute('''create table if not exists distillation_temporal_authority(
      candidate_id text primary key,
      temporal_mode text not null,
      observed_at text,
      auto_eligible integer not null,
      reasons text not null default '[]',
      checked_at text not null
    )''')


def record_temporal_authority(connection, candidate_id, profile, checked_at):
    ensure_temporal_schema(connection)
    connection.execute('''insert or replace into distillation_temporal_authority
      (candidate_id,temporal_mode,observed_at,auto_eligible,reasons,checked_at)
      values(?,?,?,?,?,?)''',(
        candidate_id,profile.mode,profile.observed_at,1 if profile.auto_eligible else 0,
        json.dumps(list(profile.reasons),sort_keys=True),checked_at,
    ))


def temporal_gate_override(profile):
    return None if profile.auto_eligible else 'REVIEW'


def _lineage_key(predicate, object_id, literal):
    pred=str(predicate or '').strip().lower()
    if pred in _FUNCTIONAL_PREDICATES:
        return ('functional',pred)
    return ('exact',pred,object_id or '',str(literal or ''))


def reconcile_lineages(connection, subject_id, predicate):
    rows=connection.execute('''select id,object_id,literal_value,valid_from
      from semantic_assertions
      where subject_id=? and predicate=?
        and epistemic_status='validated_extracted'
        and source_ref like 'distillation://%'
        and valid_from is not null
      order by valid_from,id''',(subject_id,predicate)).fetchall()
    groups={}
    for row in rows:
        rid,object_id,literal_value,valid_from=row[0],row[1],row[2],row[3]
        groups.setdefault(_lineage_key(predicate,object_id,literal_value),[]).append((rid,valid_from))
    for lineage in groups.values():
        lineage.sort(key=lambda x:(x[1],x[0]))
        for idx,(rid,_) in enumerate(lineage):
            previous=lineage[idx-1][0] if idx else None
            next_from=lineage[idx+1][1] if idx+1<len(lineage) else None
            connection.execute('update semantic_assertions set valid_to=?,supersedes=? where id=?',(next_from,previous,rid))
    return sum(len(v) for v in groups.values())


def assertion_is_active(valid_to, at):
    return valid_to is None or str(valid_to) > str(at)
