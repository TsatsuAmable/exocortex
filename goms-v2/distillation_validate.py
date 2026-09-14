#!/usr/bin/env python3
from contextlib import closing
import json,sqlite3,urllib.request
from datetime import datetime,timezone
from pathlib import Path

from distillation_policy import build_validation_prompt, canonicalize_kind

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
BROKER="http://127.0.0.1:8765/v1/generate"
SECRET=(Path.home()/"agalmic-llm-broker/secret.txt").read_text().strip()

def now(): return datetime.now(timezone.utc).isoformat()
def parse(text):
    text=(text or "").strip()
    a,b=text.find("{"),text.rfind("}")
    if a<0 or b<=a: raise ValueError("no JSON")
    return json.loads(text[a:b+1])

def call(prompt):
    body=json.dumps({"model":"critic","prompt":prompt,"timeout_seconds":120}).encode()
    req=urllib.request.Request(BROKER,data=body,headers={
      "Content-Type":"application/json","Authorization":"Bearer "+SECRET})
    with urllib.request.urlopen(req,timeout=150) as r:
      return json.load(r)

SCHEMA=build_validation_prompt()

with closing(sqlite3.connect(DB)) as c, c:
    c.row_factory=sqlite3.Row
    c.executescript("""CREATE TABLE IF NOT EXISTS distillation_validations(
      candidate_id TEXT PRIMARY KEY,validator_model TEXT,verdict TEXT,
      validated_kind TEXT,durability TEXT,confidence REAL,rationale TEXT,
      validated_at TEXT);""")
    run=c.execute("""select id from distillation_runs
      where status in ('SUCCESS','DEGRADED')
      order by started_at desc limit 1""").fetchone()[0]
    candidates=[dict(r) for r in c.execute(
      "select * from distillation_candidates where run_id=?",(run,)).fetchall()]
    evidence={}
    for x in candidates:
        for eid in json.loads(x.get("evidence_ids") or "[]"):
            if eid not in evidence:
                row=c.execute("select summary from entities where id=?",(eid,)).fetchone()
                evidence[eid]=row["summary"] if row else ""

    errors=[]; accepted=0; rejected=0; reclassified=0
    for i in range(0,len(candidates),10):
        batch=candidates[i:i+10]
        payload=[]
        for x in batch:
            ev=json.loads(x.get("evidence_ids") or "[]")
            payload.append({
              "candidate_id":x["id"],"kind":x["kind"],"subject":x["subject"],
              "predicate":x["predicate"],"object":x["object"],"literal":x["literal"],
              "confidence":x["confidence"],
              "evidence":[{"id":e,"text":evidence.get(e,"")[:1800]} for e in ev]
            })
        try:
            reply=call(SCHEMA+"\n\n"+json.dumps(payload,ensure_ascii=False))
            result=parse(reply.get("response",""))
        except Exception as exc:
            errors.append({"batch":i,"error":str(exc)[:1000]})
            continue
        byid={x.get("candidate_id"):x for x in result.get("items",[])}
        for cand in batch:
            v=byid.get(cand["id"])
            if not v: continue
            verdict=str(v.get("verdict") or "reject")
            if verdict=="accept": accepted+=1
            elif verdict=="reclassify": reclassified+=1
            else: rejected+=1
            validated_kind=canonicalize_kind(v.get("kind"), cand["kind"])
            if not validated_kind:
                verdict="reject"
                validated_kind=cand["kind"]
            c.execute("""insert or replace into distillation_validations
              (candidate_id,validator_model,verdict,validated_kind,durability,
               confidence,rationale,validated_at) values(?,?,?,?,?,?,?,?)""",
              (cand["id"],reply.get("model","critic"),verdict,
               validated_kind,str(v.get("durability") or "session"),
               min(.99,max(0,float(v.get("confidence") or 0))),
               str(v.get("rationale") or ""),now()))
        c.commit()

    print(json.dumps({
      "run":run,"candidates":len(candidates),"accepted":accepted,
      "reclassified":reclassified,"rejected":rejected,"errors":errors
    },indent=2))
