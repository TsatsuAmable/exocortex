#!/usr/bin/env python3


def select_pending_shape_reviews(connection, limit=12):
    connection.row_factory=__import__('sqlite3').Row
    rows=connection.execute('''
      select p.*,g.score,g.reasons,g.gate_fingerprint
      from distillation_reconciliation_proposals p
      join distillation_promotion_gate g on g.candidate_id=p.candidate_id
      left join distillation_graphshape_reviews s on s.candidate_id=p.candidate_id and s.gate_fingerprint=g.gate_fingerprint
      where p.status='candidate' and g.decision='AUTO_READY' and g.gate_fingerprint is not null and s.candidate_id is null
      order by g.score desc,p.candidate_id asc
      limit ?
    ''',(max(1,int(limit)),)).fetchall()
    return [dict(r) for r in rows]


def _distinct_reviews(reviews):
    by_model={}
    for review in reviews or ():
        item=dict(review)
        model=str(item.get("model") or "").strip()
        verdict=str(item.get("verdict") or "").upper()
        if model and verdict in {"ACCEPT","REWRITE","REJECT"}:
            by_model.setdefault(model,item)
    return list(by_model.values())


def aggregate_shape_verdicts(reviews, required_reviewers=2):
    required=max(1,int(required_reviewers))
    items=_distinct_reviews(reviews)
    if len(items) < required:
        models=','.join(str(x.get("model") or "unknown") for x in items) or 'none'
        return 'REWRITE',f'INSUFFICIENT_REVIEW_CONSENSUS reviewers={models}'
    verdicts=[str(x.get("verdict")).upper() for x in items]
    models=','.join(f'{x.get("model") or "unknown"}:{str(x.get("verdict")).upper()}' for x in items)
    if all(v == 'ACCEPT' for v in verdicts):
        return 'ACCEPT',f'CONSENSUS_ACCEPT {models}'
    if len(set(verdicts)) > 1:
        return 'REWRITE',f'REVIEWER_DISAGREEMENT {models}'
    verdict=verdicts[0]
    return verdict,f'CONSENSUS_{verdict} {models}'


def committee_complete(reviews_by_candidate, candidate_ids, required_reviewers=2):
    required=max(1,int(required_reviewers))
    return all(len(_distinct_reviews(reviews_by_candidate.get(candidate_id,()))) >= required
               for candidate_id in candidate_ids)
