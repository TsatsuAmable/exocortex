#!/usr/bin/env python3
import argparse
from contextlib import closing
from collections import Counter
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path

from distillation_temporal_authority import (
    authority_profile,
    existing_assertion_remediation_fields,
    reconcile_lineages,
)

DEFAULT_DB=Path.home()/"Library/Application Support/Aineko/GOMS/goms.sqlite3"


def now():
    return datetime.now(timezone.utc).isoformat()


def migrate(connection, migration_at, apply=False):
    old_factory=connection.row_factory
    connection.row_factory=sqlite3.Row
    rows=connection.execute('''
      select a.*,p.candidate_id,p.canonical_kind,p.status proposal_status,
             v.durability,d.evidence_ids
      from semantic_assertions a
      join distillation_reconciliation_proposals p
        on a.source_ref='distillation://'||p.candidate_id
      join distillation_candidates d on d.id=p.candidate_id
      join distillation_validations v on v.candidate_id=p.candidate_id
      order by a.created_at,a.id
    ''').fetchall()
    modes=Counter()
    quarantined=0
    historical=0
    updated=0
    lineages=set()
    for row in rows:
        try:
            evidence=json.loads(row['evidence_ids'] or '[]')
        except Exception:
            evidence=[]
        profile=authority_profile(connection,row['canonical_kind'],row['durability'],evidence)
        fields=existing_assertion_remediation_fields(profile,row['created_at'] or migration_at)
        try:
            metadata=json.loads(row['metadata'] or '{}')
        except Exception:
            metadata={}
        metadata.update({
            'temporal_mode':profile.mode,
            'observed_at':profile.observed_at,
            'temporal_authority_reasons':list(profile.reasons),
            'authority_status':'admissible' if profile.auto_eligible else 'quarantined',
            'temporal_migrated_at':migration_at,
        })
        source_entity_id=row['source_entity_id'] or (evidence[0] if evidence else None)
        modes[profile.mode]+=1
        if fields['epistemic_status']=='historical_observation':
            historical+=1
        if fields['epistemic_status'] in ('quarantined_nonfactual','authority_review'):
            quarantined+=1
        if apply:
            connection.execute('''update semantic_assertions
              set epistemic_status=?,valid_from=?,valid_to=?,source_entity_id=?,metadata=?,updated_at=?
              where id=?''',(
                fields['epistemic_status'],fields['valid_from'],fields['valid_to'],source_entity_id,
                json.dumps(metadata,sort_keys=True),migration_at,row['id']))
            if not profile.auto_eligible:
                connection.execute("update distillation_reconciliation_proposals set status='quarantined' where candidate_id=?",(row['candidate_id'],))
            if profile.auto_eligible and profile.mode in ('CURRENT_STATE','COMMITMENT'):
                lineages.add((row['subject_id'],row['predicate']))
            updated+=1
    if apply:
        for subject_id,predicate in sorted(lineages):
            reconcile_lineages(connection,subject_id,predicate)
        connection.commit()
    connection.row_factory=old_factory
    return {
        'assertions_examined':len(rows),
        'updated':updated,
        'modes':dict(modes),
        'historical_observations':historical,
        'quarantined':quarantined,
        'lineages':len(lineages),
        'apply':bool(apply),
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',default=str(DEFAULT_DB))
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    migration_at=now()
    with closing(sqlite3.connect(args.db)) as connection:
        report=migrate(connection,migration_at,apply=args.apply)
    print(json.dumps(report,sort_keys=True,indent=2))


if __name__=='__main__':
    main()
