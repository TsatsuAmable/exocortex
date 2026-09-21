#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,hmac,json,os,sqlite3
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from autopilot import tick
from delivery import DB_PATH,now
EVENTS={'pull_request','pull_request_review','check_run','check_suite','workflow_run'}
SCHEMA='CREATE TABLE IF NOT EXISTS github_events(delivery_id TEXT PRIMARY KEY,event TEXT NOT NULL,repo TEXT NOT NULL,received_at TEXT NOT NULL,payload_sha256 TEXT NOT NULL)'
def verify(secret,body,supplied):
 if not supplied.startswith('sha256='): return False
 return hmac.compare_digest('sha256='+hmac.new(secret,body,hashlib.sha256).hexdigest(),supplied)
def accept(db,did,event,repo,body):
 db.parent.mkdir(parents=True,exist_ok=True)
 with sqlite3.connect(db) as con:
  con.execute(SCHEMA)
  try: con.execute('INSERT INTO github_events VALUES(?,?,?,?,?)',(did,event,repo,now(),hashlib.sha256(body).hexdigest()))
  except sqlite3.IntegrityError: return False
 return True
def handler(secret,db):
 class H(BaseHTTPRequestHandler):
  def log_message(self,*a): pass
  def reply(self,n,obj):
   raw=json.dumps(obj).encode(); self.send_response(n); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
  def do_POST(self):
   if self.path!='/github': return self.reply(404,{'error':'not_found'})
   body=self.rfile.read(int(self.headers.get('Content-Length','0')))
   if not verify(secret,body,self.headers.get('X-Hub-Signature-256','')): return self.reply(401,{'error':'bad_signature'})
   event=self.headers.get('X-GitHub-Event',''); did=self.headers.get('X-GitHub-Delivery','')
   if event=='ping': return self.reply(200,{'ok':True})
   if event not in EVENTS or not did: return self.reply(202,{'ignored':True})
   try: repo=((json.loads(body).get('repository') or {}).get('full_name') or '').strip()
   except Exception: return self.reply(400,{'error':'bad_json'})
   if not repo: return self.reply(400,{'error':'missing_repo'})
   if not accept(db,did,event,repo,body): return self.reply(200,{'ok':True,'duplicate':True})
   try: result=tick(repo)
   except Exception as exc: return self.reply(202,{'accepted':True,'error':str(exc)})
   return self.reply(200,{'ok':True,'result':result})
 return H
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--host',default='127.0.0.1'); ap.add_argument('--port',type=int,default=8798); ap.add_argument('--db',type=Path,default=Path(os.environ.get('AINEKO_WEBHOOK_DB', str(DB_PATH.parent / 'github-events.sqlite3')))); a=ap.parse_args(); secret=os.environ.get('GITHUB_WEBHOOK_SECRET','').encode()
 if not secret: raise SystemExit('GITHUB_WEBHOOK_SECRET is required')
 ThreadingHTTPServer((a.host,a.port),handler(secret,a.db)).serve_forever()
if __name__=='__main__': main()
