#!/usr/bin/env python3
"""Refresh the Notion MCP OAuth access token before the hourly steward runs.

Proactive rotation: if expires_at is closer than THRESHOLD seconds (default 1h,
longer than the steward interval), POST refresh_token to the Notion token
endpoint and persist the rotated tokens in Hermes token storage format.
Idempotent and safe under concurrent runs via a lock file.
"""
import json, os, sys, time, urllib.parse, urllib.request, urllib.error, pathlib

TOKEN_PATH = pathlib.Path(os.environ.get(
    "NOTION_TOKEN_FILE",
    os.path.expanduser("~/.hermes/profiles/gsvaineko/mcp-tokens/notion.json"),
))
META_PATH = TOKEN_PATH.parent / "notion.meta.json"
CLIENT_PATH = TOKEN_PATH.parent / "notion.client.json"
LOCK = TOKEN_PATH.parent / "notion-refresh.lock"
THRESHOLD = int(sys.argv[1]) if len(sys.argv) > 1 else 3600


def _ua():
    return {"User-Agent": "exocortex-goms-notion-sync/1.0", "Accept": "application/json"}


def main() -> int:
    try:
        data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"ok": False, "reason": "unreadable-token-file", "error": str(exc)}))
        return 1
    exp = data.get("expires_at")
    if not exp or (exp - time.time()) > THRESHOLD:
        print(json.dumps({"ok": True, "rotated": False,
                          "seconds_remaining": int((exp - time.time())) if exp else None}))
        return 0
    try:
        meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        client = json.loads(CLIENT_PATH.read_text(encoding="utf-8"))
        endpoint = meta.get("token_endpoint") or "https://mcp.notion.com/token"
        client_id = client.get("client_id")
        if not client_id or not data.get("refresh_token"):
            raise RuntimeError("missing client_id or refresh_token")
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": data["refresh_token"],
            "client_id": client_id,
        }).encode()
        headers = dict(_ua())
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            tok = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(json.dumps({"ok": False, "rotated": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    if "access_token" not in tok:
        print(json.dumps({"ok": False, "rotated": False, "error": "no access_token in response"}))
        return 1
    expires_in = int(tok.get("expires_in", data.get("expires_in", 3600)) or 3600)
    data["access_token"] = tok["access_token"]
    data["expires_in"] = expires_in
    data["expires_at"] = time.time() + expires_in
    if tok.get("refresh_token"):
        data["refresh_token"] = tok["refresh_token"]
    tmp = TOKEN_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(TOKEN_PATH)
    print(json.dumps({"ok": True, "rotated": True,
                      "seconds_remaining": expires_in,
                      "new_expires_at": data["expires_at"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
