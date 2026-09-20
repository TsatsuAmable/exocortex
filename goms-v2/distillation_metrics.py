#!/usr/bin/env python3
from contextlib import closing
import json, sqlite3
from datetime import datetime,timezone,timedelta
from pathlib import Path

from distillation_evidence_review import pending_count as evidence_review_pending_count
from distillation_rewrite_repair import actionable_rewrite_count

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
WINDOW=3600

def now(): return datetime.now(timezone.utc).isoformat()

with closing(sqlite3.connect(DB)) as c:
    c.row_factory=sqlite3.Row
    cutoff=(datetime.now(timezone.utc)-timedelta(seconds=WINDOW)).isoformat()
    q=lambda sql,args=(): c.execute(sql,args).fetchone()[0]
    metrics={
      "segments_total":q("select count(*) from distillation_segments"),
      "segments_done":q("select count(*) from distillation_segments where status='done'"),
      "claims_total":q("select count(*) from distillation_claim_work"),
      "claims_valid":q("select count(*) from distillation_claim_work where validation_status in ('salvaged','valid')"),
      "claims_quarantined":q("select count(*) from distillation_claim_work where validation_status='quarantined'"),
      "retries":q("select coalesce(sum(attempts),0) from distillation_claim_work"),
      "salvage_success":q("select count(*) from distillation_claim_work where salvage_state='recovered'"),
      "provenance_complete":q("""select count(*) from distillation_candidates
        where evidence_ids is not null and evidence_ids!='[]'"""),
      "governor_backlog":q("""select count(*) from distillation_reconciliation_proposals
        where status='candidate'"""),
      "promotion_backlog":q("""select count(*) from distillation_promotion_gate
        where decision in ('AUTO_READY','REVIEW')"""),
      "claims_last_hour":q("select count(*) from distillation_claim_work where created_at>=?",(cutoff,)),
      "salvage_events_last_hour":q("select count(*) from distillation_salvage_events where created_at>=?",(cutoff,)),
      "candidates_last_hour":q("select count(*) from distillation_candidates where created_at>=?",(cutoff,)),
      "assertions_last_hour":q("select count(*) from semantic_assertions where created_at>=?",(cutoff,)),
      "accepted_candidates":q("select count(*) from distillation_validations where verdict in ('accept','reclassify')"),
      "promoted_proposals":q("select count(*) from distillation_reconciliation_proposals where status='promoted'"),
      "semantic_assertions_total":q("select count(*) from semantic_assertions"),
      "review_holds":q("select count(*) from distillation_review_adjudications where action='HOLD'"),
      "shape_rewrite_backlog":q("""select count(*) from distillation_reconciliation_proposals p
        join distillation_promotion_gate g on g.candidate_id=p.candidate_id
        join distillation_graphshape_reviews s
          on s.candidate_id=p.candidate_id and s.gate_fingerprint=g.gate_fingerprint
        where p.status='candidate' and g.decision='AUTO_READY' and s.verdict='REWRITE'""")
,
      "evidence_review_pending":evidence_review_pending_count(c),
      "rewrite_actionable":actionable_rewrite_count(c)
    }
    yield_rate=metrics["claims_valid"]/max(1,metrics["claims_total"])
    salvage_rate=metrics["salvage_success"]/max(1,metrics["claims_total"])
    prov_rate=metrics["provenance_complete"]/max(1,q("select count(*) from distillation_candidates"))
    accepted_to_promoted=metrics["promoted_proposals"]/max(1,metrics["accepted_candidates"])
    promotion_to_arrival=metrics["assertions_last_hour"]/max(1,metrics["candidates_last_hour"])
    meta={
      "claims_per_hour":metrics["claims_last_hour"],
      "candidate_arrival_per_hour":metrics["candidates_last_hour"],
      "assertions_per_hour":metrics["assertions_last_hour"],
      "promotion_to_arrival_ratio":promotion_to_arrival,
      "accepted_to_promoted_ratio":accepted_to_promoted,
      "valid_record_yield":yield_rate,
      "salvage_rate":salvage_rate,
      "provenance_completeness":prov_rate,
      "review_holds":metrics["review_holds"],
      "shape_rewrite_backlog":metrics["shape_rewrite_backlog"],
      "evidence_review_pending":metrics["evidence_review_pending"],
      "rewrite_actionable":metrics["rewrite_actionable"],
    }
    c.execute("""insert into distillation_metrics(
      observed_at,window_seconds,segments_total,segments_done,claims_total,claims_valid,
      claims_quarantined,retries,salvage_success,provenance_complete,governor_backlog,
      promotion_backlog,metadata) values(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (now(),WINDOW,metrics["segments_total"],metrics["segments_done"],metrics["claims_total"],
       metrics["claims_valid"],metrics["claims_quarantined"],metrics["retries"],
       metrics["salvage_success"],metrics["provenance_complete"],metrics["governor_backlog"],
       metrics["promotion_backlog"],json.dumps(meta)))
    c.commit()
    print(json.dumps({**metrics,**meta},indent=2))
