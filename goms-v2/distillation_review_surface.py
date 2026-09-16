#!/usr/bin/env python3
from contextlib import closing
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
RESOURCE_KIND='AuthorityReviewQueue'
RESOURCE_NAME='Canonical authority review queue'
RESOURCE_ID='res_'+hashlib.sha256((RESOURCE_KIND+'|'+RESOURCE_NAME).encode()).hexdigest()[:20]
ATTENTION_ID='attn_'+hashlib.sha256(('AuthorityReviewController|'+RESOURCE_NAME).encode()).hexdigest()[:24]
COHORT_PRIORITY=('IDENTITY_UNRESOLVED','TEMPORAL_UNDEFINED','GRAPH_SHAPE','LOW_CONFIDENCE','OTHER')


def now(): return datetime.now(timezone.utc).isoformat()


def _reasons(raw):
    try:
        value=json.loads(raw or '[]')
        return [str(x) for x in value] if isinstance(value,list) else []
    except (TypeError,json.JSONDecodeError):
        return []


def cohort_for(reasons):
    r=set(reasons)
    if r & {'SUBJECT_IDENTITY_UNRESOLVED','OBJECT_IDENTITY_UNRESOLVED',
            'SUBJECT_DUPLICATE_AMBIGUOUS','OBJECT_DUPLICATE_AMBIGUOUS'}:
        return 'IDENTITY_UNRESOLVED'
    if 'TEMPORAL_AUTHORITY_UNDEFINED' in r or 'AUTHORITY_CONFLICT' in r or 'STALE_STATE_UPDATE' in r:
        return 'TEMPORAL_UNDEFINED'
    if r & {'SENTENCE_SHAPED_SUBJECT','SENTENCE_SHAPED_OBJECT'}:
        return 'GRAPH_SHAPE'
    if 'LOW_COMPOSITE_CONFIDENCE' in r:
        return 'LOW_CONFIDENCE'
    return 'OTHER'


def build_review_summary(connection, examples_per_cohort=2):
    connection.row_factory=sqlite3.Row
    rows=connection.execute('''
      select p.candidate_id,p.subject_title,p.predicate,p.object_title,p.literal,p.created_at,
             g.score,g.reasons
      from distillation_reconciliation_proposals p
      join distillation_promotion_gate g on g.candidate_id=p.candidate_id
      where p.status='candidate' and g.decision='REVIEW'
      order by p.created_at,p.candidate_id
    ''').fetchall()
    groups={name:[] for name in COHORT_PRIORITY}
    for row in rows:
        groups[cohort_for(_reasons(row['reasons']))].append(row)
    cohorts=[]; limit=max(0,int(examples_per_cohort))
    for name in COHORT_PRIORITY:
        items=groups[name]
        if not items: continue
        examples=[{'candidate_id':row['candidate_id'],'subject':row['subject_title'],
                   'predicate':row['predicate'],'object':row['object_title'] or row['literal'],
                   'score':round(float(row['score'] or 0),3)} for row in items[:limit]]
        cohorts.append({'cohort':name,'count':len(items),'examples':examples})
    oldest=min((r['created_at'] for r in rows if r['created_at']),default=None)
    return {'total':len(rows),'oldest':oldest,'cohorts':cohorts}


def _parse_time(value):
    if not value:
        return None
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def review_surface_needs_refresh(connection, observed_at=None, max_age_seconds=300):
    connection.row_factory=sqlite3.Row
    review_count=connection.execute('''select count(*) from distillation_reconciliation_proposals p
      join distillation_promotion_gate g on g.candidate_id=p.candidate_id
      where p.status='candidate' and g.decision='REVIEW' ''').fetchone()[0]
    latest=connection.execute('''select max(g.checked_at) from distillation_reconciliation_proposals p
      join distillation_promotion_gate g on g.candidate_id=p.candidate_id
      where p.status='candidate' and g.decision='REVIEW' ''').fetchone()[0]
    resource=connection.execute('select status from resources where id=?',(RESOURCE_ID,)).fetchone()
    legacy=connection.execute("select 1 from attention_items where source='AuthorityReviewController' and status='open' limit 1").fetchone()
    if legacy or not resource:
        return True
    try: status=json.loads(resource['status'] or '{}')
    except (TypeError,json.JSONDecodeError): return True
    if int(status.get('review_count') or 0) != int(review_count):
        return True
    published=status.get('last_observed')
    if latest and (not published or str(latest) > str(published)):
        return True
    now_dt=_parse_time(observed_at) or datetime.now(timezone.utc)
    published_dt=_parse_time(published)
    return published_dt is None or (now_dt-published_dt).total_seconds() >= max(0,int(max_age_seconds))


def review_surface_dirty(connection):
    return review_surface_needs_refresh(connection)


def publish_review_surface(connection, summary, observed_at=None):
    ts=observed_at or now(); total=int(summary.get('total') or 0)
    status={'observed_state':'review_required' if total else 'healthy',
            'review_count':total,'summary':summary,'last_observed':ts}
    spec={'desired_state':'healthy','policy':'protocol_owned_review','surface':'manfred_cohorts'}
    spec_json=json.dumps(spec,sort_keys=True)
    row=connection.execute('select generation,spec,created_at from resources where id=?',(RESOURCE_ID,)).fetchone()
    generation=1 if not row else int(row[0])+(1 if row[1]!=spec_json else 0)
    created_at=ts if not row else row[2]
    connection.execute('''insert into resources(id,kind,name,spec,status,generation,observed_generation,
      controller,authority,metadata,created_at,updated_at)
      values(?,?,?,?,?,?,?,'AuthorityReviewController','system','{}',?,?)
      on conflict(id) do update set spec=excluded.spec,status=excluded.status,
      generation=excluded.generation,observed_generation=excluded.observed_generation,
      controller=excluded.controller,updated_at=excluded.updated_at''',
      (RESOURCE_ID,RESOURCE_KIND,RESOURCE_NAME,spec_json,json.dumps(status,sort_keys=True),generation,generation,created_at,ts))
    connection.execute('''insert into resource_conditions(resource_id,condition_type,status,reason,message,severity,observed_at)
      values(?,?,?,?,?,?,?) on conflict(resource_id,condition_type) do update set
      status=excluded.status,reason=excluded.reason,message=excluded.message,
      severity=excluded.severity,observed_at=excluded.observed_at''',
      (RESOURCE_ID,'ReviewDrained','True' if not total else 'False',
       'QueueDrained' if not total else 'HumanReviewResidue',
       f'canonical authority review held={total}','info',ts))
    connection.execute("update attention_items set status='resolved',updated_at=? where source='AuthorityReviewController' and status='open'",(ts,))
    connection.execute('''update alerts set state='RESOLVED',resolved_at=?,
      resolution_reason='source_cleared',updated_at=? where state!='RESOLVED' and intent_id in (
        select aci.intent_id from attention_control_intents aci
        join attention_items ai on ai.id=aci.attention_id
        where ai.source='AuthorityReviewController' and ai.status='resolved')''',(ts,ts))
    connection.commit(); return RESOURCE_ID


def main():
    with closing(sqlite3.connect(DB)) as c:
        summary=build_review_summary(c)
        rid=publish_review_surface(c,summary)
        print(json.dumps({'resource_id':rid,'summary':summary},sort_keys=True))


if __name__=='__main__': main()
