#!/usr/bin/env python3
import hashlib,json,os,sqlite3,subprocess,time
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"; LEDGER=ROOT/"events.jsonl"
REPL=ROOT/"outbox/replication"; INGEST_STATE=ROOT/"chatgpt_live_ingest.sqlite3"
def now(): return datetime.now(timezone.utc).isoformat()
def aid(key): return "attn_infra_"+hashlib.sha256(key.encode()).hexdigest()[:20]

def upsert(c,key,severity,title,summary,actions,open_=True):
    ts=now(); i=aid(key)
    if open_:
        c.execute("""insert into attention_items(id,resource_id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
        values(?,NULL,'p1',?,?,?,?,?,'InfrastructureHealthController',?,?)
        on conflict(id) do update set severity=excluded.severity,title=excluded.title,
        summary=excluded.summary,status='open',suggested_actions=excluded.suggested_actions,updated_at=excluded.updated_at""",
        (i,severity,title,summary,"open",json.dumps(actions),ts,ts))
    else:
        c.execute("update attention_items set status='resolved',updated_at=? where id=?",(ts,i))

def sh(cmd):
    cp=subprocess.run(cmd,text=True,capture_output=True)
    return cp.returncode,cp.stdout.strip(),cp.stderr.strip()

def ledger_ok():
    if not LEDGER.exists(): return False,"ledger missing"
    lines=LEDGER.read_bytes().splitlines()
    start=max(1,len(lines)-5000)
    checked=0
    for i in range(start,len(lines)):
        try: obj=json.loads(lines[i])
        except Exception: return False,f"invalid JSON at line {i+1}"
        prev=obj.get("prev_line_sha256")
        if prev:
            actual=hashlib.sha256(lines[i-1]).hexdigest()
            if actual!=prev: return False,f"hash-chain mismatch at line {i+1}"
            checked+=1
    return checked>0,f"verified {checked} linked events"

def newest_age(path):
    files=list(path.glob("*")) if path.exists() else []
    if not files:return 0,None
    newest=max(f.stat().st_mtime for f in files)
    oldest=min(f.stat().st_mtime for f in files)
    return len(files),time.time()-oldest

with sqlite3.connect(DB) as c:
    # Canonical DB integrity
    try:
        result=c.execute("PRAGMA quick_check").fetchone()[0]
        db_ok=(result=="ok")
    except Exception as e:
        db_ok=False; result=str(e)
    upsert(c,"goms-integrity","critical","P1: canonical GOMS integrity failure",
           f"SQLite quick_check result: {result}",["Stop mutating GOMS","Restore from verified replica/backup","Investigate corruption"],not db_ok)

    ok,msg=ledger_ok()
    upsert(c,"ledger-integrity","critical","P1: GOMS provenance ledger integrity failure",
           msg,["Freeze canonical writes","Preserve damaged ledger","Reconcile from replica and raw evidence"],not ok)

    # Ingestion freshness
    ingest_loaded=False
    rc,out,err=sh(["launchctl","list"])
    ingest_loaded="org.aineko.chatgpt-goms-ingest" in out
    stale=False; age=None
    if INGEST_STATE.exists():
        try:
            ic=sqlite3.connect(INGEST_STATE)
            row=ic.execute("select max(ingested_at) from snapshots").fetchone()
            ic.close()
            if row and row[0]:
                dt=datetime.fromisoformat(row[0].replace("Z","+00:00"))
                age=(datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()
        except Exception: pass
    if not ingest_loaded:
        upsert(c,"ingest","critical","P1: ChatGPT→GOMS ingestion controller unavailable",
               "The live ingestion LaunchAgent is not loaded.",["Restore ingestion controller","Preserve raw archive until repaired"],True)
    else:
        upsert(c,"ingest","critical","","",[],False)

    # Replication backlog
    pending,oldest_age=newest_age(REPL)
    repl_loaded="org.aineko.chatgpt-replication" in out
    repl_bad=(not repl_loaded) or (pending>0 and oldest_age is not None and oldest_age>1800)
    sev="critical" if (pending>0 and oldest_age and oldest_age>21600) else "warning"
    upsert(c,"replication",sev,"GOMS replication degraded",
           f"pending={pending}; oldest_pending_seconds={round(oldest_age or 0)}; controller_loaded={repl_loaded}",
           ["Restore replication controller","Verify Yoda reachability","Drain replication backlog"],repl_bad)

    # Controller crash / not loaded checks
    critical_labels=[
      "org.aineko.goms-topology-controller",
      "org.aineko.goms-agalmic-controller",
      "org.aineko.goms-cognition-health",
      "org.aineko.goms-semantic-maintenance",
      "org.agalmic.goms-manfred-sync"
    ]
    missing=[x for x in critical_labels if x not in out]
    upsert(c,"controllers","critical","P1: critical controller set incomplete",
           "Missing: "+", ".join(missing),["Reload missing LaunchAgents","Inspect stderr logs"],bool(missing))

    # Manfred sync specifically
    manfred_ok="org.agalmic.goms-manfred-sync" in out
    upsert(c,"manfred","warning","Manfred control-plane sync unavailable",
           "GOMS↔Manfred sync LaunchAgent is not loaded.",["Restore Manfred sync","Continue canonical GOMS operation"],not manfred_ok)

    # Execution host reachability
    rc,tout,terr=sh(["/usr/local/bin/tailscale","status","--json"])
    yoda=False
    if rc==0 and tout:
        try:
            td=json.loads(tout)
            yoda=any(v.get("HostName")=="fedora" and v.get("Online") for v in td.get("Peer",{}).values())
        except: pass
    upsert(c,"yoda","warning","Yoda execution/replica host unreachable",
           "Fedora/Yoda is not online via Tailscale.",["Continue locally","Restore Yoda connectivity","Avoid deleting unreplicated evidence"],not yoda)

    c.commit()
    open_rows=c.execute("""select severity,title from attention_items
                           where status='open' and category='p1'
                           order by case severity when 'critical' then 0 else 1 end,title""").fetchall()
    print(json.dumps({"db_ok":db_ok,"ledger_ok":ok,"ledger_detail":msg,
                      "replication_pending":pending,"yoda_online":yoda,
                      "open_priority_health":[{"severity":r[0],"title":r[1]} for r in open_rows]},indent=2))
