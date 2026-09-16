#!/usr/bin/env python3


def select_pending_shape_reviews(connection, limit=12):
    connection.row_factory=__import__('sqlite3').Row
    rows=connection.execute('''
      select p.*,g.score,g.reasons
      from distillation_reconciliation_proposals p
      join distillation_promotion_gate g on g.candidate_id=p.candidate_id
      left join distillation_graphshape_reviews s on s.candidate_id=p.candidate_id
      where p.status='candidate' and g.decision='AUTO_READY' and s.candidate_id is null
      order by g.score desc,p.candidate_id asc
      limit ?
    ''',(max(1,int(limit)),)).fetchall()
    return [dict(r) for r in rows]
