#!/usr/bin/env python3
import hashlib,json,re,sqlite3
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"

STOP=set("""
the and for with from that this have your you are our but not can will into about what when
how why then than use using need needs should could would just also very more some all one two
three chatgpt aineko user assistant proceed next there work good other please where like able
make still know these which want them null content_type text really right okay ok yes yeah
well now much been being does did doing had has get got going thing things something anything
everything way ways even only over under again already actually perhaps maybe current currently direction review issues
""".split())
DOMAIN_HINTS={
 "nemosyne","moneta","agalmic","attention","ontology","memory","goms","manfred","obsidian",
 "notion","capability","scarcity","autonomy","autonomous","provenance","evidence","project",
 "objective","decision","constraint","blocker","compute","research","representation","semantic",
 "graph","knowledge","agent","worker","verification","hardware","simulation","publication",
 "abundance","cognition","epistemic","interface","control","roadmap","security","architecture",
 "performance","dataset","visualization","embeddings","embedding","replication","yoda","audio_transcription","decoding_id","content_type"
}

def now(): return datetime.now(timezone.utc).isoformat()
def pid(kind,name): return "onto_prop_"+hashlib.sha256((kind+"|"+name).encode()).hexdigest()[:20]
def tokens(text):
    out=[]
    for w in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{3,}",text or ""):
        w=w.lower().strip("._-")
        if w and w not in STOP and w not in {"audio_transcription","decoding_id","content_type"} and not w.isdigit():
            out.append(w)
    return out

with sqlite3.connect(DB) as c:
    c.row_factory=sqlite3.Row
    rows=c.execute("""select summary,source from entities
                      where type='evidence' and tags like '%\"user\"%'
                      and source like 'chatgpt://conversation/%/message/%'""").fetchall()
    unigram=Counter(); bigram=Counter(); examples=defaultdict(list)
    for r in rows:
        toks=tokens(r["summary"])
        uniq=set(toks)
        for w in uniq:
            unigram[w]+=1
            if len(examples[w])<3: examples[w].append(r["source"])
        for a,b in set(zip(toks,toks[1:])):
            if a!=b:
                bigram[f"{a} {b}"]+=1

    ts=now()
    # Re-score rather than auto-promote. High recurrence alone is not enough.
    proposals=[]
    for name,count in unigram.items():
        if count<8: continue
        domain_bonus=0.18 if name in DOMAIN_HINTS else 0.0
        confidence=min(0.92,0.18 + min(count,20)*0.02 + domain_bonus)
        if confidence<0.5: continue
        proposals.append((name,count,confidence,"concept"))
    for name,count in bigram.items():
        if count<5: continue
        a,b=name.split(" ",1)
        domain_bonus=0.22 if (a in DOMAIN_HINTS or b in DOMAIN_HINTS) else 0.0
        confidence=min(0.94,0.24 + min(count,15)*0.025 + domain_bonus)
        if confidence<0.55: continue
        proposals.append((name,count,confidence,"concept_phrase"))

    keep=set()
    for name,count,confidence,ptype in sorted(proposals,key=lambda x:(-x[2],-x[1]))[:250]:
        keep.add((ptype,name))
        rationale=f"Recurring semantically filtered term across {count} user-authored evidence items."
        meta=json.dumps({"example_sources":examples.get(name,[])},sort_keys=True)
        c.execute("""insert into ontology_proposals
          (id,proposal_type,canonical_name,description,evidence_count,confidence,status,rationale,metadata,created_at,updated_at)
          values(?,?,?,?,?,?,?,?,?,?,?)
          on conflict(proposal_type,canonical_name) do update set
            evidence_count=excluded.evidence_count,confidence=excluded.confidence,
            rationale=excluded.rationale,metadata=excluded.metadata,updated_at=excluded.updated_at""",
          (pid(ptype,name),ptype,name,"Candidate semantic concept",count,confidence,
           "candidate",rationale,meta,ts,ts))
    # Retire low-value lexical candidates from the earlier naive pass without deleting provenance.
    for row in c.execute("select proposal_type,canonical_name from ontology_proposals where status='candidate'").fetchall():
        key=(row["proposal_type"],row["canonical_name"])
        if key not in keep and row["proposal_type"] in ("concept","concept_phrase"):
            c.execute("update ontology_proposals set status='retired',updated_at=? where proposal_type=? and canonical_name=?",
                      (ts,*key))
    c.commit()
    print(json.dumps({
      "active_candidates":c.execute("select count(*) from ontology_proposals where status='candidate'").fetchone()[0],
      "retired":c.execute("select count(*) from ontology_proposals where status='retired'").fetchone()[0]
    },indent=2))
