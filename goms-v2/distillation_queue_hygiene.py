#!/usr/bin/env python3
from contextlib import closing
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"


def now(): return datetime.now(timezone.utc).isoformat()


def _ensure_schema(c):
    c.execute('''create table if not exists distillation_queue_hygiene_events(
      id text primary key,segment_id text not null,previous_status text not null,
      new_status text not null,reason text not null,observed_at text not null)''')


def apply_hygiene(c):
    _ensure_schema(c)
    eligible_statuses = ("pending", "repair")
    orphaned=c.execute('''select s.id,s.status from distillation_segments s
      left join distillation_artifacts a on a.id=s.artifact_id
      where s.status in ('pending','repair') and a.id is null''').fetchall()
    has_metadata=any(r[1]=='metadata' for r in c.execute("pragma table_info(entities)").fetchall())
    selftest_sql = " or coalesce(json_extract(e.metadata,'$.chatgpt_conversation_id'),'') like '%selftest%'" if has_metadata else ""
    ineligible=c.execute(f'''select s.id,s.status,
      case when not (
        exists(select 1 from json_each(e.tags) where value='chatgpt') and
        exists(select 1 from json_each(e.tags) where value='message') and
        exists(select 1 from json_each(e.tags) where value='user'))
      then 'not_chatgpt_user_message' else 'known_selftest_conversation' end reason
      from distillation_segments s
      join distillation_artifacts a on a.id=s.artifact_id
      join entities e on e.id=a.source_entity_id
      where s.status in ('pending','repair') and (
        not (
          exists(select 1 from json_each(e.tags) where value='chatgpt') and
          exists(select 1 from json_each(e.tags) where value='message') and
          exists(select 1 from json_each(e.tags) where value='user'))
        {selftest_sql})''').fetchall()
    ts=now()
    for sid,previous in orphaned:
        c.execute("insert or ignore into distillation_queue_hygiene_events values(?,?,?,?,?,?)",
                  (sid+':orphaned',sid,previous,'orphaned','missing_distillation_artifact',ts))
        c.execute("update distillation_segments set status='orphaned',last_error='missing_distillation_artifact',updated_at=? where id=? and status=?",(ts,sid,previous))
    for sid,previous,reason in ineligible:
        c.execute("insert or ignore into distillation_queue_hygiene_events values(?,?,?,?,?,?)",
                  (sid+':ineligible',sid,previous,'ineligible',reason,ts))
        c.execute("update distillation_segments set status='ineligible',last_error=?,updated_at=? where id=? and status=?",(reason,ts,sid,previous))
    c.commit()
    return {'ineligible':len(ineligible),'orphaned':len(orphaned)}


def main():
    with closing(sqlite3.connect(DB)) as c:
        result=apply_hygiene(c)
        print(json.dumps(result,sort_keys=True))


if __name__=='__main__': main()
