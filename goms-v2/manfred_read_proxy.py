#!/usr/bin/env python3
from __future__ import annotations
import argparse,ipaddress,json,os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from manfred_control import ManfredControl

LOOPBACK_HOSTS={"127.0.0.1","localhost","::1"}
TAILNET_V4=ipaddress.ip_network("100.64.0.0/10")

def _tailnet_ipv4(value):
    try:
        return ipaddress.ip_address(value) in TAILNET_V4
    except ValueError:
        return False

def validate_bind(host,allowed_client):
    if host in LOOPBACK_HOSTS:
        return
    if not (_tailnet_ipv4(host) and allowed_client and _tailnet_ipv4(allowed_client)):
        raise ValueError("remote read proxy requires tailnet host and explicit tailnet client")

def client_allowed(peer,allowed_client):
    return allowed_client is None or peer == allowed_client

class Server(ThreadingHTTPServer):
    def __init__(self,address,handler,*,root:Path,allowed_client=None):
        self.control=ManfredControl(root/"goms.sqlite3")
        self.allowed_client=allowed_client
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
    def _peer_ok(self):
        if client_allowed(self.client_address[0],self.server.allowed_client): return True
        self._json(403,{"ok":False,"error":"forbidden_client"}); return False
    def do_GET(self):
        if not self._peer_ok(): return
        if self.path!="/v1/manfred/brief":
            self._json(404,{"ok":False,"error":"not_found"}); return
        self._json(200,{"ok":True,"brief":self.server.control.build_brief()})
    def do_POST(self):
        if not self._peer_ok(): return
        self._json(405,{"ok":False,"error":"method_not_allowed"})

def create_server(root:str|Path,*,host:str="127.0.0.1",port:int=8794,allowed_client=None):
    validate_bind(host,allowed_client)
    return Server((host,int(port)),Handler,root=Path(root),allowed_client=allowed_client)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",default=os.environ.get("GOMS_HOME",str(Path.home()/"Library/Application Support/Aineko/GOMS")))
    ap.add_argument("--host",default="127.0.0.1")
    ap.add_argument("--port",type=int,default=8794)
    ap.add_argument("--allowed-client")
    args=ap.parse_args()
    server=create_server(args.root,host=args.host,port=args.port,allowed_client=args.allowed_client)
    print(json.dumps({"listening":f"{args.host}:{args.port}","mode":"read-only"}),flush=True)
    server.serve_forever()

if __name__=="__main__": main()
