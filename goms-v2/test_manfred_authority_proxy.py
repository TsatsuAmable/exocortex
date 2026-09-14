#!/usr/bin/env python3
import base64
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from control_intents import ControlIntentService
from goms_store import GomsStore
from manfred_authority_proxy import (
    Handler,
    Ed25519SignatureVerifier,
    Server,
    load_public_key_file,
    validate_bind,
)


class ManfredAuthorityProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys_tmp = tempfile.TemporaryDirectory(prefix="manfred-authority-keys-")
        cls.key_root = Path(cls.keys_tmp.name)
        cls.private_key = Ed25519PrivateKey.generate()
        cls.public_key_file = cls.key_root / "authority-public.pem"
        cls.public_key_file.write_bytes(cls.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
        cls.public_key_file.chmod(0o600)

    @classmethod
    def tearDownClass(cls):
        cls.keys_tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="manfred-authority-")
        self.root = Path(self.tmp.name)
        self.store = GomsStore(self.root)
        verifier = Ed25519SignatureVerifier(self.public_key_file)
        self.server = Server(
            ("127.0.0.1", 0), Handler, root=self.root,
            allowed_client="127.0.0.1", verifier=verifier,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.tmp.cleanup()

    def signed(self, body, request_id="req-1", timestamp=None, corrupt=False):
        timestamp = str(timestamp or int(time.time()))
        raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        path = "/v1/manfred/intent-command"
        canonical = f"POST\n{path}\n{timestamp}\n{request_id}\n".encode() + raw
        signature_bytes = self.private_key.sign(canonical)
        if corrupt:
            signature_bytes = b"\x00" * len(signature_bytes)
        signature = base64.b64encode(signature_bytes).decode()
        return raw, {
            "Content-Type": "application/json",
            "X-Manfred-Request-Id": request_id,
            "X-Manfred-Timestamp": timestamp,
            "X-Manfred-Signature": signature,
        }

    def post(self, body, **kwargs):
        raw, headers = self.signed(body, **kwargs)
        req = urllib.request.Request(
            self.base + "/v1/manfred/intent-command",
            data=raw, headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.load(exc)
            finally:
                exc.close()

    def test_production_bind_requires_tailnet_host_and_exact_tailnet_client(self):
        with self.assertRaises(ValueError):
            validate_bind("192.168.1.10", "100.73.215.97")
        with self.assertRaises(ValueError):
            validate_bind("100.109.209.29", "192.168.1.128")
        validate_bind("100.109.209.29", "100.73.215.97")

    def test_public_key_file_must_be_private(self):
        public_key = self.root / "authority-public.pem"
        public_key.write_bytes(self.public_key_file.read_bytes())
        public_key.chmod(0o644)
        with self.assertRaises(ValueError):
            load_public_key_file(public_key)
        public_key.chmod(0o600)
        self.assertEqual(load_public_key_file(public_key), public_key)

    def test_wrong_peer_is_forbidden_before_auth(self):
        self.server.allowed_client = "100.73.215.97"
        status, body = self.post({"type": "approve_intent"})
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "forbidden_client")

    def test_missing_bad_stale_and_replayed_signatures_are_rejected(self):
        raw = b"{}"
        req = urllib.request.Request(
            self.base + "/v1/manfred/intent-command",
            data=raw, headers={"Content-Type": "application/json"}, method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(req, timeout=3)
        self.assertEqual(missing.exception.code, 401)
        missing.exception.close()

        status, body = self.post({"type": "approve_intent"}, request_id="bad-key", corrupt=True)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "bad_signature")
        stale = int(time.time()) - 1000
        status, body = self.post(
            {"type": "approve_intent"}, request_id="stale", timestamp=stale,
        )
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "stale_request")

        command = {
            "type": "approve_intent", "target_id": "missing",
            "idempotency_key": "replay", "payload": {"resolved_by": "human:test"},
        }
        first_status, _ = self.post(command, request_id="same-request")
        second_status, second = self.post(command, request_id="same-request")
        self.assertNotEqual(first_status, 401)
        self.assertEqual(second_status, 401)
        self.assertEqual(second["error"], "replay")

    def test_signed_unknown_action_is_rejected(self):
        status, body = self.post({
            "type": "shell", "target_id": "x", "idempotency_key": "bad", "payload": {},
        }, request_id="unknown-action")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "unsupported_command")

    def test_valid_signed_intent_command_executes_shared_control_path(self):
        branch = self.store.create_branch("Proxy branch", "test", status="ACTIVE")
        action = {
            "type": "checkpoint_branch", "target_id": branch,
            "payload": {"status": "PARKED", "summary": "Proxy approved"},
        }
        ts = "2026-09-14T09:00:00+00:00"
        with self.store.connect() as con:
            con.execute("""INSERT INTO attention_items
              (id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              VALUES('attn_proxy','test','warning','Proxy','Approve','open',?,'test',?,?)""",
              (json.dumps([action]), ts, ts))
        intent_id = ControlIntentService(self.root).ensure_for_attention("attn_proxy")
        command = {
            "type": "approve_intent", "target_id": intent_id,
            "idempotency_key": "proxy-approve-1",
            "payload": {"resolved_by": "human:test"},
        }
        status, body = self.post(command, request_id="valid-command")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["intent_status"], "RESOLVED")
        with self.store.connect() as con:
            self.assertEqual(
                con.execute("SELECT status FROM branches WHERE id=?", (branch,)).fetchone()[0],
                "PARKED",
            )
            self.assertEqual(
                con.execute("SELECT count(*) FROM manfred_commands WHERE idempotency_key='proxy-approve-1'").fetchone()[0],
                1,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
