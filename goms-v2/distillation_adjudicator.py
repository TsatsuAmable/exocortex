#!/usr/bin/env python3
import hashlib,json,sqlite3,urllib.request
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
BROKER="http://127.0.0.1:8765/v1/generate"
SECRET=(Path.home()/"agalmic-llm-broker/secret.txt").read_text().strip()

def now(): return datetime.now(timezone.utc).isoformat()
def parse(text):
    text=(text or "").strip()
    a,b=text.find("{"),text.rfind("}")
    if a<0 or b<=a: raise ValueError("no JSON object")
    return json.loads(text[a:b+1])
def call(prompt):
    body=json.dumps({"model":"reason","prompt":prompt,"timeout_seconds":120}).encode()
    req=urllib.request.Request(BROKER,data=body,headers={
        "Content-Type":"application/json","Authorization":"Bearer "+SECRET})
    with urllib.request.urlopen(req,timeout=150) as r:return json.load(r)

with sqlite3.connect(DB) as c:
    c.row_factory=sqlite3.Row
    run=c.execute("select id from distillation_runs where item_count>0 order by completed_at desc limit 1").fetchone()[0]
    candidates=[dict(r) for r in c.execute(
        "select * from distillation_candidates where run_id=? order by confidence desc",(run,))]
    branches=[dict(r) for r in c.execute(
        "select id,title,status,objective,last_result,next_action,blocker from branches order by updated_at desc limit 40")]
    assertions=[dict(r) for r in c.execute(
        "select subject_id,predicate,object_id,literal_value,confidence,epistemic_status from semantic_assertions limit 100")]
    evidence={}
    for cand in candidates:
        ids=json.loads(cand["evidence_ids"])
        evidence[cand["id"]]=[
            {"id":eid,"summary":(c.execute("select summary from entities where id=?",(eid,)).fetchone() or [""])[0][:1200]}
            for eid in ids
        ]

prompt="""You adjudicate candidate memories for a long-lived personal cognitive graph.
Classify each candidate with status from:
durable_current, preference_current, resolved, implemented, completed_or_historical,
historical_design, ephemeral, exploratory, exploratory_historical, superseded, uncertain.
Also give canonicalizable true/false, confidence 0..0.98, and a short rationale.
Canonicalize only information that is both durable AND currently relevant.
Questions, one-off tasks, resolved incidents, completed work, and old superseded designs are not canonical.
Use CURRENT_BRANCHES and CURRENT_ASSERTIONS to detect supersession.
Return strict JSON: {"items":[{"candidate_id":"...","status":"...",
"canonicalizable":true,"confidence":0.9,"rationale":"..."}]}.

CURRENT_BRANCHES:
"""+json.dumps(branches,ensure_ascii=False)+"""
CURRENT_ASSERTIONS:
"""+json.dumps(assertions,ensure_ascii=False)+"""
CANDIDATES_AND_EVIDENCE:
"""+json.dumps([{"candidate":x,"evidence":evidence[x["id"]]} for x in candidates],ensure_ascii=False)

reply=call(prompt)
out=parse(reply.get("response",""))
with sqlite3.connect(DB) as c:
    for x in out.get("items",[]):
        cid=x.get("candidate_id")
        if not cid: continue
        c.execute("""insert or replace into distillation_adjudications
          (candidate_id,status,canonicalizable,confidence,rationale,adjudicator,created_at)
          values(?,?,?,?,?,?,?)""",
          (cid,str(x.get("status") or "uncertain"),1 if x.get("canonicalizable") else 0,
           min(.98,max(0,float(x.get("confidence") or 0))),str(x.get("rationale") or ""),
           reply.get("model","reason"),now()))
    c.commit()
    rows=c.execute("""select g.candidate_id,g.expected_status,g.canonicalizable expected,
                            a.status,a.canonicalizable predicted,a.confidence
                     from distillation_gold g join distillation_adjudications a on a.candidate_id=g.candidate_id""").fetchall()
    n=len(rows); exact=sum(1 for r in rows if r[1]==r[3]); canon=sum(1 for r in rows if r[2]==r[4])
    tp=sum(1 for r in rows if r[2]==1 and r[4]==1)
    fp=sum(1 for r in rows if r[2]==0 and r[4]==1)
    fn=sum(1 for r in rows if r[2]==1 and r[4]==0)
    precision=tp/(tp+fp) if tp+fp else 0
    recall=tp/(tp+fn) if tp+fn else 0
    print(json.dumps({"model":reply.get("model"),"evaluated":n,
      "status_exact_accuracy":exact/n if n else 0,
      "canonicalizable_accuracy":canon/n if n else 0,
      "canonical_precision":precision,"canonical_recall":recall,
      "false_positives":fp,"false_negatives":fn},indent=2))
