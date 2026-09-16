#!/usr/bin/env python3
from contextlib import closing
import json, sqlite3
from datetime import datetime,timezone,timedelta
from pathlib import Path

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
      "salvage_events_last_hour":q("select count(*) from distillation_salvage_events where created_at>=?",(cutoff,))
    }
    yield_rate=metrics["claims_valid"]/max(1,metrics["claims_total"])
    salvage_rate=metrics["salvage_success"]/max(1,metrics["claims_total"])
    prov_rate=metrics["provenance_complete"]/max(1,q("select count(*) from distillation_candidates"))
    meta={"claims_per_hour":metrics["claims_last_hour"],"valid_record_yield":yield_rate,
          "salvage_rate":salvage_rate,"provenance_completeness":prov_rate}
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
