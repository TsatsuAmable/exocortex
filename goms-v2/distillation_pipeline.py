#!/usr/bin/env python3
import fcntl, hashlib, json, sqlite3, urllib.request
from datetime import datetime, timezone
from pathlib import Path

from distillation_policy import build_extraction_prompt, canonicalize_kind, reap_stale_runs

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
LOCK=ROOT/"distillation.lock"
BROKER="http://127.0.0.1:8765/v1/generate"
SECRET=(Path.home()/"agalmic-llm-broker/secret.txt").read_text().strip()

def now(): return datetime.now(timezone.utc).isoformat()
def hid(x): return hashlib.sha256(x.encode()).hexdigest()[:24]

def parse_json(text):
    text=(text or "").strip()
    first,last=text.find("{"),text.rfind("}")
    if first < 0 or last <= first:
        raise ValueError("no JSON object found in model response")
    return json.loads(text[first:last+1])

def call(prompt):
    body=json.dumps({"model":"balanced","prompt":prompt,"timeout_seconds":75}).encode()
    req=urllib.request.Request(BROKER,data=body,headers={
        "Content-Type":"application/json","Authorization":"Bearer "+SECRET})
    with urllib.request.urlopen(req,timeout=105) as r:
        return json.load(r)

SCHEMA=build_extraction_prompt()

with LOCK.open("w") as lf:
    try:
        fcntl.flock(lf.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("distillation already running")

    with sqlite3.connect(DB) as c:
        c.row_factory=sqlite3.Row
        c.executescript("""CREATE TABLE IF NOT EXISTS distillation_runs(
          id TEXT PRIMARY KEY,started_at TEXT,completed_at TEXT,status TEXT,
          evidence_count INTEGER DEFAULT 0,item_count INTEGER DEFAULT 0,
          metadata TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS distillation_candidates(
          id TEXT PRIMARY KEY,run_id TEXT,kind TEXT,subject TEXT,predicate TEXT,
          object TEXT,literal TEXT,confidence REAL,evidence_ids TEXT,
          status TEXT DEFAULT 'candidate',created_at TEXT);""")

        abandoned = reap_stale_runs(c)
        if abandoned:
            c.commit()

        rows=c.execute("""select id,summary from entities
          where type='evidence' and tags like '%"user"%'
          and length(summary)>=40
          order by cast(json_extract(metadata,'$.create_time') as real) desc
          limit 40""").fetchall()
        run="distill_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        c.execute("""insert into distillation_runs
          (id,started_at,status,evidence_count) values(?,?,?,?)""",
          (run,now(),"RUNNING",len(rows)))
        c.commit()

        items=[]; errors=[]; diagnostics=[]
        for i in range(0,len(rows),10):
            batch=rows[i:i+10]
            evidence="\n".join(
                f"[{r['id']}] {r['summary'][:1400]}" for r in batch
            )
            try:
                reply=call(SCHEMA+"\n\n"+evidence)
                raw=reply.get("response","")
                diagnostics.append({
                    "batch_start":i,
                    "model":reply.get("model"),
                    "response_chars":len(raw or "")
                })
                out=parse_json(raw)
            except Exception as exc:
                errors.append({"batch_start":i,"error":str(exc)[:1000]})
                continue

            valid={r["id"] for r in batch}
            for x in out.get("items",[])[:40]:
                ev=[e for e in x.get("evidence_ids",[]) if e in valid]
                if not ev:
                    continue
                kind=canonicalize_kind(x.get("kind"))
                if not kind:
                    continue
                x["kind"]=kind
                x["evidence_ids"]=ev
                items.append(x)

        for x in items:
            cid="distcand_"+hid(json.dumps(x,sort_keys=True))
            c.execute("""insert or ignore into distillation_candidates(
              id,run_id,kind,subject,predicate,object,literal,confidence,
              evidence_ids,created_at) values(?,?,?,?,?,?,?,?,?,?)""",
              (cid,run,x.get("kind",""),x.get("subject",""),
               x.get("predicate",""),x.get("object"),x.get("literal"),
               min(.98,max(0.0,float(x.get("confidence",0)))),
               json.dumps(x["evidence_ids"]),now()))

        meta={"policy":"candidate-only","errors":errors,
              "error_count":len(errors),"diagnostics":diagnostics,
              "sampled_evidence_ids":[r["id"] for r in rows],
              "abandoned_stale_runs":abandoned}
        c.execute("""update distillation_runs set completed_at=?,status=?,
                     item_count=?,metadata=? where id=?""",
                  (now(),"SUCCESS" if not errors else "DEGRADED",
                   len(items),json.dumps(meta),run))
        c.commit()
        print(json.dumps({
          "run":run,"evidence":len(rows),"candidates":len(items),
          "errors":len(errors),"diagnostics":diagnostics
        },indent=2))
