#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from manfred_control import ManfredControl, authorized

MAX_BODY = 64 * 1024
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class ManfredHTTPServer(ThreadingHTTPServer):
    def __init__(self, address, handler, *, root: Path, token: str, authority_token: str):
        self.control = ManfredControl(root / "goms.sqlite3")
        self.token = token
        self.authority_token = authority_token
        super().__init__(address, handler)


class Handler(BaseHTTPRequestHandler):
    server: ManfredHTTPServer
    timeout = 15

    def log_message(self, format, *args):
        return

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self, *, authority=False) -> bool:
        token = self.server.authority_token if authority else self.server.token
        if authorized(self.headers.get("Authorization"), token):
            return True
        self._json(401, {"ok": False, "error": "unauthorized"})
        return False

    def do_GET(self):
        if not self._auth_ok():
            return
        if self.path != "/v1/manfred/brief":
            self._json(404, {"ok": False, "error": "not_found"})
            return
        self._json(200, {"ok": True, "brief": self.server.control.build_brief()})

    def do_POST(self):
        if not self._auth_ok(authority=True):
            return
        if self.path != "/v1/manfred/commands":
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
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                self._json(400, {"ok": False, "error": "incomplete_body"})
                return
            command = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"ok": False, "error": "invalid_json"})
            return
        if not isinstance(command, dict):
            self._json(400, {"ok": False, "error": "invalid_command"})
            return
        result = self.server.control.execute_command(command)
        error = result.get("error")
        if result.get("ok"):
            code = 200
        elif error in {"command_in_progress", "idempotency_key_reused"}:
            code = 409
        elif error == "human_attestation_required":
            code = 403
        elif error in {"command_claim_failed", "command_outcome_unknown", "command_failed"}:
            code = 503
        else:
            code = 400
        self._json(code, result)


def create_server(root: str | Path, *, token: str, authority_token: str | None = None,
                  host: str = "127.0.0.1", port: int = 8793):
    if not token:
        raise ValueError("non-empty read bearer token required")
    authority_token = authority_token or token
    if not authority_token:
        raise ValueError("non-empty authority bearer token required")
    if host not in LOOPBACK_HOSTS:
        raise ValueError("Manfred control must bind to loopback; expose via an authenticated tunnel/proxy")
    return ManfredHTTPServer((host, int(port)), Handler, root=Path(root),
                             token=token, authority_token=authority_token)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get(
        "GOMS_HOME", str(Path.home() / "Library/Application Support/Aineko/GOMS")))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8793)
    args = ap.parse_args()
    token = os.environ.get("GOMS_MANFRED_TOKEN", "")
    authority_token = os.environ.get("GOMS_MANFRED_AUTHORITY_TOKEN", "")
    server = create_server(args.root, token=token, authority_token=authority_token,
                           host=args.host, port=args.port)
    print(json.dumps({"listening": f"{args.host}:{args.port}"}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
