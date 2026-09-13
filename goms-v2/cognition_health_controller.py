#!/usr/bin/env python3
import json, re, sqlite3, subprocess, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
BROKER=Path.home()/"agalmic-llm-broker"
LOGS=BROKER/"logs"
def now(): return datetime.now(timezone.utc).isoformat()
def attn_id(name): import hashlib; return "attn_p1_"+hashlib.sha256(name.encode()).hexdigest()[:20]

QUOTA=re.compile(r"quota|rate.?limit|too many requests|429|resource exhausted|usage limit",re.I)
AUTH=re.compile(r"unauthori[sz]ed|forbidden|401|403|credential|api key|authentication",re.I)
PROVIDER=re.compile(r"provider|unavailable|overloaded|5\d\d|timeout|connection.*(refused|reset)",re.I)

def attention(c,key,severity,title,summary,actions,status="open"):
    ts=now(); i=attn_id(key)
    c.execute("""insert into attention_items(id,resource_id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
      values(?,NULL,'p1',?,?,?,?,?,'CognitionHealthController',?,?)
      on conflict(id) do update set severity=excluded.severity,title=excluded.title,summary=excluded.summary,
      status=excluded.status,suggested_actions=excluded.suggested_actions,updated_at=excluded.updated_at""",
      (i,severity,title,summary,status,json.dumps(actions),ts,ts))
def clear(c,key):
    c.execute("update attention_items set status='resolved',updated_at=? where id=?",(now(),attn_id(key)))

def http_json(url,timeout=3):
    try:
        with urllib.request.urlopen(url,timeout=timeout) as r:
            return True,json.load(r)
    except Exception as e: return False,{"error":str(e)}

broker_ok,broker= http_json("http://127.0.0.1:8765/health")
ollama_ok,ollama = http_json("http://127.0.0.1:11434/api/tags")
local_models = [m.get("name","") for m in (ollama.get("models",[]) if ollama_ok else [])]
fallback_ok = ollama_ok and len(local_models)>0

events=[]
for p in sorted(LOGS.glob("broker-*.jsonl"))[-2:]:
    try:
        for line in p.read_text(errors="replace").splitlines()[-500:]:
            try: events.append(json.loads(line))
            except: pass
    except: pass

recent_errors=[e for e in events if e.get("status")=="ERROR"]
quota_errors=[e for e in recent_errors if QUOTA.search(str(e.get("error","")))]
auth_errors=[e for e in recent_errors if AUTH.search(str(e.get("error","")))]
provider_errors=[e for e in recent_errors if PROVIDER.search(str(e.get("error","")))]

with sqlite3.connect(DB) as c:
    if not broker_ok:
        sev="critical" if not fallback_ok else "warning"
        attention(c,"broker-down",sev,"LLM broker unavailable",
                  "Agalmic LLM broker health endpoint is unavailable.",
                  ["Route to local Ollama models" if fallback_ok else "Restore broker service",
                   "Inspect broker service logs"])
    else: clear(c,"broker-down")

    if not ollama_ok:
        sev="critical" if not broker_ok else "warning"
        attention(c,"ollama-down",sev,"Local model runtime unavailable",
                  "Ollama is not responding; local fallback cognition is unavailable.",
                  ["Restore Ollama","Use broker/cloud route if healthy"])
    else: clear(c,"ollama-down")

    if quota_errors:
        models=sorted({str(e.get("model","unknown")) for e in quota_errors})
        sev="critical" if not fallback_ok and not broker_ok else "warning"
        attention(c,"quota",sev,"Model quota/rate limit encountered",
                  f"Recent quota/rate-limit errors observed for: {', '.join(models)}.",
                  ["Fail over to another model/provider","Reduce priority of nonessential jobs",
                   "Record quota exhaustion and retry-after when known"])
    else: clear(c,"quota")

    if auth_errors:
        attention(c,"auth","critical","Model authentication failure",
                  "Recent model/provider authentication failures were observed.",
                  ["Repair credentials/authorization","Disable broken route until repaired"])
    else: clear(c,"auth")

    if provider_errors and not quota_errors:
        sev="critical" if not fallback_ok else "warning"
        attention(c,"provider",sev,"Model provider/runtime failures",
                  f"{len(provider_errors)} recent provider/runtime errors observed.",
                  ["Route around failed provider","Inspect provider error details"])
    else: clear(c,"provider")

    # Fabric-level P1: no viable cognition route at all.
    if not broker_ok and not fallback_ok:
        attention(c,"fabric-down","critical","P1: cognitive fabric unavailable",
                  "Neither broker-backed strong models nor local Ollama fallback are currently available.",
                  ["Restore at least one cognitive route immediately","Pause nonessential autonomous jobs"])
    else: clear(c,"fabric-down")
    c.commit()
    print(json.dumps({
      "broker_ok":broker_ok,"ollama_ok":ollama_ok,"local_models":len(local_models),
      "recent_errors":len(recent_errors),"quota_errors":len(quota_errors),
      "auth_errors":len(auth_errors),"provider_errors":len(provider_errors),
      "open_p1":c.execute("select count(*) from attention_items where status='open' and category='p1'").fetchone()[0]
    },indent=2))
