#!/usr/bin/env python3
from contextlib import closing
import hashlib, json, sqlite3, urllib.request
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
BROKER="http://127.0.0.1:8765/v1/generate"
SECRET=(Path.home()/"agalmic-llm-broker/secret.txt").read_text().strip()
PROMPT='''Extract durable semantic claims from this evidence segment.
Return JSON with key items. Each item: kind, subject, predicate, object, literal,
confidence, evidence_ids. Ignore transient chatter. Do not invent facts.
Use the supplied evidence id in evidence_ids for every claim.'''

def now(): return datetime.now(timezone.utc).isoformat()
def wid(parent,model):
    return "claimwork_"+hashlib.sha256((parent+"|"+model+"|"+now()).encode()).hexdigest()[:24]

def call(text,model="critic"):
    body=json.dumps({"model":model,"prompt":text,"timeout_seconds":90}).encode()
    req=urllib.request.Request(BROKER,data=body,headers={
      "Content-Type":"application/json","Authorization":"Bearer "+SECRET})
    with urllib.request.urlopen(req,timeout=120) as r:
        d=json.load(r)
    return d.get("response",""),d.get("model",model)

with closing(sqlite3.connect(DB)) as c:
    c.row_factory=sqlite3.Row
    rows=c.execute("""select w.id parent_id,w.segment_id,s.content
      from distillation_claim_work w
      join distillation_segments s on s.id=w.segment_id
      where w.validation_status='quarantined'
        and coalesce(w.route_stage,'')!='escalated'
      order by w.updated_at asc limit 10""").fetchall()
    out=[]
    for r in rows:
        prompt=PROMPT+"\n\nEVIDENCE_ID: "+r["segment_id"]+"\n\n"+r["content"]
        try:
            raw,model=call(prompt,"critic")
            child=wid(r["parent_id"],model)
            ts=now()
            c.execute("""insert into distillation_claim_work(
              id,segment_id,extractor,raw_record,validation_status,salvage_state,
              attempts,parent_work_id,route_stage,created_at,updated_at)
              values(?,?,?,?,'pending','none',0,?,'alternate_model',?,?)""",
              (child,r["segment_id"],model,raw,r["parent_id"],ts,ts))
            c.execute("""update distillation_claim_work set route_stage='escalated',
                         updated_at=? where id=?""",(ts,r["parent_id"]))
            out.append({"parent":r["parent_id"],"child":child,"model":model})
        except Exception as e:
            c.execute("""update distillation_claim_work set route_stage='escalation_failed',
                         last_error=?,updated_at=? where id=?""",
                      (str(e)[:1000],now(),r["parent_id"]))
            out.append({"parent":r["parent_id"],"error":str(e)[:400]})
        c.commit()
    print(json.dumps({"attempted":len(rows),"results":out},indent=2))
