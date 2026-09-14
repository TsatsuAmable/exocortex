#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from manfred_control import ManfredControl

TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
MAX_BODY = 64 * 1024
MAX_CLOCK_SKEW_SECONDS = 120
ALLOWED_COMMANDS = {"approve_intent", "reject_intent", "defer_intent", "confirm_intent"}


def _tailnet_ipv4(value: str | None) -> bool:
    try:
        return ipaddress.ip_address(str(value)) in TAILNET_V4
    except ValueError:
        return False


def validate_bind(host: str, allowed_client: str | None) -> None:
    if not (_tailnet_ipv4(host) and allowed_client and _tailnet_ipv4(allowed_client)):
        raise ValueError("authority ingress requires tailnet host and explicit tailnet client")


def client_allowed(peer: str, allowed_client: str | None) -> bool:
    return bool(allowed_client) and peer == allowed_client


def load_key_file(path: str | Path) -> bytes:
    key_path = Path(path)
    mode = key_path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ValueError("authority key file must not be group/world accessible")
    key = key_path.read_bytes().strip()
    if len(key) < 16:
        raise ValueError("authority key is missing or too short")
    return key


class Server(ThreadingHTTPServer):
    def __init__(self, address, handler, *, root: Path, allowed_client: str, key: bytes):
        self.control = ManfredControl(root / "goms.sqlite3")
        self.allowed_client = allowed_client
        self.key = bytes(key)
        self.seen_requests = deque(maxlen=4096)
        self.seen_lock = threading.Lock()
        super().__init__(address, handler)

    def verify(self, path: str, body: bytes, headers) -> tuple[bool, str]:
        request_id = str(headers.get("X-Manfred-Request-Id") or "").strip()
        timestamp = str(headers.get("X-Manfred-Timestamp") or "").strip()
        supplied = str(headers.get("X-Manfred-Signature") or "").strip()
        if not request_id or not timestamp or not supplied:
            return False, "missing_auth"
        try:
            when = int(timestamp)
        except ValueError:
            return False, "bad_timestamp"
        if abs(int(time.time()) - when) > MAX_CLOCK_SKEW_SECONDS:
            return False, "stale_request"
        canonical = f"POST\n{path}\n{timestamp}\n{request_id}\n".encode() + body
        expected = hmac.new(self.key, canonical, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            return False, "bad_signature"
        with self.seen_lock:
            if request_id in self.seen_requests:
                return False, "replay"
            self.seen_requests.append(request_id)
        return True, request_id


class Handler(BaseHTTPRequestHandler):
    server: Server

    def log_message(self, *_args):
        return

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _peer_ok(self) -> bool:
        if client_allowed(self.client_address[0], self.server.allowed_client):
            return True
        self._json(403, {"ok": False, "error": "forbidden_client"})
        return False

    def do_POST(self) -> None:
        if not self._peer_ok():
            return
        if self.path != "/v1/manfred/intent-command":
            self._json(404, {"ok": False, "error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            self._json(400, {"ok": False, "error": "invalid_content_length"})
            return
        if length <= 0 or length > MAX_BODY:
            self._json(413 if length > MAX_BODY else 400,
                       {"ok": False, "error": "invalid_body_size"})
            return
        raw = self.rfile.read(length)
        if len(raw) != length:
            self._json(400, {"ok": False, "error": "incomplete_body"})
            return
        auth_ok, detail = self.server.verify(self.path, raw, self.headers)
        if not auth_ok:
            self._json(401, {"ok": False, "error": detail})
            return
        try:
            command = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"ok": False, "error": "invalid_json"})
            return
        if not isinstance(command, dict):
            self._json(400, {"ok": False, "error": "invalid_command"})
            return
        if str(command.get("type") or "") not in ALLOWED_COMMANDS:
            self._json(400, {"ok": False, "error": "unsupported_command"})
            return
        result = self.server.control.execute_command(command)
        error = result.get("error")
        if result.get("ok"):
            status = 200
        elif error in {"command_in_progress", "idempotency_key_reused", "intent_in_progress"}:
            status = 409
        elif error in {"human_attestation_required", "resolved_by_required"}:
            status = 403
        elif error in {"command_claim_failed", "command_outcome_unknown",
                       "intent_outcome_unknown", "command_failed"}:
            status = 503
        elif error in {"intent_not_found"}:
            status = 404
        else:
            status = 400
        self._json(status, result)

    def do_GET(self) -> None:
        if not self._peer_ok():
            return
        self._json(405, {"ok": False, "error": "method_not_allowed"})


def create_server(root: str | Path, *, host: str, port: int,
                  allowed_client: str, key: bytes) -> Server:
    validate_bind(host, allowed_client)
    if not key:
        raise ValueError("non-empty authority key required")
    return Server((host, int(port)), Handler, root=Path(root),
                  allowed_client=allowed_client, key=key)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get(
        "GOMS_HOME", str(Path.home() / "Library/Application Support/Aineko/GOMS")))
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=8795)
    ap.add_argument("--allowed-client", required=True)
    ap.add_argument("--key-file", default=os.environ.get(
        "GOMS_MANFRED_AUTHORITY_KEY_FILE",
        str(Path.home() / "Library/Application Support/Aineko/GOMS/secrets/manfred-ingress.key")))
    args = ap.parse_args()
    key = load_key_file(args.key_file)
    server = create_server(args.root, host=args.host, port=args.port,
                           allowed_client=args.allowed_client, key=key)
    print(json.dumps({"listening": f"{args.host}:{args.port}",
                      "mode": "signed-authority"}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
