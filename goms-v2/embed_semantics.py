#!/usr/bin/env python3
from contextlib import closing
import array,hashlib,json,sqlite3,urllib.request
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"
MODEL="nomic-embed-text"

def now(): return datetime.now(timezone.utc).isoformat()
def embed(text):
    body=json.dumps({"model":MODEL,"input":text}).encode()
    req=urllib.request.Request("http://127.0.0.1:11434/api/embed",data=body,
        headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=60) as r:
        return json.load(r)["embeddings"][0]
def store(c,kind,target_id,text):
    h=hashlib.sha256(text.encode()).hexdigest()
    row=c.execute("""select content_sha256 from semantic_embeddings
                     where target_kind=? and target_id=? and model=?""",
                  (kind,target_id,MODEL)).fetchone()
    if row and row[0]==h: return False
    v=embed(text); blob=array.array("f",v).tobytes(); ts=now()
    c.execute("""insert into semantic_embeddings
      (target_kind,target_id,model,content_sha256,dimensions,vector_blob,created_at,updated_at)
      values(?,?,?,?,?,?,?,?)
      on conflict(target_kind,target_id,model) do update set
      content_sha256=excluded.content_sha256,dimensions=excluded.dimensions,
      vector_blob=excluded.vector_blob,updated_at=excluded.updated_at""",
      (kind,target_id,MODEL,h,len(v),blob,ts,ts))
    return True

with closing(sqlite3.connect(DB)) as c, c:
    changed=0
    for r in c.execute("""select id,type,title,summary from entities
                          where type not in ('evidence','source')""").fetchall():
        changed+=int(store(c,"entity",r[0],f"{r[1]}\n{r[2]}\n{r[3] or ''}"))
    for r in c.execute("""select id,title,objective,last_result,next_action,blocker from branches""").fetchall():
        changed+=int(store(c,"branch",r[0],"\n".join(str(x or "") for x in r[1:])))
    for r in c.execute("""select id,kind,canonical_name,description from ontology_terms where status='active'""").fetchall():
        changed+=int(store(c,"ontology_term",r[0],f"{r[1]}\n{r[2]}\n{r[3] or ''}"))
    for r in c.execute("""select id,proposal_type,canonical_name,description,rationale
                          from ontology_proposals
                          where status='candidate' and confidence>=0.6""").fetchall():
        changed+=int(store(c,"ontology_proposal",r[0],"\n".join(str(x or "") for x in r[1:])))
    c.commit()
    print(json.dumps({
      "changed":changed,
      "total":c.execute("select count(*) from semantic_embeddings where model=?",(MODEL,)).fetchone()[0]
    },indent=2))
