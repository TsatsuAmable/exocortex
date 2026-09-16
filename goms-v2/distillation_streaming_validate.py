#!/usr/bin/env python3
from contextlib import closing
import json, sqlite3, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
BROKER="http://127.0.0.1:8765/v1/generate"
SECRET=(Path.home()/"agalmic-llm-broker/secret.txt").read_text().strip()

def now(): return datetime.now(timezone.utc).isoformat()
def parse(t):
    t=(t or "").strip(); a=t.find("{"); b=t.rfind("}")
    if a<0 or b<=a: raise ValueError("no JSON")
    return json.loads(t[a:b+1])
def call(prompt):
    body=json.dumps({"model":"critic","prompt":prompt,"timeout_seconds":120}).encode()
    req=urllib.request.Request(BROKER,data=body,headers={
      "Content-Type":"application/json","Authorization":"Bearer "+SECRET})
    with urllib.request.urlopen(req,timeout=150) as r:
        return json.load(r)
PROMPT='''Validate candidate claims against their cited evidence.
Return strict JSON {"items":[...]} one per candidate:
candidate_id, verdict accept|reject|reclassify, kind,
durability ephemeral|session|project|enduring, confidence, rationale.
Reject status questions, one-off requests, expiring transient facts,
acknowledgements, and runtime chatter unless they materially encode
a durable project decision/principle/capability/constraint.
Questions can be durable only if unresolved and materially govern work.
Do not invent facts.'''

with closing(sqlite3.connect(DB)) as c:
    c.row_factory=sqlite3.Row
    rows=[dict(r) for r in c.execute("""select d.*,
      e.summary evidence_text from distillation_candidates d
      left join entities e on e.id=json_extract(d.evidence_ids,'$[0]')
      left join distillation_validations v on v.candidate_id=d.id
      where d.run_id='streaming-worker' and v.candidate_id is null
      order by d.created_at desc limit 100""")]
    accepted=rejected=reclassified=errors=0
    for i in range(0,len(rows),12):
        batch=rows[i:i+12]
        payload=[{k:r.get(k) for k in [
          "id","kind","subject","predicate","object","literal",
          "confidence","evidence_ids","evidence_text"]} for r in batch]
        try:
            reply=call(PROMPT+"\n\n"+json.dumps(payload,ensure_ascii=False))
            out=parse(reply.get("response",""))
        except Exception as exc:
            errors+=1
            print("batch_error",i,exc)
            continue
        by={x.get("candidate_id"):x for x in out.get("items",[])}
        for r in batch:
            x=by.get(r["id"])
            if not x: continue
            v=str(x.get("verdict") or "reject")
            if v=="accept": accepted+=1
            elif v=="reclassify": reclassified+=1
            else: rejected+=1
            c.execute("""insert or replace into distillation_validations(
              candidate_id,validator_model,verdict,validated_kind,durability,
              confidence,rationale,validated_at)
              values(?,?,?,?,?,?,?,?)""",
              (r["id"],reply.get("model","critic"),v,
               str(x.get("kind") or r["kind"]),
               str(x.get("durability") or "session"),
               min(.99,max(0,float(x.get("confidence") or 0))),
               str(x.get("rationale") or ""),now()))
        c.commit()
    print(json.dumps({"candidates":len(rows),"accepted":accepted,
      "reclassified":reclassified,"rejected":rejected,"errors":errors},indent=2))
