#!/usr/bin/env python3
from contextlib import closing
import json,re,sqlite3,urllib.request
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
BROKER="http://127.0.0.1:8765/v1/generate"
SECRET=(Path.home()/"agalmic-llm-broker/secret.txt").read_text().strip()
def now(): return datetime.now(timezone.utc).isoformat()

def parse(t):
    t=(t or "").strip()
    candidates=[t]
    m=re.search(r"```(?:json)?\s*(\{.*?\})\s*```",t,re.S|re.I)
    if m: candidates.append(m.group(1))
    a,b=t.find("{"),t.rfind("}")
    if a>=0 and b>a: candidates.append(t[a:b+1])
    err=None
    for x in candidates:
        try: return json.loads(x)
        except Exception as exc: err=exc
    raise err or ValueError("no JSON")

def call(prompt,model="reason",timeout=120):
    body=json.dumps({"model":model,"prompt":prompt,"timeout_seconds":timeout}).encode()
    req=urllib.request.Request(BROKER,data=body,headers={
      "Content-Type":"application/json","Authorization":"Bearer "+SECRET})
    with urllib.request.urlopen(req,timeout=timeout+30) as r:return json.load(r)

with closing(sqlite3.connect(DB)) as c, c:
    c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS distillation_resolutions(
      candidate_id TEXT PRIMARY KEY,subject_entity_id TEXT,object_entity_id TEXT,
      create_subject INTEGER NOT NULL DEFAULT 0,create_object INTEGER NOT NULL DEFAULT 0,
      confidence REAL NOT NULL,rationale TEXT NOT NULL,resolver TEXT NOT NULL,created_at TEXT NOT NULL)""")
    ready=[dict(r) for r in c.execute("""select rr.candidate_id,d.kind,d.subject,d.predicate,
      d.object,d.literal,rr.confidence from distillation_ready rr
      join distillation_candidates d on d.id=rr.candidate_id""")]
    catalog=[dict(r) for r in c.execute("""select id,type,title,summary,status from entities
      where type not in ('evidence','source') order by type,title""")]

prompt="""Resolve semantic candidates against the canonical entity catalog.
Prefer an existing entity only when conceptually identical, including renamed historical concepts.
Do not merge merely related concepts. If no defensible match exists, request a new entity.
Return strict JSON:
{"items":[{"candidate_id":"...","subject_entity_id":null,"object_entity_id":null,
"create_subject":false,"create_object":false,"confidence":0.0,"rationale":"..."}]}
Object may be null when candidate object is null or literal carries the meaning.
CATALOG:
"""+json.dumps(catalog,ensure_ascii=False)+"""
CANDIDATES:
"""+json.dumps(ready,ensure_ascii=False)
reply=call(prompt)
raw=reply.get("response","")
try:
    out=parse(raw)
except Exception:
    repair=call("Convert this entity-resolution response into strict JSON matching the requested schema. Preserve meaning; add no facts.\n\n"+raw,model="critic",timeout=90)
    out=parse(repair.get("response",""))

with closing(sqlite3.connect(DB)) as c, c:
    for x in out.get("items",[]):
        cid=x.get("candidate_id")
        if not cid: continue
        c.execute("""insert or replace into distillation_resolutions
          (candidate_id,subject_entity_id,object_entity_id,create_subject,create_object,
           confidence,rationale,resolver,created_at) values(?,?,?,?,?,?,?,?,?)""",
          (cid,x.get("subject_entity_id"),x.get("object_entity_id"),
           1 if x.get("create_subject") else 0,1 if x.get("create_object") else 0,
           min(.98,max(0,float(x.get("confidence") or 0))),
           str(x.get("rationale") or ""),reply.get("model","reason"),now()))
    c.commit()
    rows=c.execute("""select d.subject,d.predicate,d.object,
      r.subject_entity_id,r.object_entity_id,r.create_subject,r.create_object,
      r.confidence,r.rationale
      from distillation_ready rr join distillation_candidates d on d.id=rr.candidate_id
      join distillation_resolutions r on r.candidate_id=rr.candidate_id
      order by r.confidence desc""").fetchall()
    print(json.dumps([dict(r) for r in rows],indent=2))
