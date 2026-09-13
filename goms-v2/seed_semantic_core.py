#!/usr/bin/env python3
import json, sqlite3, hashlib
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
def now(): return datetime.now(timezone.utc).isoformat()
def sid(kind,name): return kind+"_"+hashlib.sha256(name.encode()).hexdigest()[:20]
def ins_entity(c,t,title,summary="",eid=None):
    eid=eid or sid(t,title); ts=now()
    c.execute("""insert or ignore into entities(id,type,title,summary,tags,metadata,created_at,updated_at)
                 values(?,?,?,?,?,?,?,?)""",(eid,t,title,summary,"[]","{}",ts,ts))
    return eid
def assert_(c,sub,pred,obj=None,literal=None,confidence=1.0,status="explicit",source_ref="conversation://current"):
    raw="|".join(map(str,[sub,pred,obj,literal,source_ref]))
    aid="assert_"+hashlib.sha256(raw.encode()).hexdigest()[:24]; ts=now()
    c.execute("""insert or ignore into semantic_assertions
      (id,subject_id,predicate,object_id,literal_value,confidence,epistemic_status,source_ref,metadata,created_at,updated_at)
      values(?,?,?,?,?,?,?,?,?,?,?)""",(aid,sub,pred,obj,literal,confidence,status,source_ref,"{}",ts,ts))
with sqlite3.connect(DB) as c:
    person=ins_entity(c,"person","User","Human principal and judgment authority in the Manfred↔Aineko collaboration.")
    obj=ins_entity(c,"idea","Increase joint cognitive capacity","Expand autonomous machine cognition while preserving human strategic control.")
    scarcity=ins_entity(c,"scarcity","Human attention","Human attention, selection, validation, and intervention bandwidth are scarce.")
    nemosyne=ins_entity(c,"project","nemosyne.world","Spatial/VR data-navigation and representation-intelligence project.")
    agalmic=ins_entity(c,"project","Agalmic Research","Research and publication effort focused on abundance, cognition, and machine-human capability.")
    goms=ins_entity(c,"project","GOMS","Persistent ontological graph memory / external cognitive architecture.")
    manfred=ins_entity(c,"tool","Manfred","Human-facing control plane for intervention, prioritisation, and state visibility.")
    aineko=ins_entity(c,"agent","Aineko","Machine cognition collaborator for research, synthesis, implementation, verification, and autonomous execution.")
    obs=ins_entity(c,"tool","Obsidian","Human-readable durable knowledge surface.")
    notion=ins_entity(c,"tool","Notion","Structured knowledge/work-management surface.")
    for o in [obj]: assert_(c,person,"pursues",o)
    assert_(c,obj,"constrained_by",scarcity)
    for p in [nemosyne,agalmic,goms]: assert_(c,person,"works_on",p)
    assert_(c,goms,"implements",sid("idea","Cross-session persistent memory"),literal="Cross-session persistent memory",confidence=1.0)
    assert_(c,manfred,"serves_as",None,"human control plane")
    assert_(c,person,"delegates_to",aineko)
    assert_(c,goms,"projects_to",manfred)
    assert_(c,goms,"projects_to",obs)
    assert_(c,goms,"projects_to",notion)
print("seeded")
