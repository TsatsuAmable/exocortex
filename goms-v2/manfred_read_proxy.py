#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from manfred_control import ManfredControl

LOOPBACK_HOSTS={"127.0.0.1","localhost","::1"}

class Server(ThreadingHTTPServer):
    def __init__(self,address,handler,*,root:Path):
        self.control=ManfredControl(root/"goms.sqlite3")
        super().__init__(address,handler)

class Handler(BaseHTTPRequestHandler):
    server:Server
    def log_message(self,*_): return
    def _json(self,status,payload):
        body=json.dumps(payload,sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path!="/v1/manfred/brief":
            self._json(404,{"ok":False,"error":"not_found"}); return
        self._json(200,{"ok":True,"brief":self.server.control.build_brief()})
    def do_POST(self):
        self._json(405,{"ok":False,"error":"method_not_allowed"})

def create_server(root:str|Path,*,host:str="127.0.0.1",port:int=8794):
    if host not in LOOPBACK_HOSTS:
        raise ValueError("read proxy must bind to loopback; expose with Tailscale Serve")
    return Server((host,int(port)),Handler,root=Path(root))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=os.environ.get("GOMS_HOME",str(Path.home()/"Library/Application Support/Aineko/GOMS")))
    ap.add_argument("--host",default="127.0.0.1")
    ap.add_argument("--port",type=int,default=8794)
    args=ap.parse_args()
    server=create_server(args.root,host=args.host,port=args.port)
    print(json.dumps({"listening":f"{args.host}:{args.port}","mode":"read-only"}),flush=True)
    server.serve_forever()

if __name__=="__main__": main()
