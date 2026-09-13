#!/usr/bin/env python3
import fcntl
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("GOMS_HOME", MODULE_ROOT)).expanduser().resolve()
DB = ROOT / "goms.sqlite3"
LEDGER = ROOT / "events.jsonl"
SCHEMA = MODULE_ROOT / "schema.sql"
ENTITY_TYPES = {
    "project", "research_question", "claim", "evidence", "source", "decision",
    "artefact", "experiment", "task", "scarcity", "capability", "failure",
    "lesson", "procedure", "worker", "compute_resource", "idea", "person",
    "tool", "agent", "checkpoint", "machine", "service", "bridge", "routine",
    "data_store", "interface", "committee", "resource"
}
BRANCH_STATUSES = {"ACTIVE", "PARKED", "DELEGATED", "BLOCKED", "CONCLUDED"}

def now():
    return datetime.now(timezone.utc).isoformat()

def make_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def _canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def _last_line_hash(path):
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell() - 1
        while pos >= 0:
            f.seek(pos)
            b = f.read(1)
            if b not in (b"\n", b"\r"):
                break
            pos -= 1
        end = pos + 1
        while pos >= 0:
            f.seek(pos)
            if f.read(1) == b"\n":
                pos += 1
                break
            pos -= 1
        start = max(0, pos)
        f.seek(start)
        line = f.read(end - start)
    return hashlib.sha256(line).hexdigest() if line else None

def source_hash(source):
    if not source:
        return None
    p = Path(source).expanduser()
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

