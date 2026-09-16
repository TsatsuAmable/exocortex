#!/usr/bin/env python3
from contextlib import closing
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(os.environ.get('GOMS_ROOT', Path.home() / 'Library/Application Support/Aineko/GOMS'))
DB = Path(os.environ.get('GOMS_DB', ROOT / 'goms.sqlite3'))
HOST = os.environ.get('GOMS_QUEUE_HOST', '100.109.209.29')
PORT = int(os.environ.get('GOMS_QUEUE_PORT', '8767'))
ALLOWED = {x.strip() for x in os.environ.get('GOMS_QUEUE_ALLOWED', '100.109.209.29,100.66.115.49,127.0.0.1').split(',') if x.strip()}

def now():
    return datetime.now(timezone.utc)

def iso(dt=None):
    return (dt or now()).isoformat()

def hid(prefix, *parts):
    text = '|'.join(str(x) for x in parts)
    return prefix + '_' + hashlib.sha256(text.encode()).hexdigest()[:24]

def segment_status_for_recovered(recovered):
    return 'done' if recovered != 0 else 'repair'

def claim(worker, count, *, db_path=DB, privacy_scope='private', lease_seconds=600):
    if privacy_scope not in {'private', 'non_sensitive'}:
        raise ValueError(f'unsupported privacy scope: {privacy_scope}')
    with closing(sqlite3.connect(db_path)) as c:
        c.row_factory = sqlite3.Row
        c.execute('BEGIN IMMEDIATE')
        expiry = iso(now() + timedelta(seconds=lease_seconds))
        privacy_sql = "" if privacy_scope == 'private' else "and coalesce(json_extract(s.metadata,'$.privacy'),json_extract(a.metadata,'$.privacy'))='non_sensitive'"
        sql = f'''select s.id,s.content,s.content_sha256,a.source_entity_id,a.source_ref,
          coalesce(json_extract(s.metadata,'$.privacy'),json_extract(a.metadata,'$.privacy')) as privacy
          from distillation_segments s
          join distillation_artifacts a on a.id=s.artifact_id
          join entities e on e.id=a.source_entity_id
          where (s.status='pending' or (s.status='leased' and (s.lease_until is null or s.lease_until<?)))
            and exists (select 1 from json_each(e.tags) where value='chatgpt')
            and exists (select 1 from json_each(e.tags) where value='message')
            and exists (select 1 from json_each(e.tags) where value='user')
            {privacy_sql}
          order by s.priority desc,s.ordinal asc limit ?'''
        rows = c.execute(sql, (iso(), max(1, min(50, int(count))))).fetchall()
        out = []
        for row in rows:
            c.execute('''update distillation_segments set status='leased',lease_owner=?,lease_until=?,
              attempts=attempts+1,updated_at=? where id=?''', (worker, expiry, iso(), row['id']))
            out.append(dict(row))
        c.commit()
        return out

def release(worker, segment_id, error=None, *, db_path=DB):
    with closing(sqlite3.connect(db_path)) as c:
        cur = c.execute("update distillation_segments set status='pending',lease_owner=null, lease_until=null,last_error=?,updated_at=? where id=? and lease_owner=?",
                        ((error or '')[:1000] or None, iso(), segment_id, worker))
        c.commit()
        return cur.rowcount == 1

def submit(worker, segment_id, extractor, raw, *, db_path=DB):
    from distillation_salvage import process_work
    with closing(sqlite3.connect(db_path)) as c:
        c.row_factory = sqlite3.Row
        row = c.execute('select lease_owner from distillation_segments where id=?', (segment_id,)).fetchone()
        if not row or row['lease_owner'] != worker:
            return {'ok': False, 'error': 'lease_not_owned'}, 409
        ts = iso()
        wid = hid('claimwork', segment_id, worker, extractor, hashlib.sha256(raw.encode()).hexdigest())
        c.execute('''insert or ignore into distillation_claim_work(
          id,segment_id,extractor,raw_record,validation_status,salvage_state,attempts,created_at,updated_at)
          values(?,?,?,?,'pending','none',0,?,?)''', (wid, segment_id, extractor, raw, ts, ts))
        recovered = process_work(c, wid)
        candidate_ids = []
        if recovered > 0:
            seg = c.execute('''select a.source_entity_id from distillation_segments s
              join distillation_artifacts a on a.id=s.artifact_id where s.id=?''', (segment_id,)).fetchone()
            work = c.execute('select parsed_record from distillation_claim_work where id=?', (wid,)).fetchone()
            try:
                items = json.loads(work['parsed_record'] or '{}').get('items', [])
            except Exception:
                items = []
            for item in items:
                item['evidence_ids'] = [seg['source_entity_id']]
                payload = json.dumps(item, sort_keys=True, ensure_ascii=False)
                cid = hid('distcand', segment_id, payload)
                c.execute('''insert or ignore into distillation_candidates(
                  id,run_id,kind,subject,predicate,object,literal,confidence,evidence_ids,status,created_at)
                  values(?,?,?,?,?,?,?,?,?,'candidate',?)''',
                  (cid, 'streaming-worker', item.get('kind',''), item.get('subject',''), item.get('predicate',''),
                   item.get('object'), item.get('literal'), min(.90,max(0,float(item.get('confidence',0)))),
                   json.dumps([seg['source_entity_id']]), ts))
                candidate_ids.append(cid)
            if candidate_ids:
                c.execute('update distillation_claim_work set candidate_id=? where id=?', (candidate_ids[0], wid))
        status = segment_status_for_recovered(recovered)
        c.execute('''update distillation_segments set status=?,lease_owner=null,lease_until=null,
          last_model=?,last_error=?,updated_at=? where id=? and lease_owner=?''',
          (status, extractor, None if status == 'done' else 'no valid claims', ts, segment_id, worker))
        c.commit()
        return {'ok': True, 'work_id': wid, 'recovered': recovered, 'candidate_ids': candidate_ids, 'segment_status': status}, 200

class Handler(BaseHTTPRequestHandler):
    def sendj(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def auth(self):
        return self.client_address[0] in ALLOWED

    def do_GET(self):
        if not self.auth():
            return self.sendj(401, {'error': 'unauthorized'})
        if self.path == '/health':
            return self.sendj(200, {'status': 'ok'})
        return self.sendj(404, {'error': 'not_found'})

    def do_POST(self):
        if not self.auth():
            return self.sendj(401, {'error': 'unauthorized'})
        n = int(self.headers.get('Content-Length','0'))
        body = json.loads(self.rfile.read(n) or b'{}')
        if self.path == '/claim':
            scope = str(body.get('privacy_scope') or 'private')
            try:
                rows = claim(str(body.get('worker')), int(body.get('count',5)), privacy_scope=scope)
            except ValueError as exc:
                return self.sendj(400, {'error': str(exc)})
            return self.sendj(200, {'segments': rows})
        if self.path == '/release':
            ok = release(str(body.get('worker')), str(body.get('segment_id')), str(body.get('error') or ''))
            return self.sendj(200 if ok else 409, {'ok': ok, 'error': None if ok else 'lease_not_owned'})
        if self.path == '/submit':
            obj, code = submit(str(body.get('worker')), str(body.get('segment_id')),
                               str(body.get('extractor')), str(body.get('raw') or ''))
            return self.sendj(code, obj)
        return self.sendj(404, {'error': 'not_found'})

    def log_message(self, fmt, *args):
        pass

if __name__ == '__main__':
    print(f'queue server on {HOST}:{PORT}', flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
