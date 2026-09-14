#!/usr/bin/env python3
from contextlib import closing
import json,sqlite3
from pathlib import Path
ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
THRESHOLD=0.93
ALLOWED={"durable_current","preference_current"}

with closing(sqlite3.connect(DB)) as c, c:
    c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS distillation_ready(
      candidate_id TEXT PRIMARY KEY,status TEXT NOT NULL,confidence REAL NOT NULL,
      reason TEXT NOT NULL,ready_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    rows=c.execute("""select d.id,a.status,a.canonicalizable,a.confidence
      from distillation_candidates d join distillation_adjudications a on a.candidate_id=d.id
      where a.canonicalizable=1""").fetchall()
    ready=[]
    for r in rows:
        ok=r["status"] in ALLOWED and r["confidence"]>=THRESHOLD
        if ok:
            c.execute("""insert or replace into distillation_ready(candidate_id,status,confidence,reason)
                         values(?,?,?,?)""",
                      (r["id"],r["status"],r["confidence"],
                       f"adjudicated canonicalizable with confidence >= {THRESHOLD}"))
            ready.append(r["id"])
    c.commit()

    gold=c.execute("""select g.canonicalizable expected,
      case when rr.candidate_id is null then 0 else 1 end predicted
      from distillation_gold g left join distillation_ready rr on rr.candidate_id=g.candidate_id""").fetchall()
    tp=sum(1 for r in gold if r["expected"]==1 and r["predicted"]==1)
    fp=sum(1 for r in gold if r["expected"]==0 and r["predicted"]==1)
    fn=sum(1 for r in gold if r["expected"]==1 and r["predicted"]==0)
    tn=sum(1 for r in gold if r["expected"]==0 and r["predicted"]==0)
    precision=tp/(tp+fp) if tp+fp else 0
    recall=tp/(tp+fn) if tp+fn else 0
    print(json.dumps({"threshold":THRESHOLD,"ready":len(ready),
      "tp":tp,"fp":fp,"fn":fn,"tn":tn,
      "precision":precision,"recall":recall},indent=2))
