#!/usr/bin/env python3
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from goms_store import GomsStore
from manfred_http import create_server


class ManfredHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="manfred-http-")
        self.root = Path(self.tmp.name)
        self.store = GomsStore(self.root)
        self.server = create_server(self.root, token="read-secret", authority_token="authority-secret", host="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()
    def request(self, path, *, method="GET", body=None, token=None):
        data = json.dumps(body).encode() if body is not None else None
        token = token or ("authority-secret" if method == "POST" else "read-secret")
        headers = {"Authorization": f"Bearer {token}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, json.load(response)

    def test_unauthorized_request_is_rejected(self):
        req = urllib.request.Request(self.base + "/v1/manfred/brief")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=3)
        self.assertEqual(ctx.exception.code, 401)
        ctx.exception.close()

    def test_authorized_brief_returns_canonical_state(self):
        self.store.create_branch("Blocked", "test", status="BLOCKED", blocker="human")
        status, body = self.request("/v1/manfred/brief")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["brief"]["branches"][0]["status"], "BLOCKED")
    def test_command_endpoint_executes_allowlisted_command(self):
        branch = self.store.create_branch("Active", "test", status="ACTIVE")
        command = {
            "idempotency_key": "http-cmd-1",
            "type": "checkpoint_branch",
            "target_id": branch,
            "payload": {"status": "PARKED", "summary": "Pause from Manfred"},
        }
        status, body = self.request("/v1/manfred/commands", method="POST", body=command)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(self.store.list_branches(project="test")[0]["status"], "PARKED")

    def test_unknown_route_returns_404(self):
        req = urllib.request.Request(
            self.base + "/v1/manfred/shell",
            headers={"Authorization": "Bearer read-secret"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=3)
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()

    def test_post_requires_distinct_authority_token(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)
        self.server = create_server(self.root, token="read-secret", authority_token="authority-secret", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        port = self.server.server_address[1]
        data = json.dumps({"idempotency_key":"authz-1","type":"resolve_attention",
                           "target_id":"missing","payload":{}}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/manfred/commands", data=data,
              headers={"Authorization":"Bearer read-secret","Content-Type":"application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=2)
        self.assertEqual(ctx.exception.code, 401); ctx.exception.close()



if __name__ == "__main__":
    unittest.main(verbosity=2)
