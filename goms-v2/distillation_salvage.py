#!/usr/bin/env python3
from contextlib import closing
import hashlib, json, re, sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
REQ={"kind","subject","predicate","evidence_ids"}

def now(): return datetime.now(timezone.utc).isoformat()
def hid(prefix,text): return prefix+"_"+hashlib.sha256(text.encode()).hexdigest()[:24]

def iter_json_objects(text):
    dec=json.JSONDecoder(); i=0
    while i<len(text):
        j=text.find("{",i)
        if j<0: return
        try:
            obj,end=dec.raw_decode(text[j:])
            yield obj
            i=j+end
        except Exception:
            i=j+1

def coerce_record(x):
    if not isinstance(x,dict): return None
    if not REQ.issubset(x): return None
    ev=x.get("evidence_ids")
    if isinstance(ev,str): x["evidence_ids"]=[ev]
    elif not isinstance(ev,list): return None
    x["confidence"]=min(.98,max(0,float(x.get("confidence",0))))
    return x
def salvage(raw):
    records=[]; notes=[]
    try:
        top=json.loads(raw)
        pool=top.get("items",[]) if isinstance(top,dict) else top if isinstance(top,list) else []
        for x in pool:
            y=coerce_record(x)
            if y: records.append(y)
        if isinstance(top,dict) and top.get("items")==[]:
            return [],[("strict_json","empty_valid",0)]
        if records: return records,[("strict_json","success",len(records))]
    except Exception as e:
        notes.append(("strict_json","failed",str(e)[:300]))

    for obj in iter_json_objects(raw):
        pool=obj.get("items",[]) if isinstance(obj,dict) and isinstance(obj.get("items"),list) else [obj]
        for x in pool:
            y=coerce_record(x)
            if y: records.append(y)
    if records:
        notes.append(("fragment_json","success",len(records)))
        return records,notes

    # Last deterministic recovery for JSONL-like records.
    for line in raw.splitlines():
        line=line.strip().strip(",")
        if not line.startswith("{"): continue
        try: y=coerce_record(json.loads(line))
        except: y=None
        if y: records.append(y)
    notes.append(("jsonl","success" if records else "failed",len(records)))
    return records,notes
def process_work(c,work_id):
    row=c.execute("select * from distillation_claim_work where id=?",(work_id,)).fetchone()
    records,notes=salvage(row["raw_record"] or "")
    ts=now()
    for stage,outcome,detail in notes:
        event=hid("salvage",work_id+"|"+stage+"|"+str(detail))
        c.execute("""insert or ignore into distillation_salvage_events(
          id,work_id,stage,action,outcome,detail,created_at)
          values(?,?,?,'deterministic_recovery',?,?,?)""",
          (event,work_id,stage,outcome,str(detail),ts))
    if not records:
        if any(stage=="strict_json" and outcome=="empty_valid" for stage,outcome,_ in notes):
            c.execute("""update distillation_claim_work set validation_status='empty_valid',
              salvage_state='not_needed',attempts=attempts+1,last_error=NULL,
              parsed_record='{"items":[]}',updated_at=? where id=?""",(ts,work_id))
            return -1
        c.execute("""update distillation_claim_work set validation_status='quarantined',
          salvage_state='exhausted',attempts=attempts+1,last_error='no valid records',
          updated_at=? where id=?""",(ts,work_id))
        return 0
    c.execute("""update distillation_claim_work set validation_status='salvaged',
      salvage_state='recovered',attempts=attempts+1,parsed_record=?,last_error=NULL,
      updated_at=? where id=?""",(json.dumps({"items":records}),ts,work_id))
    return len(records)

if __name__=="__main__":
    with closing(sqlite3.connect(DB)) as c:
        c.row_factory=sqlite3.Row
        ids=[r["id"] for r in c.execute("""select id from distillation_claim_work
              where validation_status in ('pending','parse_error') limit 100""")]
        n=sum(process_work(c,i) for i in ids)
        c.commit()
        print(json.dumps({"work_items":len(ids),"records_recovered":n},indent=2))
