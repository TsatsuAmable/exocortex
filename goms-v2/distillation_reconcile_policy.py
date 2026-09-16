#!/usr/bin/env python3


def select_eligible_candidates(connection, limit=60):
    connection.row_factory = __import__('sqlite3').Row
    rows = connection.execute('''
      select d.*,v.verdict,v.validated_kind,v.durability,
             v.confidence validator_confidence,v.rationale validator_rationale
      from distillation_candidates d
      join distillation_validations v on v.candidate_id=d.id
      left join distillation_reconciliation_proposals p on p.candidate_id=d.id
      where p.candidate_id is null
        and v.verdict in ('accept','reclassify')
        and v.durability in ('project','enduring')
        and d.confidence>=0.80 and v.confidence>=0.80
      order by v.confidence desc,d.created_at asc
      limit ?
    ''', (max(1, int(limit)),)).fetchall()
    return [dict(r) for r in rows]
