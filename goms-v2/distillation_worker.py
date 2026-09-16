#!/usr/bin/env python3
from contextlib import closing
import argparse, hashlib, json, socket, sqlite3, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
OLLAMA="http://127.0.0.1:11434/api/generate"
MODEL_DEFAULT="qwen3.5:4b"

def now(): return datetime.now(timezone.utc).isoformat()
def hid(prefix,*parts):
    return prefix+"_"+hashlib.sha256("|".join(str(x) for x in parts).encode()).hexdigest()[:24]

PROMPT='''Extract only durable semantic state from the evidence below.
Return JSON only: {"items":[...]}.
Each item: kind, subject, predicate, object, literal, confidence, evidence_ids.
Allowed kind: objective, decision, task, scarcity, capability, constraint,
preference, outcome, adjacent_possible, proposal, principle, question.
Ignore acknowledgements, transient chatter, rhetoric and one-off requests unless project-relevant.
Do not invent completion or facts. Use exactly the supplied evidence ID.
Confidence <= 0.90 for this cheap extraction tier.
'''
def ollama(prompt,model):
    body=json.dumps({"model":model,"prompt":prompt,"stream":False,
                     "format":"json","options":{"temperature":0}}).encode()
    req=urllib.request.Request(OLLAMA,data=body,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=90) as r:
        d=json.load(r)
    return (d.get("response") or d.get("thinking") or ""),d

def claim(c,worker,count,lease_seconds=600):
    from datetime import timedelta
    t=datetime.now(timezone.utc)
    expiry=(t+timedelta(seconds=lease_seconds)).isoformat()
    c.execute("BEGIN IMMEDIATE")
    rows=c.execute("""select s.id,s.content,a.source_entity_id,a.source_ref
      from distillation_segments s
      join distillation_artifacts a on a.id=s.artifact_id
      join entities e on e.id=a.source_entity_id
      where (s.status='pending'
         or (s.status='leased' and (s.lease_until is null or s.lease_until<?)))
        and e.tags like '%"user"%'
      order by s.priority desc,
               cast(json_extract(e.metadata,'$.create_time') as real) desc,
               s.ordinal asc limit ?""",(t.isoformat(),count)).fetchall()
    for r in rows:
        c.execute("""update distillation_segments set status='leased',lease_owner=?,
          lease_until=?,attempts=attempts+1,updated_at=? where id=?""",
          (worker,expiry,t.isoformat(),r["id"]))
    c.commit()
    return rows
def persist_raw(c,seg,worker,model,raw,meta):
    wid=hid("work",seg["id"],worker,model,str(meta.get("created_at","")))
    ts=now()
    c.execute("""insert or replace into distillation_claim_work(
      id,segment_id,extractor,raw_record,validation_status,salvage_state,
      attempts,last_error,created_at,updated_at)
      values(?,?,?,?,?,'none',0,NULL,?,?)""",
      (wid,seg["id"],model,raw,"pending",ts,ts))
    c.commit()
    return wid

def materialize(c,wid,seg,records,model):
    ts=now(); n=0
    for rec in records:
        ev=[seg["source_entity_id"]]
        rec["evidence_ids"]=ev
        payload=json.dumps(rec,sort_keys=True,ensure_ascii=False)
        cid=hid("distcand",seg["id"],payload)
        c.execute("""insert or ignore into distillation_candidates(
          id,run_id,kind,subject,predicate,object,literal,confidence,
          evidence_ids,status,created_at) values(?,?,?,?,?,?,?,?,?,'candidate',?)""",
          (cid,"streaming-worker",rec.get("kind",""),rec.get("subject",""),
           rec.get("predicate",""),rec.get("object"),rec.get("literal"),
           min(.90,max(0,float(rec.get("confidence",0)))),
           json.dumps(ev),ts))
        c.execute("""update distillation_claim_work set candidate_id=coalesce(candidate_id,?),
          updated_at=? where id=?""",(cid,ts,wid))
        n+=1
    return n
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--count",type=int,default=5)
    ap.add_argument("--model",default=MODEL_DEFAULT)
    ap.add_argument("--worker",default=socket.gethostname()+"-local")
    args=ap.parse_args()

    import distillation_salvage as salv
    with closing(sqlite3.connect(DB)) as c:
        c.row_factory=sqlite3.Row
        segs=claim(c,args.worker,args.count)
        stats={"worker":args.worker,"claimed":len(segs),"done":0,"repair":0,
               "model_errors":0,"candidates":0}
        for seg in segs:
            try:
                raw,meta=ollama(PROMPT+"\nEVIDENCE_ID: "+seg["source_entity_id"]+
                                "\nSOURCE: "+str(seg["source_ref"] or "")+
                                "\nTEXT:\n"+seg["content"],args.model)
                meta["created_at"]=now()
                wid=persist_raw(c,seg,args.worker,args.model,raw,meta)
                salv.process_work(c,wid)
                row=c.execute("select parsed_record,validation_status from distillation_claim_work where id=?",(wid,)).fetchone()
                if row["validation_status"] in ("salvaged","empty_valid"):
                    records=json.loads(row["parsed_record"] or '{"items":[]}').get("items",[])
                    stats["candidates"]+=materialize(c,wid,seg,records,args.model)
                    c.execute("""update distillation_segments set status='done',lease_owner=null,
                      lease_until=null,last_model=?,last_error=null,updated_at=? where id=? and lease_owner=?""",
                      (args.model,now(),seg["id"],args.worker))
                    stats["done"]+=1
                else:
                    c.execute("""update distillation_segments set status='repair',lease_owner=null,
                      lease_until=null,last_model=?,last_error='salvage exhausted',updated_at=?
                      where id=? and lease_owner=?""",(args.model,now(),seg["id"],args.worker))
                    stats["repair"]+=1
            except Exception as exc:
                c.execute("""update distillation_segments set status='pending',lease_owner=null,
                  lease_until=null,last_model=?,last_error=?,updated_at=?
                  where id=? and lease_owner=?""",(args.model,str(exc)[:1000],now(),seg["id"],args.worker))
                stats["model_errors"]+=1
            c.commit()
        print(json.dumps(stats,indent=2))

if __name__=="__main__":
    main()
