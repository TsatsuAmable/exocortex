#!/usr/bin/env python3
from contextlib import closing
import hashlib,json,sqlite3,subprocess
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
def now(): return datetime.now(timezone.utc).isoformat()
def rid(kind,name): return "res_"+hashlib.sha256((kind+"|"+name).encode()).hexdigest()[:20]
def aid(resource_id,ctype): return "attn_"+hashlib.sha256((resource_id+"|"+ctype).encode()).hexdigest()[:20]

def upsert_resource(c,kind,name,spec,status,controller="TopologyController",authority="system"):
    i=rid(kind,name); ts=now()
    row=c.execute("select generation,spec from resources where id=?",(i,)).fetchone()
    gen=1
    if row:
        gen=row[0] + (1 if row[1] != json.dumps(spec,sort_keys=True) else 0)
    c.execute("""insert into resources(id,kind,name,spec,status,generation,observed_generation,controller,authority,metadata,created_at,updated_at)
      values(?,?,?,?,?,?,?,?,?,'{}',?,?)
      on conflict(id) do update set spec=excluded.spec,status=excluded.status,
      generation=excluded.generation,observed_generation=excluded.observed_generation,
      controller=excluded.controller,authority=excluded.authority,updated_at=excluded.updated_at""",
      (i,kind,name,json.dumps(spec,sort_keys=True),json.dumps(status,sort_keys=True),gen,gen,controller,authority,ts,ts))
    return i

def condition(c,res,ctype,state,reason="",message="",severity="info"):
    ts=now()
    c.execute("""insert into resource_conditions(resource_id,condition_type,status,reason,message,severity,observed_at)
      values(?,?,?,?,?,?,?) on conflict(resource_id,condition_type) do update set
      status=excluded.status,reason=excluded.reason,message=excluded.message,severity=excluded.severity,observed_at=excluded.observed_at""",
      (res,ctype,state,reason,message,severity,ts))
    attention_id=aid(res,ctype)
    if state in ("False","Unknown") and severity in ("warning","critical"):
        c.execute("""insert into attention_items(id,resource_id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
          values(?,?,?,?,?,?,'open','[]','TopologyController',?,?)
          on conflict(id) do update set severity=excluded.severity,title=excluded.title,summary=excluded.summary,status='open',updated_at=excluded.updated_at""",
          (attention_id,res,"drift",severity,f"{ctype}: {reason}",message,ts,ts))
    else:
        c.execute("update attention_items set status='resolved',updated_at=? where id=?",(ts,attention_id))

def run(cmd):
    cp=subprocess.run(cmd,text=True,capture_output=True)
    return cp.returncode,cp.stdout.strip(),cp.stderr.strip()

with closing(sqlite3.connect(DB)) as c, c:
    # Critical services on Mac
    services=[
      ("Neo4j",["pgrep","-f","org.neo4j.server.Neo4jCommunity"]),
      ("Ollama",["pgrep","-f","ollama serve"]),
      ("Agalmic LLM broker",["pgrep","-f","agalmic-llm-broker/server.py"]),
      ("Hermes gateway",["pgrep","-f","hermes_cli.main.*gsvaineko"]),
    ]
    for name,cmd in services:
        rc,out,err=run(cmd); running=(rc==0 and bool(out))
        res=upsert_resource(c,"Service",name,{"desired_state":"running","host":"MacBook Pro"},
                            {"observed_state":"running" if running else "stopped","last_observed":now()})
        condition(c,res,"Ready","True" if running else "False",
                  "ProcessObserved" if running else "ProcessMissing",
                  f"{name} is {'running' if running else 'not observed'} on MacBook Pro.",
                  "info" if running else "critical")
    # Autonomous routines expected via launchd
    routines=[
      "org.aineko.chatgpt-goms-ingest",
      "org.aineko.chatgpt-replication",
      "org.aineko.goms-semantic-maintenance",
      "org.agalmic.goms-manfred-sync",
      "org.agalmic.aineko-vault-git-sync",
    ]
    rc,out,err=run(["launchctl","list"])
    for label in routines:
        present=label in out
        res=upsert_resource(c,"Routine",label,{"desired_state":"loaded","host":"MacBook Pro"},
                            {"observed_state":"loaded" if present else "missing","last_observed":now()})
        condition(c,res,"Ready","True" if present else "False",
                  "LaunchAgentLoaded" if present else "LaunchAgentMissing",
                  f"{label} is {'loaded' if present else 'not loaded'}.",
                  "info" if present else "critical")
    # Tailnet machine reachability
    rc,out,err=run(["/usr/local/bin/tailscale","status","--json"])
    peers={}
    if rc==0 and out:
        try:
            data=json.loads(out)
            peers={v.get("HostName"):bool(v.get("Online")) for v in data.get("Peer",{}).values()}
        except Exception: pass
    for host in ["fedora","millhouse-adb-bridge","Ultron"]:
        online=peers.get(host,False)
        res=upsert_resource(c,"Machine",host,{"desired_state":"reachable","network":"tailscale"},
                            {"observed_state":"reachable" if online else "unreachable","last_observed":now()})
        condition(c,res,"Reachable","True" if online else "False",
                  "TailnetOnline" if online else "TailnetOffline",
                  f"{host} is {'reachable' if online else 'not reachable'} via Tailscale.",
                  "info" if online else "warning")
    c.commit()

    print(json.dumps({
      "resources":c.execute("select count(*) from resources").fetchone()[0],
      "open_attention":c.execute("select count(*) from attention_items where status='open'").fetchone()[0],
      "conditions":c.execute("select count(*) from resource_conditions").fetchone()[0]
    },indent=2))
