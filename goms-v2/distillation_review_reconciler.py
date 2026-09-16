#!/usr/bin/env python3
from contextlib import closing
from collections import Counter
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"


def now():
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(connection):
    connection.executescript('''
      create table if not exists distillation_review_adjudications(
        candidate_id text not null,
        gate_fingerprint text not null,
        gate_checked_at text not null,
        action text not null,
        reason text not null,
        before_state text not null default '{}',
        after_state text not null default '{}',
        adjudicated_at text not null,
        primary key(candidate_id,gate_fingerprint)
      );
      create index if not exists idx_dist_review_adjudications_action
        on distillation_review_adjudications(action,adjudicated_at);
    ''')


def _proposal_state(row):
    keys=('candidate_id','subject_mode','subject_id','subject_type','subject_title',
          'object_mode','object_id','object_type','object_title','status')
    return {k:row[k] for k in keys if k in row.keys()}


def _reasons(raw):
    try:
        value=json.loads(raw or '[]')
        return [str(x) for x in value] if isinstance(value,list) else []
    except (TypeError,json.JSONDecodeError):
        return []


def _gate_fingerprint(row):
    payload={
      'decision':row['decision'],'score':round(float(row['score'] or 0),6),
      'reasons':sorted(_reasons(row['reasons'])),
      'subject_resolution':row['subject_resolution'],'object_resolution':row['object_resolution'],
      'contradiction_count':int(row['contradiction_count'] or 0),
      'subject_mode':row['subject_mode'],'subject_id':row['subject_id'],'subject_title':row['subject_title'],
      'object_mode':row['object_mode'],'object_id':row['object_id'],'object_title':row['object_title'],
      'status':row['status'],
    }
    raw=json.dumps(payload,sort_keys=True,separators=(',',':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def _action(row):
    reasons=_reasons(row['reasons'])
    if 'NONFACTUAL_KIND' in reasons:
        return 'QUARANTINE_NONFACTUAL','NONFACTUAL_KIND'
    can_rebind=(row['subject_resolution'] and row['subject_mode']=='new') or (
        row['object_resolution'] and row['object_mode']=='new')
    if can_rebind:
        return 'REBIND_ENTITY','EXACT_CANONICAL_ENTITY_MATCH'
    return 'HOLD',(reasons[0] if reasons else 'UNCLASSIFIED_REVIEW')



def unadjudicated_review_count(connection):
    ensure_schema(connection)
    connection.row_factory=sqlite3.Row
    seen={(r[0],r[1]) for r in connection.execute(
        'select candidate_id,gate_fingerprint from distillation_review_adjudications').fetchall()}
    rows=connection.execute('''
      select p.*,g.decision,g.score,g.reasons,g.subject_resolution,g.object_resolution,
             g.contradiction_count,g.checked_at gate_checked_at
      from distillation_reconciliation_proposals p
      join distillation_promotion_gate g on g.candidate_id=p.candidate_id
      where p.status='candidate' and g.decision='REVIEW'
    ''').fetchall()
    return sum(1 for row in rows if (row['candidate_id'],_gate_fingerprint(row)) not in seen)

def reconcile_review_batch(connection, limit=50, observed_at=None):
    ensure_schema(connection)
    ts=observed_at or now()
    connection.row_factory=sqlite3.Row
    rows=connection.execute('''
      select p.*,g.decision,g.score,g.reasons,g.subject_resolution,g.object_resolution,
             g.contradiction_count,g.checked_at gate_checked_at
      from distillation_reconciliation_proposals p
      join distillation_promotion_gate g on g.candidate_id=p.candidate_id
      where p.status='candidate' and g.decision='REVIEW'
      order by g.checked_at,p.candidate_id
    ''').fetchall()
    counts=Counter()
    processed=0
    for row in rows:
        if processed >= max(1,int(limit)):
            break
        fingerprint=_gate_fingerprint(row)
        if connection.execute('''select 1 from distillation_review_adjudications
             where candidate_id=? and gate_fingerprint=?''',
             (row['candidate_id'],fingerprint)).fetchone():
            continue
        before=_proposal_state(row)
        action,reason=_action(row)
        if action=='REBIND_ENTITY':
            if row['subject_resolution'] and row['subject_mode']=='new':
                connection.execute('''update distillation_reconciliation_proposals
                    set subject_mode='existing',subject_id=? where candidate_id=?''',
                    (row['subject_resolution'],row['candidate_id']))
            if row['object_resolution'] and row['object_mode']=='new':
                connection.execute('''update distillation_reconciliation_proposals
                    set object_mode='existing',object_id=? where candidate_id=?''',
                    (row['object_resolution'],row['candidate_id']))
            after_row=connection.execute('select * from distillation_reconciliation_proposals where candidate_id=?',
                                         (row['candidate_id'],)).fetchone()
            after=_proposal_state(after_row)
            connection.execute('delete from distillation_promotion_gate where candidate_id=?',(row['candidate_id'],))
            connection.execute('delete from distillation_graphshape_reviews where candidate_id=?',(row['candidate_id'],))
        elif action=='QUARANTINE_NONFACTUAL':
            connection.execute("update distillation_reconciliation_proposals set status='quarantined' where candidate_id=?",
                               (row['candidate_id'],))
            after_row=connection.execute('select * from distillation_reconciliation_proposals where candidate_id=?',
                                         (row['candidate_id'],)).fetchone()
            after=_proposal_state(after_row)
        else:
            after=before
        connection.execute('''insert into distillation_review_adjudications
          (candidate_id,gate_fingerprint,gate_checked_at,action,reason,before_state,after_state,adjudicated_at)
          values(?,?,?,?,?,?,?,?)''',(
            row['candidate_id'],fingerprint,row['gate_checked_at'],action,reason,
            json.dumps(before,sort_keys=True),json.dumps(after,sort_keys=True),ts))
        counts[action]+=1
        processed+=1
    connection.commit()
    return {'processed':processed,'actions':dict(sorted(counts.items()))}


def main():
    from distillation_review_surface import build_review_summary, publish_review_surface
    with closing(sqlite3.connect(DB)) as c:
        result=reconcile_review_batch(c,limit=100)
        summary=build_review_summary(c)
        publish_review_surface(c,summary)
        print(json.dumps({**result,'review_summary':summary},sort_keys=True))


if __name__=='__main__':
    main()
