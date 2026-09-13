#!/usr/bin/env python3
import json, sqlite3, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
BROKER="http://127.0.0.1:8765/v1/generate"
SECRET=(Path.home()/"agalmic-llm-broker/secret.txt").read_text().strip()

def now(): return datetime.now(timezone.utc).isoformat()

def parse(text):
    text=(text or "").strip()
    a,b=text.find("{"),text.rfind("}")
    if a<0 or b<=a:
        raise ValueError("no JSON object")
    return json.loads(text[a:b+1])

def call(prompt,model):
    body=json.dumps({"model":model,"prompt":prompt,"timeout_seconds":120}).encode()
    req=urllib.request.Request(BROKER,data=body,headers={
      "Content-Type":"application/json","Authorization":"Bearer "+SECRET})
    with urllib.request.urlopen(req,timeout=150) as r:
        return json.load(r)
PROMPT='''You are the final graph-shape reviewer for GOMS.
Review candidate canonical assertions that already passed extraction, independent validation,
durability filtering, provenance checks, alias checks, and contradiction checks.

For each candidate return one of:
ACCEPT: graph shape is semantically correct as written.
REWRITE: underlying meaning is valid but subject/predicate/object shape is wrong.
REJECT: meaning is unsupported, misleading, duplicate, or should not become canonical state.

Return strict JSON {"items":[...]} with:
candidate_id, verdict, rationale,
and when verdict=REWRITE: subject_title, subject_type, predicate,
object_title, object_type, literal.

Be especially alert to reversed edge direction, implementation technology confused
with conceptual owner, sentence-shaped entities, project-specific claims attached globally,
requirements represented as facts, proposals represented as decisions, and tools confused
with capabilities. Do not invent new facts.'''

with sqlite3.connect(DB) as c:
    c.row_factory=sqlite3.Row
    c.executescript("""CREATE TABLE IF NOT EXISTS distillation_graphshape_reviews(
      candidate_id TEXT PRIMARY KEY, verdict TEXT NOT NULL, rationale TEXT,
      subject_title TEXT,subject_type TEXT,predicate TEXT,
      object_title TEXT,object_type TEXT,literal TEXT,
      reviewer_model TEXT,reviewed_at TEXT);""")
    rows=[dict(r) for r in c.execute("""select p.*,g.score,g.reasons
      from distillation_reconciliation_proposals p
      join distillation_promotion_gate g on g.candidate_id=p.candidate_id
      where g.decision='AUTO_READY'
      order by g.score desc""").fetchall()]
    payload=[]
    for r in rows:
        payload.append({
          "candidate_id":r["candidate_id"],
          "canonical_kind":r["canonical_kind"],
          "subject":{"mode":r["subject_mode"],"id":r["subject_id"],
                     "type":r["subject_type"],"title":r["subject_title"]},
          "predicate":r["predicate"],
          "object":{"mode":r["object_mode"],"id":r["object_id"],
                    "type":r["object_type"],"title":r["object_title"],
                    "literal":r["literal"]},
          "gate_score":r["score"]
        })

    overall={}
    for model in ("critic","balanced"):
        try:
            reply=call(PROMPT+"\n\n"+json.dumps(payload,ensure_ascii=False),model)
            out=parse(reply.get("response",""))
        except Exception as exc:
            overall[model]={"ERROR":str(exc)[:500]}
            continue
        byid={x.get("candidate_id"):x for x in out.get("items",[])}
        counts={"ACCEPT":0,"REWRITE":0,"REJECT":0,"MISSING":0}
        actual_model=reply.get("model",model)
        for r in rows:
            x=byid.get(r["candidate_id"])
            if not x:
                counts["MISSING"]+=1
                continue
            verdict=str(x.get("verdict") or "REJECT").upper()
            if verdict not in counts:
                verdict="REJECT"
            counts[verdict]+=1
            vals=(r["candidate_id"],actual_model,verdict,str(x.get("rationale") or ""),
                  x.get("subject_title"),x.get("subject_type"),x.get("predicate"),
                  x.get("object_title"),x.get("object_type"),x.get("literal"),now())
            c.execute("""insert into distillation_graphshape_review_history(
              candidate_id,reviewer_model,verdict,rationale,subject_title,subject_type,
              predicate,object_title,object_type,literal,reviewed_at)
              values(?,?,?,?,?,?,?,?,?,?,?)""", vals)
            c.execute("""insert or replace into distillation_graphshape_reviews(
              candidate_id,verdict,rationale,subject_title,subject_type,predicate,
              object_title,object_type,literal,reviewer_model,reviewed_at)
              values(?,?,?,?,?,?,?,?,?,?,?)""",
              (r["candidate_id"],verdict,str(x.get("rationale") or ""),
               x.get("subject_title"),x.get("subject_type"),x.get("predicate"),
               x.get("object_title"),x.get("object_type"),x.get("literal"),
               actual_model,now()))
        overall[actual_model]=counts
        c.commit()
    print(json.dumps({"reviewed":len(rows),"by_model":overall},indent=2))
