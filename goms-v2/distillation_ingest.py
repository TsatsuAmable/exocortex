#!/usr/bin/env python3
from contextlib import closing
import hashlib, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"

def now(): return datetime.now(timezone.utc).isoformat()
def sha(x): return hashlib.sha256(x.encode()).hexdigest()
def sid(prefix,*parts):
    return prefix+"_"+hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]

def segment_text(text,max_chars=3500):
    text=text or ""
    if len(text)<=max_chars: return [(0,len(text),text)]
    out=[]; start=0
    while start<len(text):
        end=min(len(text),start+max_chars)
        if end<len(text):
            cut=max(text.rfind("\n\n",start,end),text.rfind(". ",start,end))
            if cut>start+max_chars//2: end=cut+1
        out.append((start,end,text[start:end]))
        start=end
    return out
with closing(sqlite3.connect(DB)) as c:
    c.row_factory=sqlite3.Row
    rows=c.execute("""select id,source,summary,metadata,created_at
                      from entities where type='evidence'
                      order by created_at asc""").fetchall()
    created_artifacts=created_segments=0
    for r in rows:
        text=r["summary"] or ""
        content_sha=sha(text)
        artifact_id=sid("artifact",r["id"],content_sha)
        ts=now()
        c.execute("""insert or ignore into distillation_artifacts(
          id,source_entity_id,source_ref,content_sha256,byte_count,status,metadata,created_at,updated_at)
          values(?,?,?,?,?,'ingested',?,?,?)""",
          (artifact_id,r["id"],r["source"],content_sha,len(text.encode()),
           json.dumps({"entity_created_at":r["created_at"],"entity_metadata":r["metadata"]}),
           ts,ts))
        if c.total_changes: created_artifacts+=1
        for ordinal,(start,end,content) in enumerate(segment_text(text)):
            seg_id=sid("segment",artifact_id,str(ordinal),sha(content))
            before=c.total_changes
            c.execute("""insert or ignore into distillation_segments(
              id,artifact_id,ordinal,start_offset,end_offset,content_sha256,content,status,
              metadata,created_at,updated_at)
              values(?,?,?,?,?,?,?,'pending','{}',?,?)""",
              (seg_id,artifact_id,ordinal,start,end,sha(content),content,ts,ts))
            if c.total_changes>before: created_segments+=1
    c.commit()
    print(json.dumps({
      "evidence_rows":len(rows),
      "created_artifacts":created_artifacts,
      "created_segments":created_segments,
      "artifacts_total":c.execute("select count(*) from distillation_artifacts").fetchone()[0],
      "segments_total":c.execute("select count(*) from distillation_segments").fetchone()[0]
    },indent=2))
