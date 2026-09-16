#!/usr/bin/env python3
from contextlib import closing
import json,sqlite3
from datetime import datetime,timezone
from pathlib import Path

from distillation_model_client import generate_structured

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
def now(): return datetime.now(timezone.utc).isoformat()
def parse(text):
    text=(text or "").strip(); a=text.find("{"); b=text.rfind("}")
    if a<0 or b<=a: raise ValueError("no JSON")
    return json.loads(text[a:b+1])

def call(prompt):
    result=generate_structured(prompt)
    return {"model":result["model"],"response":result["response"]}
SCHEMA='''Independently validate semantic candidates against cited USER evidence.
Return strict JSON {"items":[...]} with candidate_id, verdict
(accept|reject|reclassify), kind, durability (ephemeral|session|project|enduring),
confidence, rationale.
Reject acknowledgements and transient one-off requests with no durable relevance.
Questions/proposals are not decisions unless the evidence commits to them.
Do not invent facts.'''

with closing(sqlite3.connect(DB)) as c:
    c.row_factory=sqlite3.Row
    candidates=[dict(r) for r in c.execute("""select d.*
      from distillation_candidates d
      left join distillation_validations v on v.candidate_id=d.id
      where v.candidate_id is null
      order by d.created_at asc limit 50""").fetchall()]
    evidence={}
    for x in candidates:
        for eid in json.loads(x.get("evidence_ids") or "[]"):
            if eid not in evidence:
                row=c.execute("select summary from entities where id=?",(eid,)).fetchone()
                evidence[eid]=row["summary"] if row else ""
    stats={"accepted":0,"reclassified":0,"rejected":0,"missing":0}
    errors=[]
    for i in range(0,len(candidates),10):
        batch=candidates[i:i+10]; payload=[]
        for x in batch:
            ev=json.loads(x.get("evidence_ids") or "[]")
            payload.append({
              "candidate_id":x["id"],"kind":x["kind"],"subject":x["subject"],
              "predicate":x["predicate"],"object":x["object"],"literal":x["literal"],
              "confidence":x["confidence"],
              "evidence":[{"id":e,"text":evidence.get(e,"")[:1800]} for e in ev]})
        try:
            reply=call(SCHEMA+"\n\n"+json.dumps(payload,ensure_ascii=False))
            result=parse(reply.get("response",""))
        except Exception as exc:
            errors.append({"batch":i,"error":str(exc)[:1000]}); continue
        byid={x.get("candidate_id"):x for x in result.get("items",[])}
        for cand in batch:
            v=byid.get(cand["id"])
            if not v:
                stats["missing"]+=1; continue
            verdict=str(v.get("verdict") or "reject")
            stats[{"accept":"accepted","reclassify":"reclassified"}.get(verdict,"rejected")]+=1
            c.execute("""insert or replace into distillation_validations(
              candidate_id,validator_model,verdict,validated_kind,durability,
              confidence,rationale,validated_at) values(?,?,?,?,?,?,?,?)""",
              (cand["id"],reply.get("model","critic"),verdict,
               str(v.get("kind") or cand["kind"]),str(v.get("durability") or "session"),
               min(.99,max(0,float(v.get("confidence") or 0))),
               str(v.get("rationale") or ""),now()))
        c.commit()
    print(json.dumps({"candidates":len(candidates),**stats,"errors":errors},indent=2))