class GomsStore:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.db = self.root / "goms.sqlite3"
        self.ledger = self.root / "events.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self):
        con = sqlite3.connect(self.db, timeout=30)
        con.row_factory = sqlite3.Row
        con.executescript(SCHEMA.read_text())
        return con

    def init(self):
        with self.connect():
            pass
        self.ledger.touch(exist_ok=True)

    def append_event(self, event):
        event = dict(event)
        event.setdefault("event_id", make_id("event"))
        event.setdefault("at", now())
        with self.ledger.open("a+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            prev = _last_line_hash(self.ledger)
            event["prev_line_sha256"] = prev
            event["event_sha256"] = hashlib.sha256(_canonical_bytes(event)).hexdigest()
            f.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
            f.flush(); os.fsync(f.fileno())
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return event

    def add_entity(self, entity_type, title, summary="", project=None, status=None,
                   confidence=None, source=None, tags=None, metadata=None,
                   entity_id=None, actor=None):
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"Unknown entity type: {entity_type}")
        eid, ts = entity_id or make_id(entity_type), now()
        meta = dict(metadata or {})
        if actor: meta.setdefault("actor", actor)
        row = {
            "id": eid, "type": entity_type, "title": title, "summary": summary,
            "project": project, "status": status, "confidence": confidence,
            "source": source, "source_hash": source_hash(source),
            "tags": json.dumps(tags or []), "metadata": json.dumps(meta),
            "created_at": ts, "updated_at": ts,
        }
        with self.connect() as con:
            con.execute("""
              INSERT INTO entities(id,type,title,summary,project,status,confidence,source,
                source_hash,tags,metadata,created_at,updated_at)
              VALUES(:id,:type,:title,:summary,:project,:status,:confidence,:source,
                :source_hash,:tags,:metadata,:created_at,:updated_at)
            """, row)
        self.append_event({"op": "add_entity", "actor": actor, "entity": row})
        return eid

    def link(self, src, relation, dst, evidence=None, actor=None):
        ts = now()
        with self.connect() as con:
            for eid in (src, dst):
                if not con.execute("SELECT 1 FROM entities WHERE id=?", (eid,)).fetchone():
                    raise KeyError(f"Unknown entity: {eid}")
            con.execute("INSERT OR REPLACE INTO relations(src,rel,dst,evidence,created_at) VALUES(?,?,?,?,?)",
                        (src, relation, dst, evidence, ts))
        self.append_event({"op": "add_relation", "actor": actor, "src": src,
                           "rel": relation, "dst": dst, "evidence": evidence})
        return {"src": src, "relation": relation, "dst": dst}

    def search(self, query, limit=20, project=None, entity_type=None):
        sql = """
          SELECT e.id,e.type,e.title,e.summary,e.project,e.status,e.confidence,e.source,e.tags
          FROM entities_fts f JOIN entities e ON e.rowid=f.rowid
          WHERE entities_fts MATCH ?
        """
        vals = [query]
        if project:
            sql += " AND e.project=?"; vals.append(project)
        if entity_type:
            sql += " AND e.type=?"; vals.append(entity_type)
        sql += " ORDER BY bm25(entities_fts) LIMIT ?"; vals.append(limit)
        with self.connect() as con:
            try:
                rows = con.execute(sql, vals).fetchall()
            except sqlite3.OperationalError:
                like = f"%{query}%"
                rows = con.execute("""
                  SELECT id,type,title,summary,project,status,confidence,source,tags
                  FROM entities WHERE (title LIKE ? OR summary LIKE ?)
                  ORDER BY updated_at DESC LIMIT ?
                """, (like, like, limit)).fetchall()
        out = []
        for row in rows:
            item = dict(row); item["tags"] = json.loads(item.get("tags") or "[]")
            out.append(item)
        return out

    def get_entity(self, entity_id):
        with self.connect() as con:
            row = con.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
            if not row:
                raise KeyError(f"Unknown entity: {entity_id}")
            rels = con.execute("""
              SELECT src,rel,dst,evidence,created_at FROM relations
              WHERE src=? OR dst=? ORDER BY created_at
            """, (entity_id, entity_id)).fetchall()
        out = dict(row)
        out["tags"] = json.loads(out["tags"] or "[]")
        out["metadata"] = json.loads(out["metadata"] or "{}")
        out["relations"] = [dict(r) for r in rels]
        return out

    def create_branch(self, title, project=None, status="ACTIVE", objective="",
                      last_result="", unresolved=None, next_action="", blocker="",
                      parent=None, worker=None, branch_id=None, actor=None):
        status = status.upper()
        if status not in BRANCH_STATUSES:
            raise ValueError(f"Bad status: {status}")
        bid, ts = branch_id or make_id("branch"), now()
        with self.connect() as con:
            con.execute("""INSERT INTO branches
            (id,title,project,status,objective,last_result,unresolved,next_action,blocker,
             parent_branch,worker,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (bid,title,project,status,objective,last_result,json.dumps(unresolved or []),
             next_action,blocker,parent,worker,ts,ts))
        self.append_event({"op": "branch_create", "actor": actor, "id": bid,
                           "title": title, "project": project, "status": status})
        return bid

    def checkpoint(self, branch_id, status, summary, unresolved=None,
                   next_action="", blocker="", source=None, actor=None):
        status = status.upper()
        if status not in BRANCH_STATUSES:
            raise ValueError(f"Bad status: {status}")
        ts, cid = now(), make_id("checkpoint")
        provenance = {"source": source} if source else {}
        with self.connect() as con:
            if not con.execute("SELECT 1 FROM branches WHERE id=?", (branch_id,)).fetchone():
                raise KeyError(f"Unknown branch: {branch_id}")
            con.execute("""INSERT INTO checkpoints
            (id,branch_id,status,summary,unresolved,next_action,blocker,provenance,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (cid,branch_id,status,summary,json.dumps(unresolved or []),next_action,
             blocker,json.dumps(provenance),ts))
            con.execute("""UPDATE branches SET status=?,last_result=?,unresolved=?,
            next_action=?,blocker=?,updated_at=? WHERE id=?""",
            (status,summary,json.dumps(unresolved or []),next_action,blocker,ts,branch_id))
        self.append_event({"op": "checkpoint", "actor": actor, "id": cid,
                           "branch": branch_id, "status": status,
                           "summary": summary, "next_action": next_action})
        return cid

    def list_branches(self, status=None, project=None):
        where, vals = [], []
        if status:
            where.append("status=?"); vals.append(status.upper())
        if project:
            where.append("project=?"); vals.append(project)
        sql = "SELECT id,title,project,status,objective,last_result,unresolved,next_action,blocker,parent_branch,worker,updated_at FROM branches"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY CASE status WHEN 'ACTIVE' THEN 0 WHEN 'BLOCKED' THEN 1 WHEN 'DELEGATED' THEN 2 WHEN 'PARKED' THEN 3 ELSE 4 END, updated_at DESC"
        with self.connect() as con:
            rows = [dict(r) for r in con.execute(sql, vals).fetchall()]
        for row in rows:
            row["unresolved"] = json.loads(row.get("unresolved") or "[]")
        return rows

    def project_state(self, project=None, query=None, limit=12):
        branches = self.list_branches(project=project)
        memories = self.search(query, limit=limit, project=project) if query else []
        return {"project": project, "branches": branches, "memories": memories}

    def stats(self):
        with self.connect() as con:
            types = [dict(r) for r in con.execute(
                "SELECT type,count(*) n FROM entities GROUP BY type ORDER BY n DESC").fetchall()]
            rels = [dict(r) for r in con.execute(
                "SELECT rel,count(*) n FROM relations GROUP BY rel ORDER BY n DESC").fetchall()]
            branches = [dict(r) for r in con.execute(
                "SELECT status,count(*) n FROM branches GROUP BY status ORDER BY n DESC").fetchall()]
        return {"entities": types, "relations": rels, "branches": branches}

    def recent_events(self, limit=50):
        if not self.ledger.exists():
            return []
        lines = self.ledger.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]
