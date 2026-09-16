#!/usr/bin/env python3
from contextlib import closing
import argparse, json, sqlite3, socket, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path.home()/"Library/Application Support/Aineko/GOMS"
DB=ROOT/"goms.sqlite3"

def now(): return datetime.now(timezone.utc)
def iso(dt): return dt.isoformat()

def claim(c,worker,count,lease_seconds=600):
    c.execute("BEGIN IMMEDIATE")
    expiry=iso(now()+timedelta(seconds=lease_seconds))
    rows=c.execute("""select id from distillation_segments
      where status='pending'
         or (status='leased' and (lease_until is null or lease_until<?))
      order by priority desc,ordinal asc limit ?""",(iso(now()),count)).fetchall()
    ids=[r[0] for r in rows]
    for sid in ids:
        c.execute("""update distillation_segments
          set status='leased',lease_owner=?,lease_until=?,attempts=attempts+1,updated_at=?
          where id=?""",(worker,expiry,iso(now()),sid))
    c.commit()
    return ids

def release(c,worker,ids):
    for sid in ids:
        c.execute("""update distillation_segments set status='pending',
          lease_owner=null,lease_until=null,updated_at=?
          where id=? and lease_owner=?""",(iso(now()),sid,worker))
    c.commit()

def complete(c,worker,sid,model=None):
    c.execute("""update distillation_segments set status='done',
      lease_owner=null,lease_until=null,last_model=?,updated_at=?
      where id=? and lease_owner=?""",(model,iso(now()),sid,worker))
    c.commit()
    return c.total_changes

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("action",choices=["claim","release","complete","stats"])
    ap.add_argument("--worker",default=f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}")
    ap.add_argument("--count",type=int,default=10)
    ap.add_argument("--ids",nargs="*")
    ap.add_argument("--model")
    args=ap.parse_args()
    with closing(sqlite3.connect(DB)) as c:
        if args.action=="claim":
            print(json.dumps({"worker":args.worker,"ids":claim(c,args.worker,args.count)},indent=2))
        elif args.action=="release":
            release(c,args.worker,args.ids or []); print("released")
        elif args.action=="complete":
            for sid in args.ids or []: complete(c,args.worker,sid,args.model)
            print("completed")
        else:
            rows=dict(c.execute("select status,count(*) from distillation_segments group by status").fetchall())
            print(json.dumps(rows,indent=2))
