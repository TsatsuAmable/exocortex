#!/usr/bin/env python3
from contextlib import closing
import json, os, sqlite3
from datetime import datetime, timezone
from pathlib import Path

from distillation_model_client import generate_structured, REMOTE_MODEL_CHAIN, LOCAL_MODEL_CHAIN, prompt_allows_remote
from distillation_graphshape_policy import aggregate_shape_verdicts, committee_complete, select_pending_shape_reviews
from distillation_review_reconciler import ensure_schema as ensure_review_schema

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
def now(): return datetime.now(timezone.utc).isoformat()

def parse(text):
    text=(text or "").strip()
    a,b=text.find("{"),text.rfind("}")
    if a<0 or b<=a:
        raise ValueError("no JSON object")
    return json.loads(text[a:b+1])

def call(prompt,model):
    result=generate_structured(prompt,models=(model,))
    return {"model":result["model"],"response":result["response"]}
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

with closing(sqlite3.connect(DB)) as c, c:
    c.row_factory=sqlite3.Row
    c.executescript("""CREATE TABLE IF NOT EXISTS distillation_graphshape_reviews(
      candidate_id TEXT PRIMARY KEY, verdict TEXT NOT NULL, rationale TEXT,
      subject_title TEXT,subject_type TEXT,predicate TEXT,
      object_title TEXT,object_type TEXT,literal TEXT,
      reviewer_model TEXT,reviewed_at TEXT,gate_fingerprint TEXT);""")
    ensure_review_schema(c)
    batch_size=max(1,min(int(os.getenv('GOMS_GRAPHSHAPE_BATCH_SIZE','12')),96))
    rows=select_pending_shape_reviews(c,limit=batch_size)
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

    overall={}; reviews_by_candidate={}
    remote_review_models=REMOTE_MODEL_CHAIN+('deepseek-v4-pro:cloud','nemotron-3-ultra:cloud')
    review_models = remote_review_models if prompt_allows_remote(PROMPT+"\n\n"+json.dumps(payload,ensure_ascii=False)) else LOCAL_MODEL_CHAIN
    candidate_ids=[r['candidate_id'] for r in rows]
    for model in review_models:
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
            review={"model":actual_model,"verdict":verdict,"rationale":str(x.get("rationale") or ""),
                    "subject_title":x.get("subject_title"),"subject_type":x.get("subject_type"),
                    "predicate":x.get("predicate"),"object_title":x.get("object_title"),
                    "object_type":x.get("object_type"),"literal":x.get("literal")}
            reviews_by_candidate.setdefault(r["candidate_id"],[]).append(review)
            vals=(r["candidate_id"],actual_model,verdict,review["rationale"],
                  review["subject_title"],review["subject_type"],review["predicate"],
                  review["object_title"],review["object_type"],review["literal"],now())
            c.execute("""insert into distillation_graphshape_review_history(
              candidate_id,reviewer_model,verdict,rationale,subject_title,subject_type,
              predicate,object_title,object_type,literal,reviewed_at)
              values(?,?,?,?,?,?,?,?,?,?,?)""", vals)
        overall[actual_model]=counts
        c.commit()
        if committee_complete(reviews_by_candidate,candidate_ids):
            break
    for r in rows:
        reviews=reviews_by_candidate.get(r["candidate_id"],[])
        if len(reviews) < 2:
            continue
        verdict,rationale=aggregate_shape_verdicts(reviews)
        representative=next((x for x in reviews if x["verdict"] != "ACCEPT"),reviews[0])
        committee='committee:'+','.join(str(x["model"]) for x in reviews)
        c.execute("""insert or replace into distillation_graphshape_reviews(
          candidate_id,verdict,rationale,subject_title,subject_type,predicate,
          object_title,object_type,literal,reviewer_model,reviewed_at,gate_fingerprint)
          values(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (r["candidate_id"],verdict,rationale,representative.get("subject_title"),
           representative.get("subject_type"),representative.get("predicate"),
           representative.get("object_title"),representative.get("object_type"),
           representative.get("literal"),committee,now(),r["gate_fingerprint"]))
    c.commit()
    print(json.dumps({"reviewed":len(rows),"by_model":overall},indent=2))
