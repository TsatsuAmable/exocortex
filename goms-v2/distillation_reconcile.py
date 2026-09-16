#!/usr/bin/env python3
from contextlib import closing
import json, sqlite3
from datetime import datetime,timezone
from pathlib import Path

from distillation_reconcile_policy import select_eligible_candidates
from distillation_model_client import generate_structured

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
def now(): return datetime.now(timezone.utc).isoformat()
def norm(x):
    return " ".join(str(x or "").lower().replace("_"," ").split())
def parse(text):
    text=(text or "").strip()
    a,b=text.find("{"),text.rfind("}")
    if a<0 or b<=a: raise ValueError("no JSON")
    return json.loads(text[a:b+1])

def call(prompt):
    result=generate_structured(prompt)
    return {"model":result["model"],"response":result["response"]}

SCHEMA='''Canonicalize validated semantic candidates into PROPOSALS for the GOMS graph.
Never mutate state and never invent unsupported facts.
For each candidate return:
candidate_id, canonical_kind,
subject {mode: existing|new, id, type, title},
predicate,
object {mode: existing|new|literal, id, type, title, literal},
confidence, rationale.
Use existing IDs only when they are genuinely the same concept.
When a durable objective is expressed, prefer an Objective/idea entity linked from the User rather than awkward sentence-shaped pseudo-entities.
When a requirement/constraint is expressed, prefer a typed constraint entity or a meaningful edge to the affected system.
New entities are proposals only.
Return strict JSON {"items":[...]} with one item per input candidate.'''

with closing(sqlite3.connect(DB)) as c, c:
    c.row_factory=sqlite3.Row
    c.executescript("""CREATE TABLE IF NOT EXISTS distillation_reconciliation_proposals(
      candidate_id TEXT PRIMARY KEY, canonical_kind TEXT,
      subject_mode TEXT,subject_id TEXT,subject_type TEXT,subject_title TEXT,
      predicate TEXT,object_mode TEXT,object_id TEXT,object_type TEXT,
      object_title TEXT,literal TEXT,confidence REAL,rationale TEXT,
      status TEXT DEFAULT 'candidate',created_at TEXT);""")
    existing=[dict(r) for r in c.execute("""select id,type,title,summary
      from entities where type not in ('evidence','source')
      order by type,title limit 300""").fetchall()]
    aliases={norm(r["alias"]):dict(r) for r in c.execute(
      "select alias,canonical_entity_id,confidence,status from entity_aliases where status='active'").fetchall()}
    pred_rows=[dict(r) for r in c.execute(
      "select canonical,aliases,subject_types,object_types,semantics from predicate_registry where status='active'").fetchall()]
    predicate_map={}
    for pr in pred_rows:
        predicate_map[norm(pr["canonical"])]=pr["canonical"]
        for a in json.loads(pr["aliases"] or "[]"):
            predicate_map[norm(a)]=pr["canonical"]
    eligible=select_eligible_candidates(c,limit=60)

    errors=[]; written=0
    allowed_ids={e["id"] for e in existing}
    context=json.dumps(existing,ensure_ascii=False)
    for i in range(0,len(eligible),6):
        batch=eligible[i:i+6]
        prompt=SCHEMA+"\n\nEXISTING ENTITIES:\n"+context+"\n\nCANDIDATES:\n"+json.dumps(batch,ensure_ascii=False)
        try:
            reply=call(prompt); out=parse(reply.get("response",""))
        except Exception as exc:
            errors.append({"batch":i,"error":str(exc)[:1000]}); continue
        byid={x.get("candidate_id"):x for x in out.get("items",[])}
        for cand in batch:
            x=byid.get(cand["id"])
            if not x: continue
            sub=x.get("subject") or {}; obj=x.get("object") or {}
            raw_pred=str(x.get("predicate") or cand["predicate"])
            canonical_pred=predicate_map.get(norm(raw_pred),raw_pred)
            if sub.get("mode")=="new" and norm(sub.get("title")) in aliases:
                al=aliases[norm(sub.get("title"))]
                sub={"mode":"existing","id":al["canonical_entity_id"],"type":sub.get("type"),"title":sub.get("title")}
            if obj.get("mode")=="new" and norm(obj.get("title")) in aliases:
                al=aliases[norm(obj.get("title"))]
                obj={"mode":"existing","id":al["canonical_entity_id"],"type":obj.get("type"),"title":obj.get("title")}
            if sub.get("mode")=="existing" and sub.get("id") not in allowed_ids:
                sub={"mode":"new","id":None,"type":sub.get("type"),"title":sub.get("title")}
            if obj.get("mode")=="existing" and obj.get("id") not in allowed_ids:
                obj={"mode":"new","id":None,"type":obj.get("type"),"title":obj.get("title")}

            existing_status=c.execute(
                "select status from distillation_reconciliation_proposals where candidate_id=?",
                (cand["id"],)).fetchone()
            if existing_status and existing_status["status"]=="promoted":
                continue
            c.execute("""insert into distillation_reconciliation_proposals(
              candidate_id,canonical_kind,subject_mode,subject_id,subject_type,subject_title,
              predicate,object_mode,object_id,object_type,object_title,literal,
              confidence,rationale,status,created_at)
              values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              on conflict(candidate_id) do update set
              canonical_kind=excluded.canonical_kind,subject_mode=excluded.subject_mode,
              subject_id=excluded.subject_id,subject_type=excluded.subject_type,
              subject_title=excluded.subject_title,predicate=excluded.predicate,
              object_mode=excluded.object_mode,object_id=excluded.object_id,
              object_type=excluded.object_type,object_title=excluded.object_title,
              literal=excluded.literal,confidence=excluded.confidence,
              rationale=excluded.rationale
              where distillation_reconciliation_proposals.status!='promoted'""",
              (cand["id"],str(x.get("canonical_kind") or cand["validated_kind"]),
               str(sub.get("mode") or "new"),sub.get("id"),sub.get("type"),sub.get("title"),
               canonical_pred,str(obj.get("mode") or "literal"),
               obj.get("id"),obj.get("type"),obj.get("title"),obj.get("literal"),
               min(.99,max(0,float(x.get("confidence") or 0))),
               str(x.get("rationale") or ""),"candidate",now()))
            written+=1
        c.commit()
    print(json.dumps({"mode":"incremental","eligible":len(eligible),"written":written,"errors":errors},indent=2))
