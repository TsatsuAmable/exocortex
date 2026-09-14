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


class ManfredTailnetBindTests(unittest.TestCase):
    def test_tailnet_bind_requires_explicit_tailnet_client(self):
        from manfred_read_proxy import validate_bind
        validate_bind("127.0.0.1", None)
        with self.assertRaises(ValueError):
            validate_bind("100.109.209.29", None)
        validate_bind("100.109.209.29", "100.73.215.97")

    def test_non_tailnet_addresses_are_rejected(self):
        from manfred_read_proxy import validate_bind
        with self.assertRaises(ValueError):
            validate_bind("192.168.1.222", "100.73.215.97")
        with self.assertRaises(ValueError):
            validate_bind("100.109.209.29", "192.168.1.128")

    def test_remote_client_filter_is_exact(self):
        from manfred_read_proxy import client_allowed
        self.assertTrue(client_allowed("100.73.215.97", "100.73.215.97"))
        self.assertFalse(client_allowed("100.66.115.49", "100.73.215.97"))

if __name__=="__main__": unittest.main(verbosity=2)


class ManfredProjectionEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="manfred-projection-proxy-")
        self.root=Path(self.tmp.name)
        self.store=GomsStore(self.root)
        self.server=create_server(self.root,host="127.0.0.1",port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)
        self.tmp.cleanup()

    def post(self, path, payload: bytes):
        req=urllib.request.Request(self.base+path,data=payload,method="POST",
                                   headers={"Content-Type":"application/json"})
        return urllib.request.urlopen(req,timeout=3)

    def test_projection_post_returns_schema_1_without_mutating_attention(self):
        ts="2026-09-14T15:00:00+00:00"
        with self.store.connect() as con:
            con.execute("""INSERT INTO attention_items
              (id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              VALUES('attn_readonly','test','warning','Read only','x','open','[]','test',?,?)""",(ts,ts))
        caps={"ui_schema_versions":["1.0"],"components":["summary","decision","generic_object"],"actions":["ASK_CHATGPT"]}
        with self.post("/v1/manfred/projection",json.dumps(caps).encode()) as r:
            body=json.load(r)
        self.assertTrue(body["ok"]); self.assertEqual(body["projection"]["schema_version"],"1.0")
        with self.store.connect() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM control_intents").fetchone()[0],0)

    def test_projection_post_rejects_malformed_and_oversized_bodies(self):
        with self.assertRaises(urllib.error.HTTPError) as malformed:
            self.post("/v1/manfred/projection",b"{")
        self.assertEqual(malformed.exception.code,400); malformed.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as oversized:
            self.post("/v1/manfred/projection",b"x"*(32*1024+1))
        self.assertEqual(oversized.exception.code,413); oversized.exception.close()

    def test_other_post_routes_remain_method_not_allowed(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/v1/manfred/commands",b"{}")
        self.assertEqual(ctx.exception.code,405); ctx.exception.close()

    def test_wrong_peer_is_forbidden_before_projection(self):
        other=create_server(self.root,host="127.0.0.1",port=0,allowed_client="127.0.0.2")
        thread=threading.Thread(target=other.serve_forever,daemon=True); thread.start()
        base=f"http://127.0.0.1:{other.server_address[1]}"
        try:
            req=urllib.request.Request(base+"/v1/manfred/projection",data=b"{}",method="POST")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req,timeout=3)
            self.assertEqual(ctx.exception.code,403); ctx.exception.close()
        finally:
            other.shutdown(); other.server_close(); thread.join(2)
