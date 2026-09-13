#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, os, sqlite3, urllib.request
from pathlib import Path
from goms_store import GomsStore

ROOT=Path(__file__).resolve().parent
STATE=ROOT/"manfred_sync.sqlite3"

def stable_id(prefix, value):
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:24]}"

def init_state():
    con=sqlite3.connect(STATE)
    con.execute("create table if not exists cursor(name text primary key, seq integer not null)")
    con.commit(); return con

def get_cursor(con):
    row=con.execute("select seq from cursor where name='manfred'").fetchone()
    return int(row[0]) if row else 0

def set_cursor(con, seq):
    con.execute("insert into cursor(name,seq) values('manfred',?) on conflict(name) do update set seq=excluded.seq",(int(seq),))
    con.commit()

def fetch_events(base_url, since, limit=200):
    url=f"{base_url.rstrip('/')}/v1/goms/events?since={since}&limit={limit}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)

def project(store, event):
    eid=stable_id("manfred_event", str(event["id"]))
    title=f"{event.get('kind','event')}: {event.get('summary','')}"[:500]
    meta={
        "manfred_seq":event.get("seq"),
        "manfred_event_id":event.get("id"),
        "at":event.get("at"),
        "kind":event.get("kind"),
        "status":event.get("status"),
        "subject_type":event.get("subject_type"),
        "subject_id":event.get("subject_id"),
        "payload":event.get("payload") or {},
    }
    try:
        store.add_entity(
            "evidence", title,
            summary=event.get("summary") or "",
            status=event.get("status"),
            source=f"manfred://event/{event.get('id')}",
            tags=["manfred", str(event.get("kind") or "event")],
            metadata=meta,
            entity_id=eid,
            actor="manfred-sync",
        )
        return True
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            return False
        raise

def sync_once(base_url):
    store=GomsStore()
    con=init_state()
    since=get_cursor(con)
    data=fetch_events(base_url, since)
    added=0; max_seq=since
    for event in data.get("events",[]):
        added += 1 if project(store,event) else 0
        max_seq=max(max_seq,int(event.get("seq") or 0))
    if max_seq>since:
        set_cursor(con,max_seq)
    con.close()
    return {"from":since,"to":max_seq,"added":added,"revision":data.get("revision")}

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--base-url",required=True)
    args=ap.parse_args()
    print(json.dumps(sync_once(args.base_url),indent=2))
