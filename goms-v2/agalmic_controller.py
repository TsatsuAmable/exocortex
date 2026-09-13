#!/usr/bin/env python3
import hashlib, json, re, sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"

SCARCITY_RULES=[
 ("permission", re.compile(r"permission|authori[sz]|access denied|blocked by policy|credential|oauth|login",re.I)),
 ("tooling", re.compile(r"missing tool|tooling|not installed|command not found|unsupported",re.I)),
 ("interface", re.compile(r"interface|bridge|integration|api missing|no api|cannot connect|connection",re.I)),
 ("compute", re.compile(r"compute|gpu|cpu|memory|ram|quota|tokens?|model capacity",re.I)),
 ("data", re.compile(r"missing data|dataset|corpus|evidence|insufficient data|need observations",re.I)),
 ("knowledge", re.compile(r"unknown|uncertain|need research|prior art|epistemic|don't know|do not know",re.I)),
 ("attention", re.compile(r"human attention|manual|needs human|human judgment|review required",re.I)),
 ("time", re.compile(r"waiting|wait for|pending|later|after .* completes",re.I)),
 ("physical", re.compile(r"hardware|device|adb|usb|quest|physical",re.I)),
]

CAPABILITY_HINTS={
 "permission":["Tailscale","Hermes gateway","Manfred control plane"],
 "tooling":["Aineko","Hermes gateway","Ollama"],
 "interface":["Hermes gateway","Aineko ChatGPT Sync Monitor v0.8.2","Manfred control plane"],
 "compute":["Ollama","Agalmic LLM broker","Yoda/Fedora"],
 "data":["Canonical GOMS","ChatGPT raw evidence archive","Neo4j GOMS projection"],
 "knowledge":["Canonical GOMS","Neo4j GOMS projection","Adversarial review committees"],
 "attention":["Aineko","Manfred control plane","GOMS semantic maintenance"],
 "time":["Aineko","GOMS semantic maintenance"],
 "physical":["Yoda/Fedora","Millhouse ADB bridge","Ultron"],
}

def now(): return datetime.now(timezone.utc).isoformat()
def sid(kind,name): return kind+"_"+hashlib.sha256(name.encode()).hexdigest()[:20]

def ensure_scarcity(c,name):
    eid=sid("scarcity",name)
    ts=now()
    c.execute("""insert or ignore into entities
      (id,type,title,summary,tags,metadata,created_at,updated_at)
      values(?,?,?,?,?,?,?,?)""",
      (eid,"scarcity",name.title(),f"Detected {name} scarcity/constraint.","[]","{}",ts,ts))
    return eid

def capability(c,scarcity):
    for title in CAPABILITY_HINTS.get(scarcity,[]):
        row=c.execute("""select id,title from entities
                         where title=? and type in ('tool','agent','service','machine','interface','data_store','routine','committee')
                         limit 1""",(title,)).fetchone()
        if row: return row[0],row[1]
    return None,None

with sqlite3.connect(DB) as c:
    c.row_factory=sqlite3.Row
    rows=c.execute("select * from branches").fetchall()
    counts={}
    for b in rows:
        status=(b["status"] or "").upper()
        blocker=(b["blocker"] or "").strip()
        text=" ".join([b["title"] or "",b["objective"] or "",blocker,b["next_action"] or ""])
        scarcity=None; confidence=0.0; rationale=""

        if status=="BLOCKED":
            task_state="BLOCKED"
        elif status=="PARKED":
            task_state="PARKED"
        elif status in ("CONCLUDED","DONE","COMPLETE"):
            task_state="COMPLETE"
        elif status in ("ACTIVE","DELEGATED"):
            task_state="ACTIVE"
        else:
            task_state="UNKNOWN"

        # Only classify scarcity when there is blocker/dependency evidence.
        evidence=blocker if blocker else (text if task_state=="BLOCKED" else "")
        if evidence:
            for name,rx in SCARCITY_RULES:
                if rx.search(evidence):
                    scarcity=name; confidence=0.9 if blocker else 0.7
                    rationale=f"Matched deterministic {name} scarcity rule from explicit task evidence."
                    break
            if scarcity is None and task_state=="BLOCKED":
                scarcity="unclassified"; confidence=0.4
                rationale="Task is explicitly BLOCKED but deterministic rules cannot classify the scarcity."

        scarcity_id=None; capability_id=None; capability_title=None
        proposed=""
        adjacent=None
        if scarcity:
            scarcity_id=ensure_scarcity(c,scarcity)
            capability_id,capability_title=capability(c,scarcity)
            if capability_id:
                proposed=f"Evaluate whether {capability_title} can reduce the {scarcity} scarcity for this task."
                adjacent=f"Task may become unblocked if {capability_title} sufficiently reduces {scarcity}."
            else:
                proposed=f"Search for or build a capability that reduces {scarcity} scarcity."
                adjacent=f"New capability acquisition could open this blocked task."

        c.execute("""insert into agalmic_reconciliations
          (task_id,task_state,scarcity_type,scarcity_entity_id,capability_entity_id,
           confidence,rationale,proposed_action,adjacent_possible,observed_at)
          values(?,?,?,?,?,?,?,?,?,?)
          on conflict(task_id) do update set
          task_state=excluded.task_state,scarcity_type=excluded.scarcity_type,
          scarcity_entity_id=excluded.scarcity_entity_id,capability_entity_id=excluded.capability_entity_id,
          confidence=excluded.confidence,rationale=excluded.rationale,
          proposed_action=excluded.proposed_action,adjacent_possible=excluded.adjacent_possible,
          observed_at=excluded.observed_at""",
          (b["id"],task_state,scarcity,scarcity_id,capability_id,confidence,rationale,proposed,adjacent,now()))
        counts[task_state]=counts.get(task_state,0)+1

        # Escalate only ambiguous blocked work or blocked work with no known capability.
        attn_id="attn_agalmic_"+hashlib.sha256(b["id"].encode()).hexdigest()[:20]
        ts=now()
        if task_state=="BLOCKED" and (scarcity in (None,"unclassified") or capability_id is None):
            reason="UnclassifiedScarcity" if scarcity in (None,"unclassified") else "MissingCapability"
            summary=(f"{b['title']} is blocked. " +
                     ("Deterministic rules cannot identify the limiting scarcity."
                      if reason=="UnclassifiedScarcity"
                      else f"No known capability is currently mapped to {scarcity} scarcity."))
            actions=["Review task context","Run model-assisted scarcity analysis","Inspect related evidence"]
            c.execute("""insert into attention_items
              (id,resource_id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              values(?,?,'agalmic','warning',?,?,'open',?,'AgalmicController',?,?)
              on conflict(id) do update set title=excluded.title,summary=excluded.summary,
              status='open',suggested_actions=excluded.suggested_actions,updated_at=excluded.updated_at""",
              (attn_id,b["id"],f"Blocked task needs reasoning: {b['title']}",summary,json.dumps(actions),ts,ts))
        else:
            c.execute("update attention_items set status='resolved',updated_at=? where id=?",(ts,attn_id))

    c.commit()
    print(json.dumps({
      "states":counts,
      "blocked_with_scarcity":c.execute("select count(*) from agalmic_reconciliations where task_state='BLOCKED' and scarcity_type is not null").fetchone()[0],
      "matched_capabilities":c.execute("select count(*) from agalmic_reconciliations where capability_entity_id is not null").fetchone()[0]
    },indent=2))
