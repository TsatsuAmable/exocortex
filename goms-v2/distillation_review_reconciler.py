#!/usr/bin/env python3
from contextlib import closing
from collections import Counter, defaultdict
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from distillation_review_policy import gate_fingerprint, normalize_entity_title, unique_entity_match

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"


def now():
    return datetime.now(timezone.utc).isoformat()


def _table_columns(connection, table):
    return {row[1] for row in connection.execute('pragma table_info(%s)' % table).fetchall()}


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
    if 'gate_fingerprint' not in _table_columns(connection,'distillation_promotion_gate'):
        connection.execute('alter table distillation_promotion_gate add column gate_fingerprint text')
    connection.executescript('''
      drop trigger if exists distillation_review_proposal_fingerprint_dirty;
      create trigger distillation_review_proposal_fingerprint_dirty
      after update of canonical_kind,subject_mode,subject_id,subject_type,subject_title,
                      predicate,object_mode,object_id,object_type,object_title,literal,confidence,rationale
      on distillation_reconciliation_proposals
      begin
        update distillation_promotion_gate set gate_fingerprint=null where candidate_id=new.candidate_id;
        delete from distillation_graphshape_reviews where candidate_id=new.candidate_id;
      end;
    ''')


def _proposal_state(row):
    keys=('candidate_id','canonical_kind','subject_mode','subject_id','subject_type','subject_title',
          'predicate','object_mode','object_id','object_type','object_title','literal',
          'confidence','rationale','status','created_at')
    return {k:row[k] for k in keys if k in row.keys()}


def _reasons(raw):
    try:
        value=json.loads(raw or '[]')
        return [str(x) for x in value] if isinstance(value,list) else []
    except (TypeError,json.JSONDecodeError):
        return []


def _entity_index(connection):
    groups=defaultdict(list)
    try:
        rows=connection.execute("select id,type,title,status from entities where type not in ('evidence','source')").fetchall()
    except sqlite3.OperationalError:
        rows=[]
    for row in rows:
        item=dict(row) if hasattr(row,'keys') else {'id':row[0],'type':row[1],'title':row[2],'status':row[3]}
        key=normalize_entity_title(item.get('title'))
        if key:
            groups[key].append(item)
    return groups


def _resolution_is_current_unique(entity_index, resolution_id, title, entity_type):
    if not resolution_id:
        return False
    match=unique_entity_match(entity_index,title,entity_type)
    return bool(match and match.get('id') == resolution_id)


def _action(row, entity_index):
    reasons=_reasons(row['reasons'])
    if 'NONFACTUAL_KIND' in reasons:
        return 'QUARANTINE_NONFACTUAL','NONFACTUAL_KIND'
    subject_requested=bool(row['subject_resolution'] and row['subject_mode']=='new')
    object_requested=bool(row['object_resolution'] and row['object_mode']=='new')
    if subject_requested and not _resolution_is_current_unique(
            entity_index,row['subject_resolution'],row['subject_title'],row['subject_type']):
        return 'HOLD','STALE_OR_AMBIGUOUS_ENTITY_RESOLUTION'
    if object_requested and not _resolution_is_current_unique(
            entity_index,row['object_resolution'],row['object_title'],row['object_type']):
        return 'HOLD','STALE_OR_AMBIGUOUS_ENTITY_RESOLUTION'
    if subject_requested or object_requested:
        return 'REBIND_ENTITY','EXACT_CANONICAL_ENTITY_MATCH'
    return 'HOLD',(reasons[0] if reasons else 'UNCLASSIFIED_REVIEW')


def _review_select_sql(select_one=False):
    selected='1' if select_one else '''p.*,g.decision,g.score,g.reasons,g.subject_resolution,g.object_resolution,
             g.contradiction_count,g.checked_at gate_checked_at,g.gate_fingerprint'''
    return f'''select {selected}
      from distillation_reconciliation_proposals p
      join distillation_promotion_gate g on g.candidate_id=p.candidate_id
      left join distillation_review_adjudications a
        on a.candidate_id=p.candidate_id and a.gate_fingerprint=g.gate_fingerprint
      where p.status='candidate' and g.decision='REVIEW'
        and g.gate_fingerprint is not null and a.candidate_id is null
      order by g.checked_at,p.candidate_id'''


def unadjudicated_review_count(connection):
    ensure_schema(connection)
    row=connection.execute(_review_select_sql(select_one=True)+' limit 1').fetchone()
    return 1 if row else 0


def _persisted_fingerprint(connection,row):
    fingerprint=row['gate_fingerprint'] if 'gate_fingerprint' in row.keys() else None
    if not fingerprint:
        raise ValueError('review gate requires re-gating before adjudication')
    return fingerprint


def reconcile_review_batch(connection, limit=50, observed_at=None):
    ensure_schema(connection)
    ts=observed_at or now()
    connection.row_factory=sqlite3.Row
    bounded=max(1,int(limit))
    rows=connection.execute(_review_select_sql()+ ' limit ?', (bounded*4,)).fetchall()
    entity_index=_entity_index(connection)
    counts=Counter(); processed=0
    for row in rows:
        if processed >= bounded:
            break
        fingerprint=_persisted_fingerprint(connection,row)
        if connection.execute('''select 1 from distillation_review_adjudications
             where candidate_id=? and gate_fingerprint=?''',
             (row['candidate_id'],fingerprint)).fetchone():
            continue
        before=_proposal_state(row)
        action,reason=_action(row,entity_index)
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
        counts[action]+=1; processed+=1
    connection.commit()
    return {'processed':processed,'actions':dict(sorted(counts.items()))}


def main():
    with closing(sqlite3.connect(DB)) as c:
        result=reconcile_review_batch(c,limit=100)
        print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()
