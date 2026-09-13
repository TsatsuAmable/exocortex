#!/usr/bin/env python3
import hashlib, json, sqlite3
from pathlib import Path
from goms_store import GomsStore

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
RAW=ROOT/"raw"/"chatgpt-live"
STATE=ROOT/"chatgpt_live_ingest.sqlite3"

def sid(prefix,value):
    return prefix+"_"+hashlib.sha256(value.encode()).hexdigest()[:24]

def init():
    c=sqlite3.connect(STATE)
    c.execute("create table if not exists snapshots(hash text primary key, conversation_id text, path text, ingested_at text default current_timestamp)")
    c.commit(); return c

def text_of(msg):
    content=(msg or {}).get("content") or {}
    parts=content.get("parts")
    if isinstance(parts,list):
        out=[]
        for p in parts:
            if isinstance(p,str): out.append(p)
            elif isinstance(p,dict): out.append(json.dumps(p,ensure_ascii=False,sort_keys=True))
        return "\n".join(out).strip()
    return str(content.get("text") or "").strip()

def ingest_snapshot(path, store):
    c=json.loads(path.read_text())
    cid=str(c.get("id") or c.get("conversation_id") or "")
    if not cid: raise ValueError("conversation missing id")
    title=str(c.get("title") or "Untitled ChatGPT conversation")
    snap=path.parent.name
    ceid=sid("chatgpt_conversation",cid)
    try:
        store.add_entity("source",title,summary="Raw ChatGPT conversation archive",
            source=f"chatgpt://conversation/{cid}",tags=["chatgpt","conversation","raw-archive"],
            metadata={"chatgpt_conversation_id":cid,"snapshot_sha256":snap,
              "raw_path":str(path),"update_time":c.get("update_time")},
            entity_id=ceid,actor="chatgpt-live-importer")
    except Exception as e:
        if "UNIQUE constraint failed" not in str(e): raise
    added=0
    for node_id,node in (c.get("mapping") or {}).items():
        msg=(node or {}).get("message")
        if not isinstance(msg,dict): continue
        txt=text_of(msg)
        if not txt: continue
        mid=str(msg.get("id") or node_id)
        role=str((msg.get("author") or {}).get("role") or "unknown")
        content_hash=hashlib.sha256(txt.encode()).hexdigest()
        meid=sid("chatgpt_message",mid+"|"+content_hash)
        try:
            store.add_entity("evidence",f"{role}: {txt[:240].replace(chr(10),' ')}"[:500],
              summary=txt,source=f"chatgpt://conversation/{cid}/message/{mid}",
              tags=["chatgpt","message",role],
              metadata={"chatgpt_message_id":mid,"chatgpt_conversation_id":cid,
                "role":role,"snapshot_sha256":snap,"content_sha256":content_hash,
                "create_time":msg.get("create_time"),"update_time":msg.get("update_time")},
              entity_id=meid,actor="chatgpt-live-importer")
            store.link(meid,"contained_in",ceid,evidence=f"chatgpt://conversation/{cid}",
                       actor="chatgpt-live-importer")
            added+=1
        except Exception as e:
            if "UNIQUE constraint failed" not in str(e): raise
    return cid,added

def main():
    state=init(); store=GomsStore(root=ROOT)
    seen={r[0] for r in state.execute("select hash from snapshots")}
    done=0; messages=0
    for p in sorted(RAW.glob("*/*/conversation.json")):
        snap=p.parent.name
        if snap in seen: continue
        cid,n=ingest_snapshot(p,store)
        state.execute("insert into snapshots(hash,conversation_id,path) values(?,?,?)",(snap,cid,str(p)))
        state.commit(); done+=1; messages+=n
    print(json.dumps({"snapshots_ingested":done,"messages_added":messages},indent=2))

if __name__=="__main__":
    main()
