#!/usr/bin/env python3
import json, sqlite3
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
GOLD=json.loads((ROOT/"distillation_gold.json").read_text())["items"]

def norm(x):
    return " ".join(str(x or "").lower().replace("_"," ").split())

with sqlite3.connect(DB) as c:
    c.row_factory=sqlite3.Row
    rr=c.execute("""select id,metadata from distillation_runs
                     where status in ('SUCCESS','DEGRADED')
                     order by started_at desc limit 1""").fetchone()
    run=rr["id"]
    try: sampled=set(json.loads(rr["metadata"] or "{}").get("sampled_evidence_ids",[]))
    except: sampled=set()
    rows=[dict(r) for r in c.execute(
        "select * from distillation_candidates where run_id=?",(run,)).fetchall()]

results=[]
for g in GOLD:
    candidates=[]
    for r in rows:
        try: ev=json.loads(r.get("evidence_ids") or "[]")
        except: ev=[]
        if g["evidence_id"] in ev:
            text=norm(" ".join([
                r.get("subject") or "",r.get("predicate") or "",
                r.get("object") or "",r.get("literal") or ""
            ]))
            hits=sum(1 for k in g["object_keywords"] if norm(k) in text)
            candidates.append((hits,r))
    candidates.sort(key=lambda x:(x[0],x[1].get("confidence") or 0),reverse=True)
    best=candidates[0][1] if candidates else None
    keyword_hits=candidates[0][0] if candidates else 0
    results.append({
        "evidence_id":g["evidence_id"],
        "sampled":g["evidence_id"] in sampled if sampled else None,
        "found":bool(best),
        "kind_ok":bool(best and best["kind"] in g.get("acceptable_kinds",[g["kind"]])),
        "predicate_exact":bool(best and best["predicate"]==g["predicate"]),
        "keyword_fraction":keyword_hits/max(1,len(g["object_keywords"])),
        "best":{k:best.get(k) for k in ["kind","subject","predicate","object","literal","confidence"]} if best else None
    })

n=len(results)
covered=[x for x in results if x["sampled"] is not False]
den=max(1,len(covered))
summary={
    "run":run,
    "gold_items":n,
    "sample_coverage":sum(x["sampled"] is True for x in results)/n if sampled else None,
    "conditional_evidence_recall":sum(x["found"] for x in covered)/den,
    "conditional_kind_accuracy":sum(x["kind_ok"] for x in covered)/den,
    "predicate_exact_accuracy":sum(x["predicate_exact"] for x in covered)/den,
    "mean_keyword_coverage":sum(x["keyword_fraction"] for x in covered)/den,
}
print(json.dumps({"summary":summary,"items":results},indent=2))
