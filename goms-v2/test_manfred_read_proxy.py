#!/usr/bin/env python3
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from goms_store import GomsStore
from manfred_read_proxy import create_server

class ManfredReadProxyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="manfred-read-proxy-")
        self.root=Path(self.tmp.name)
        self.store=GomsStore(self.root)
        self.server=create_server(self.root,host="127.0.0.1",port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f"http://127.0.0.1:{self.server.server_address[1]}"
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)
        self.tmp.cleanup()
    def test_brief_is_exposed_read_only(self):
        self.store.create_branch("Blocked","test",status="BLOCKED",blocker="human")
        with urllib.request.urlopen(self.base+"/v1/manfred/brief",timeout=3) as r:
            body=json.load(r)
        self.assertTrue(body["ok"])
        self.assertEqual(body["brief"]["branches"][0]["status"],"BLOCKED")
        req=urllib.request.Request(self.base+"/v1/manfred/commands",data=b"{}",method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req,timeout=3)
        self.assertEqual(ctx.exception.code,405); ctx.exception.close()

    def test_unknown_route_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base+"/anything",timeout=3)
        self.assertEqual(ctx.exception.code,404); ctx.exception.close()

    def test_non_loopback_bind_is_rejected(self):
        with self.assertRaises(ValueError):
            create_server(self.root,host="0.0.0.0",port=0)

if __name__=="__main__": unittest.main(verbosity=2)
