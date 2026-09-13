#!/usr/bin/env python3
import json,sqlite3,urllib.request
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
GOLD=json.loads((ROOT/"distillation_gold.json").read_text())["items"]
BROKER="http://127.0.0.1:8765/v1/generate"
SECRET=(Path.home()/"agalmic-llm-broker/secret.txt").read_text().strip()

SCHEMA='''Extract durable semantic state from these USER messages.
Return strict JSON {"items":[...]}.
Each item: kind, subject, predicate, object, literal, confidence, evidence_ids.
Allowed kinds: objective, decision, task, scarcity, capability, constraint,
preference, outcome, adjacent_possible, proposal, principle, question.
Do not convert questions/proposals into decisions. Ignore one-off chatter unless durable.
Only claims directly supported by cited evidence IDs. confidence <= 0.98.'''

def call(prompt,model):
    body=json.dumps({"model":model,"prompt":prompt,"timeout_seconds":90}).encode()
    req=urllib.request.Request(BROKER,data=body,headers={
      "Content-Type":"application/json","Authorization":"Bearer "+SECRET})
    with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)

def parse(text):
    text=(text or "").strip(); a=text.find("{"); b=text.rfind("}")
    return json.loads(text[a:b+1])

with sqlite3.connect(DB) as c:
    c.row_factory=sqlite3.Row
    ids=[x["evidence_id"] for x in GOLD]
    evidence={}
    for i in ids:
        r=c.execute("select summary from entities where id=?",(i,)).fetchone()
        evidence[i]=r["summary"] if r else ""

outputs=[]
errors=[]
ordered=[]
pos=[x for x in GOLD if x.get("should_extract",True)]
neg=[x for x in GOLD if not x.get("should_extract",True)]
for i,x in enumerate(pos):
    ordered.append(x)
    if i < len(neg):
        ordered.append(neg[i])
for x in neg[len(pos):]:
    ordered.append(x)

failed_ids=set()
for i in range(0,len(ordered),5):
    batch=ordered[i:i+5]
    text="\n".join(f"[{x['evidence_id']}] {evidence[x['evidence_id']][:1800]}" for x in batch)
    batch_success=False
    for model in ("balanced","critic"):
        try:
            reply=call(SCHEMA+"\n\n"+text,model)
            out=parse(reply.get("response",""))
            for item in out.get("items",[]):
                item["_extractor_model"]=reply.get("model",model)
                outputs.append(item)
            batch_success=True
        except Exception as exc:
            errors.append({"batch":i,"model":model,"error":str(exc)[:1000]})
    if not batch_success:
        failed_ids.update(x["evidence_id"] for x in batch)

results=[]
for g in GOLD:
    matched=[]
    for x in outputs:
        if g["evidence_id"] not in (x.get("evidence_ids") or []): continue
        text=" ".join(str(x.get(k) or "") for k in ("subject","predicate","object","literal")).lower()
        hits=sum(1 for k in g.get("object_keywords",[]) if k.lower() in text)
        matched.append((hits,float(x.get("confidence") or 0),x))
    matched.sort(key=lambda z:(z[0],z[1]),reverse=True)
    best=matched[0][2] if matched else None
    positive=g.get("should_extract",True)
    if positive:
        kind_ok=bool(best and best.get("kind") in g.get("acceptable_kinds",[g.get("kind")]))
        keyword_fraction=matched[0][0]/max(1,len(g.get("object_keywords",[]))) if matched else 0
    else:
        kind_ok=(best is None)
        keyword_fraction=1.0 if best is None else 0.0
    results.append({
      "evidence_id":g["evidence_id"],
      "should_extract":positive,
      "scorable":g["evidence_id"] not in failed_ids,
      "found":bool(best),
      "kind_ok":kind_ok,
      "keyword_fraction":keyword_fraction,
      "best":best
    })

positives=[x for x in results if x["should_extract"] and x["scorable"]]
negatives=[x for x in results if not x["should_extract"] and x["scorable"]]
summary={
 "gold_items":len(results),
 "scored_items":len(positives)+len(negatives),
 "failed_items":len(failed_ids),
 "positive_items":len(positives),
 "negative_items":len(negatives),
 "evidence_recall":sum(x["found"] for x in positives)/max(1,len(positives)),
 "kind_accuracy":sum(x["kind_ok"] for x in positives)/max(1,len(positives)),
 "mean_keyword_coverage":sum(x["keyword_fraction"] for x in positives)/max(1,len(positives)),
 "negative_suppression":sum(not x["found"] for x in negatives)/max(1,len(negatives)),
 "errors":len(errors)
}
print(json.dumps({"summary":summary,"items":results,"errors":errors},indent=2))
