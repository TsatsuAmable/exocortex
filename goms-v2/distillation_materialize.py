#!/usr/bin/env python3
from contextlib import closing
import hashlib,json,sqlite3
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"

def now(): return datetime.now(timezone.utc).isoformat()
def cid(work_id,ordinal,item):
    raw=work_id+"|"+str(ordinal)+"|"+json.dumps(item,sort_keys=True)
    return "distcand_"+hashlib.sha256(raw.encode()).hexdigest()[:24]
with closing(sqlite3.connect(DB)) as c:
    c.row_factory=sqlite3.Row
    rows=c.execute("""select id,segment_id,parsed_record from distillation_claim_work
      where validation_status='salvaged' and parsed_record is not null
      order by updated_at asc""").fetchall()
    created=0
    for w in rows:
        try: items=json.loads(w["parsed_record"]).get("items",[])
        except: continue
        for i,x in enumerate(items):
            if not isinstance(x,dict): continue
            candidate_id=cid(w["id"],i,x)
            ts=now()
            before=c.total_changes
            c.execute("""insert or ignore into distillation_candidates(
              id,run_id,kind,subject,predicate,object,literal,confidence,
              evidence_ids,status,created_at)
              values(?,?,?,?,?,?,?,?,?,'candidate',?)""",
              (candidate_id,"streaming",str(x.get("kind") or ""),
               str(x.get("subject") or ""),str(x.get("predicate") or ""),
               x.get("object"),x.get("literal"),
               min(.98,max(0,float(x.get("confidence") or 0))),
               json.dumps(x.get("evidence_ids") or [w["segment_id"]]),ts))
            if c.total_changes>before: created+=1
            c.execute("""insert or ignore into distillation_claim_candidates(
              work_id,candidate_id,ordinal,created_at) values(?,?,?,?)""",
              (w["id"],candidate_id,i,ts))
    c.commit()
    print(json.dumps({"claim_work":len(rows),"created_candidates":created,
                      "streaming_candidates":c.execute("select count(*) from distillation_candidates where run_id='streaming'").fetchone()[0]},indent=2))
