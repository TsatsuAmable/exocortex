#!/usr/bin/env python3
import hashlib,json,re,sqlite3,urllib.request
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
PACKETS=ROOT/"guardian"/"packets"
OUT=ROOT/"guardian"/"reviews"
OUT.mkdir(parents=True,exist_ok=True)
BROKER="http://127.0.0.1:8765/v1/generate"
SECRET=(Path.home()/"agalmic-llm-broker/secret.txt").read_text().strip()

def now(): return datetime.now(timezone.utc).isoformat()
def rid(packet_sha): return "guardian_"+packet_sha[:20]+"_"+datetime.now(timezone.utc).strftime("%Y%m%d")
def pid(run_id,title): return "guardian_prop_"+hashlib.sha256((run_id+"|"+title).encode()).hexdigest()[:24]

def parse_review(text):
    text=(text or "").strip()
    candidates=[text]
    m=re.search(r"```(?:json)?\s*(\{.*?\})\s*```",text,re.S|re.I)
    if m: candidates.append(m.group(1))
    first,last=text.find("{"),text.rfind("}")
    if first>=0 and last>first: candidates.append(text[first:last+1])
    err=None
    for cand in candidates:
        try: return json.loads(cand)
        except Exception as exc: err=exc
    raise err or ValueError("empty model response")

def broker_call(model,prompt,timeout):
    body=json.dumps({"model":model,"prompt":prompt,"timeout_seconds":timeout}).encode()
    req=urllib.request.Request(BROKER,data=body,headers={
        "Content-Type":"application/json","Authorization":"Bearer "+SECRET})
    with urllib.request.urlopen(req,timeout=timeout+30) as r:
        return json.load(r)

packets=sorted(PACKETS.glob("*.json"))
if not packets: raise SystemExit("no guardian packet")
packet_path=packets[-1]
packet_text=packet_path.read_text()
packet_sha=hashlib.sha256(packet_text.encode()).hexdigest()
run_id=rid(packet_sha)

schema='''Return STRICT JSON only:
{"summary":"short assessment","overall_health":"healthy|degraded|concerning",
"proposals":[{"category":"epistemic|architecture|agalmic|attention|resilience|distillation|ontology",
"severity":"info|warning|critical","title":"short title","rationale":"why this matters",
"evidence_refs":["specific packet section or object ids"],
"proposed_change":"proposal only; no direct mutation","confidence":0.0}]}
Be adversarial and skeptical. Do not fabricate facts. Prefer fewer high-value proposals.
Flag stale, contradictory, underspecified, noisy, or misleading state.
Evaluate whether GOMS converts tasks/scarcities into capabilities and adjacent possibles while reducing human attention.
Never directly mutate canonical GOMS.'''
prompt=schema+"\n\nAUDIT PACKET:\n"+packet_text

with sqlite3.connect(DB) as c:
    c.execute("""insert or replace into guardian_runs
      (id,started_at,model,status,packet_sha256,metadata)
      values(?,?,?,?,?,?)""",(run_id,now(),"strong","RUNNING",packet_sha,
      json.dumps({"packet":str(packet_path)})))
    c.commit()

try:
    strong=broker_call("strong",prompt,180)
    raw=strong.get("response","")
    repair=None
    try:
        review=parse_review(raw)
    except Exception:
        repair_prompt=("Convert the response below into STRICT JSON matching the Guardian schema. "
                       "Preserve meaning and add no facts.\n\n"+raw)
        repair=broker_call("critic",repair_prompt,90)
        review=parse_review(repair.get("response",""))
    proposals=review.get("proposals") or []
    out_path=OUT/f"{run_id}.json"
    out_path.write_text(json.dumps({"strong":strong,"repair":repair,"review":review},
                                   ensure_ascii=False,indent=2))
    with sqlite3.connect(DB) as c:
        for prop in proposals[:30]:
            title=str(prop.get("title") or "Untitled Guardian proposal")
            c.execute("""insert or replace into guardian_proposals
              (id,run_id,category,severity,title,rationale,evidence_refs,
               proposed_change,confidence,status,created_at)
              values(?,?,?,?,?,?,?,?,?,'candidate',?)""",
              (pid(run_id,title),run_id,str(prop.get("category") or "epistemic"),
               str(prop.get("severity") or "info"),title,str(prop.get("rationale") or ""),
               json.dumps(prop.get("evidence_refs") or []),
               str(prop.get("proposed_change") or ""),float(prop.get("confidence") or 0),now()))

        c.execute("""update guardian_runs set completed_at=?,status='SUCCESS',
                     proposal_count=?,metadata=? where id=?""",
                  (now(),len(proposals),json.dumps({
                    "packet":str(packet_path),"review":str(out_path),
                    "overall_health":review.get("overall_health"),
                    "summary":review.get("summary"),
                    "repair_model":repair.get("model") if repair else None}),run_id))
        c.commit()
    print(json.dumps({"run_id":run_id,"status":"SUCCESS","proposal_count":len(proposals),
                      "overall_health":review.get("overall_health"),
                      "summary":review.get("summary")},indent=2))
except Exception as exc:
    with sqlite3.connect(DB) as c:
        c.execute("update guardian_runs set completed_at=?,status='ERROR',metadata=? where id=?",
                  (now(),json.dumps({"packet":str(packet_path),"error":str(exc)[:2000]}),run_id))
        c.commit()
    raise
