#!/usr/bin/env python3
import json,sqlite3,urllib.request
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
GOLD=json.loads((ROOT/"distillation_gold.json").read_text())["items"]
BROKER="http://127.0.0.1:8765/v1/generate"
SECRET=(Path.home()/"agalmic-llm-broker/secret.txt").read_text().strip()

EXTRACT='''Extract durable semantic state from these USER messages.
Ignore acknowledgements and transient chatter.
Return strict JSON: {"items":[...]}.
Each item must contain:
kind, subject, predicate, object, literal, confidence, evidence_ids.
kind must be one of:
objective, decision, task, scarcity, capability, constraint,
preference, outcome, adjacent_possible, proposal, principle, question.

Definitions:
- objective: enduring desired state/outcome.
- decision: committed choice or accepted change.
- task: concrete action that should be executed.
- scarcity: limiting resource or bottleneck.
- capability: reusable ability, tool, resource, or mechanism.
- constraint: requirement or boundary on acceptable action.
- preference: stable user preference, priority, or style.
- outcome: observed result or completed state change.
- adjacent_possible: newly reachable future state enabled by capability/state change.
- proposal: candidate change not yet accepted.
- principle: durable architectural/governance rule or framing.
- question: unresolved question whose answer materially affects work.

Do not turn speculative questions into decisions.
Do not extract one-off content-generation requests as durable state unless they belong to an ongoing project.
Only include claims directly supported by cited evidence IDs.
Do not invent completion. confidence <= 0.98.
Prefer durable, reusable state over conversational detail.'''

VALIDATE='''Validate candidates against cited evidence.
Return strict JSON {"items":[...]} with candidate_id, verdict accept|reject|reclassify,
kind, durability ephemeral|session|project|enduring, confidence, rationale.
Reject one-off creative/writing/image/persona requests and transient chatter.
Do not upgrade questions/proposals into decisions without explicit commitment.'''

def call(model,prompt,timeout=120):
    body=json.dumps({"model":model,"prompt":prompt,"timeout_seconds":timeout}).encode()
    req=urllib.request.Request(BROKER,data=body,headers={
      "Content-Type":"application/json","Authorization":"Bearer "+SECRET})
    with urllib.request.urlopen(req,timeout=timeout+30) as r:return json.load(r)

def parse(text):
    text=(text or "").strip(); a=text.find("{"); b=text.rfind("}")
    if a<0 or b<=a: raise ValueError("no JSON")
    return json.loads(text[a:b+1])

with sqlite3.connect(DB) as c:
    c.row_factory=sqlite3.Row
    evidence={}
    for g in GOLD:
        r=c.execute("select summary from entities where id=?",(g["evidence_id"],)).fetchone()
        evidence[g["evidence_id"]]=r["summary"] if r else ""

extracted=[]; errors=[]
for i in range(0,len(GOLD),4):
    batch=GOLD[i:i+4]
    txt="\n".join(f"[{g['evidence_id']}] {evidence[g['evidence_id']][:1800]}" for g in batch)
    try:
        reply=call("balanced",EXTRACT+"\n\n"+txt,90)
        try:
            out=parse(reply.get("response",""))
        except Exception:
            reply=call("balanced",EXTRACT+"\n\nReturn STRICT JSON only.\n\n"+txt,90)
            out=parse(reply.get("response",""))
        for j,x in enumerate(out.get("items",[])):
            x=dict(x); x["candidate_id"]=f"gold_{i}_{j}"
            extracted.append(x)
    except Exception as exc:
        errors.append({"stage":"extract","batch":i,"error":str(exc)[:500]})

validated={}
for i in range(0,len(extracted),10):
    batch=extracted[i:i+10]
    payload=[]
    for x in batch:
        ev=x.get("evidence_ids") or []
        payload.append({**x,"evidence":[{"id":e,"text":evidence.get(e,"")[:1800]} for e in ev]})
    try:
        out=parse(call("critic",VALIDATE+"\n\n"+json.dumps(payload,ensure_ascii=False),120).get("response",""))
        for v in out.get("items",[]): validated[v.get("candidate_id")]=v
    except Exception as exc:
        errors.append({"stage":"validate","batch":i,"error":str(exc)[:500]})

results=[]
for g in GOLD:
    candidates=[]
    for x in extracted:
        if g["evidence_id"] not in (x.get("evidence_ids") or []): continue
        v=validated.get(x["candidate_id"],{})
        durable=v.get("durability") in ("project","enduring")
        survives=v.get("verdict") in ("accept","reclassify") and durable
        if survives:
            text=" ".join(str(x.get(k) or "") for k in ("subject","predicate","object","literal","statement")).lower()
            hits=sum(1 for k in g.get("object_keywords",[]) if k.lower() in text)
            candidates.append((hits,float(v.get("confidence") or 0),x,v))
    candidates.sort(key=lambda z:(z[0],z[1]),reverse=True)
    best=candidates[0] if candidates else None
    positive=g.get("should_extract",True)
    results.append({
      "evidence_id":g["evidence_id"],"should_extract":positive,
      "survives":bool(best),
      "kind_ok":bool(best and best[3].get("kind") in g.get("acceptable_kinds",[g.get("kind")])) if positive else not bool(best),
      "keyword_fraction":(best[0]/max(1,len(g.get("object_keywords",[])))) if (positive and best) else (1.0 if not positive and not best else 0.0),
      "extract":best[2] if best else None,"validation":best[3] if best else None
    })

pos=[x for x in results if x["should_extract"]]; neg=[x for x in results if not x["should_extract"]]
summary={
 "positive_recall_after_validation":sum(x["survives"] for x in pos)/max(1,len(pos)),
 "kind_accuracy_after_validation":sum(x["kind_ok"] for x in pos)/max(1,len(pos)),
 "semantic_coverage_after_validation":sum(x["keyword_fraction"] for x in pos)/max(1,len(pos)),
 "negative_suppression_after_validation":sum(not x["survives"] for x in neg)/max(1,len(neg)),
 "extract_count":len(extracted),"validated_count":len(validated),"errors":len(errors)
}
print(json.dumps({"summary":summary,"results":results,"errors":errors},indent=2))
