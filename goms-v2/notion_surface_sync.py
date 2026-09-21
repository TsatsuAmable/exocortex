#!/usr/bin/env python3
"""Governed GOMS <-> Notion knowledge-surface synchronization.

Notion is a structured coordination cockpit: a projection/capture surface.
GOMS remains canonical. Sync order is intentionally inbound-first:

1. fetch the last generated Notion projection page;
2. detect human edits relative to the last generated projection;
3. persist any semantic delta as a provenance-bearing GOMS candidate;
4. regenerate the canonical projection from GOMS, preserving GOMS
   identifiers, and write it back with a stable record identity;
5. persist projection state outside Notion.

Transport uses the official Notion MCP server over streamable HTTP with the
Hermes-managed OAuth token. No additional dependency is introduced.

The projection record lives in the Aineko Cognitive Ledger data source and
keeps a stable page identity (NOTION_LEDGER_ID) across runs, so repeated
synchronization never duplicates pages.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MCP_URL = "https://mcp.notion.com/mcp"
PROTOCOL_VERSION = "2025-03-26"

STATE_REL = Path("knowledge-surfaces/notion.json")
SNAPSHOT_REL = Path("knowledge-surfaces/notion-last-projection.md")

PROJECTION_PAGE_ID_ENV = "NOTION_KNOWLEDGE_SURFACE_PAGE_ID"
LEDGER_DATA_SOURCE_ENV = "NOTION_LEDGER_DATA_SOURCE_ID"

RECONCILIATION_NOTICE = (
    "> Generated projection of canonical GOMS state. Edit freely if useful: "
    "edits are captured as provenance-bearing candidates before this "
    "projection is refreshed. Do not treat this page as canonical."
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_state(root: Path) -> dict:
    path = root / STATE_REL
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(root: Path, state: dict) -> None:
    path = root / STATE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Notion MCP transport (official Notion MCP server, streamable HTTP)
# --------------------------------------------------------------------------

class NotionMCPError(RuntimeError):
    pass


class NotionMCP:
    """Minimal MCP client for the official Notion MCP server."""

    def __init__(self, token: str, url: str = MCP_URL):
        if not token:
            raise NotionMCPError("Notion token is required")
        self._token = token
        self._url = url
        self._next_id = 0

    def _headers(self):
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "User-Agent": "exocortex-goms-notion-sync/1.0",
            "Notion-Version": "2022-06-28",
        }

    def _post(self, payload: dict) -> dict:
        request = urllib.request.Request(
            self._url, data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(), method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
        data_lines = [
            line[6:] for line in body.splitlines() if line.startswith("data: ")
        ]
        if not data_lines:
            raise NotionMCPError("Notion MCP returned no data payload")
        return json.loads(data_lines[-1])

    def call(self, method: str, params: dict) -> dict:
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params,
        }
        response = self._post(payload)
        if "error" in response:
            raise NotionMCPError(f"Notion MCP error: {response['error']}")
        result = response.get("result", {})
        if result.get("isError") and result.get("content"):
            text = result["content"][0].get("text", "")
            raise NotionMCPError(f"Notion MCP tool error: {text[:500]}")
        return result

    def tool(self, name: str, arguments: dict) -> dict:
        return self.call("tools/call", {"name": name, "arguments": arguments})

    def tool_text(self, name: str, arguments: dict) -> str:
        result = self.tool(name, arguments)
        content = result.get("content") or []
        text = "\n".join(item.get("text", "") for item in content if isinstance(item, dict))
        # Notion MCP wraps some tool results in a JSON envelope whose "text"
        # field carries the rendered page (with real newlines once parsed).
        # Unwrap the envelope so downstream parsing sees the actual body.
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                data = json.loads(stripped)
            except ValueError:
                data = None
            if isinstance(data, dict) and isinstance(data.get("text"), str):
                return data["text"]
        return text


def notion_token_from_env() -> str:
    token = os.environ.get("NOTION_MCP_ACCESS_TOKEN")
    if token:
        return token
    path = os.environ.get(
        "NOTION_MCP_TOKEN_FILE",
        str(Path.home() / ".hermes/profiles/gsvaineko/mcp-tokens/notion.json"),
    )
    if path and Path(path).is_file():
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data.get("access_token", "")
    return ""


def extract_page_text(raw: str) -> str:
    """Extract the projected <content> body from a notion-fetch payload."""
    match = re.search(r"<content>\n?(.*?)</content>", raw, re.DOTALL)
    return match.group(1).rstrip() if match else raw.strip()


def extract_page_url(raw: str) -> str | None:
    match = re.search(r'url="(\S+)"', raw)
    return match.group(1) if match else None

MACHINE_FOOTER_MARK = "Synced by GOMS <-> Notion governed adapter."


def machine_footer(digest: str) -> str:
    """Machine footer appended to every outbound write, carrying the digest."""
    return f"\n\n---\n{MACHINE_FOOTER_MARK} sha256:{digest}"


def strip_machine_footer(text: str) -> str:
    """Remove the adapter's own trailing footer for content comparisons.

    Notion fetch may render newlines as literal backslash-n, so the marker
    is matched in both real and literal-escaped newline forms.
    """
    marker = "\n---\n" + MACHINE_FOOTER_MARK
    literal = marker.replace("\n", "\\n")
    for candidate in (literal, marker):
        idx = text.find(candidate)
        if idx != -1:
            return text[:idx].rstrip()
    return text.rstrip()


def page_last_edited(raw: str) -> str | None:
    match = re.search(r'"page_last_edited_at\\??"\\s*:\\s*\\?"([^"\\\\]+)', raw)
    if not match:
        match = re.search(r"page_last_edited_at[\"'=\\s:]+([0-9TZ:.-]+)", raw)
    return match.group(1) if match else None


# --------------------------------------------------------------------------
# Canonical projection rendering (GOMS -> Notion)
# --------------------------------------------------------------------------

def _flatten(text: str) -> str:
    return str(text or "").replace("|", "/").replace("\n", " ").strip()


def render_projection(store) -> str:
    branches = store.list_branches(project="Exocortex")
    active = [b for b in branches if b["status"] in {"ACTIVE", "BLOCKED", "DELEGATED"}]
    lines = [
        "## Canonical identity",
        f"- GOMS branch: `branch_ee07629123d0`",
        "- Canonical machine state: GOMS",
        "- Executable/project truth: GitHub",
        "- Human-readable knowledge: Obsidian / aineko-vault",
        "- Structured coordination cockpit: Notion",
        "- Operational control: Manfred",
        "",
        "## Reconciliation contract",
        RECONCILIATION_NOTICE,
        "",
        "## Active work",
        "",
        "| GOMS ID | Title | Status | Next action |",
        "|---|---|---|---|",
    ]
    for b in active:
        lines.append(
            f"| {b['id']} | {_flatten(b['title'])} | {b['status']} "
            f"| {_flatten(b.get('next_action'))} |"
        )
    if not active:
        lines.append("| _none_ | | | |")

    lines += ["", "## Unresolved human-attention items", ""]
    unresolved = []
    for b in active:
        for item in b.get("unresolved") or []:
            unresolved.append((b["id"], str(item)))
    if unresolved:
        for bid, item in unresolved:
            lines.append(f"- [{bid}] {_flatten(item)}")
    else:
        lines.append("- None recorded.")

    lines += [
        "",
        "## Durable decisions and commitments",
        "",
    ]
    with store.connect() as con:
        rows = con.execute(
            "SELECT id, title, summary, updated_at FROM entities "
            "WHERE type='decision' AND project='Exocortex' "
            "AND status NOT IN ('SUPERSEDED','RETIRED') "
            "ORDER BY updated_at DESC LIMIT 8"
        ).fetchall()
    if rows:
        for row in rows:
            lines.append(f"- [{row['id']}] {_flatten(row['title'])}: {_flatten(row['summary'])[:160]}")
    else:
        lines.append("- None recorded.")

    lines += [
        "",
        "## Provenance",
        "",
        "- projected_at: maintained in GOMS state file and ledger row",
        "- source: goms://project/Exocortex",
        "- canonical: false (projection; GOMS is authoritative)",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Inbound capture (Notion -> GOMS)
# --------------------------------------------------------------------------

def _deterministic_candidate_id(page_id: str, digest: str) -> str:
    raw = hashlib.sha256(f"{page_id}\0{digest}".encode()).hexdigest()[:16]
    return f"evidence_notion_{raw}"


def _detable(text: str) -> str:
    """Reconstruct markdown pipe tables from Notion's <table> rendering."""
    if "<table" not in text:
        return text

    def _rebuild(match: "re.Match[str]") -> str:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", match.group(0), re.DOTALL)
        lines = []
        ncols = 0
        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            if not cells:
                continue
            ncols = max(ncols, len(cells))
            lines.append("| " + " | ".join(c.strip() for c in cells) + " |")
        if len(lines) < 2:
            return match.group(0)
        lines.insert(1, "|" + "---|" * ncols)
        return "\n".join(lines)

    return re.sub(r"<table.*?</table>", _rebuild, text, flags=re.DOTALL)


def _canonical_text(text: str) -> str:
    """Normalize Notion fetch rendering for robust content comparison.

    Notion fetch may render newlines as literal backslash-n sequences,
    markdown tables as <table> XML, and escape bracket characters; all are
    normalized so the comparison is a semantic content comparison, not a
    rendering comparison.
    """
    text = _detable(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\\n" in text and "\n" not in text:
        text = text.replace("\\n", "\n")
    for esc, plain in (("\\[", "["), ("\\]", "]"),
                       ("\\<", "<"), ("\\>", ">")):
        text = text.replace(esc, plain)
    # Notion's render collapses blank lines; compare on the non-empty-line
    # sequence so adapter-written content round-trips byte-stably.
    return "\n".join(line for line in text.splitlines() if line.strip())


def capture_inbound_edit(root: Path, store, raw_page: str, page_id: str) -> dict:
    state = load_state(root)
    snapshot_path = root / SNAPSHOT_REL
    if not snapshot_path.is_file():
        return {"captured": False, "reason": "no_prior_projection"}

    previous = strip_machine_footer(_canonical_text(snapshot_path.read_text(encoding="utf-8")))
    current = strip_machine_footer(_canonical_text(extract_page_text(raw_page)))
    current_sha = sha256_text(current)
    previous_sha = sha256_text(previous)
    if current_sha == previous_sha:
        return {"captured": False, "reason": "unchanged"}

    # A refresh by this adapter changes only machine-generated lines
    # (provenance timestamps); human semantic content is compared separately.
    diff = "\n".join(difflib.unified_diff(
        previous.splitlines(), current.splitlines(),
        fromfile="last-goms-notion-projection", tofile="current-notion-edit",
        lineterm="",
    ))

    source_url = f"notion://page/{page_id}?sha256={current_sha}"
    candidate_id = _deterministic_candidate_id(page_id, current_sha)
    if not _entity_exists(store, candidate_id):
        store.add_entity(
            "evidence",
            "Notion edit candidate: Exocortex knowledge-surface projection",
            summary=diff[:16000] or "Projection content changed.",
            project="Exocortex",
            status="CANDIDATE",
            confidence=1.0,
            source=source_url,
            tags=["notion", "knowledge-surface", "human-edit", "reconciliation-candidate"],
            metadata={
                "surface": "notion",
                "page_id": page_id,
                "content_sha256": current_sha,
                "previous_projection_sha256": previous_sha,
                "canonical": False,
                "requires_reconciliation": True,
            },
            entity_id=candidate_id,
            actor="notion-knowledge-surface-sync",
        )
    state["last_inbound_candidate"] = {
        "entity_id": candidate_id,
        "captured_at": utc_now(),
        "content_sha256": current_sha,
        "source": source_url,
    }
    save_state(root, state)
    return {"captured": True, "entity_id": candidate_id, "content_sha256": current_sha}


def _entity_exists(store, entity_id: str) -> bool:
    try:
        store.get_entity(entity_id)
        return True
    except KeyError:
        return False


# --------------------------------------------------------------------------
# Outbound projection write (GOMS -> Notion)
# --------------------------------------------------------------------------

def _ledger_row_exists(notion: NotionMCP, data_source_id: str, content: str) -> bool:
    """True when a ledger row for this projection digest already exists.

    Rows are matched by the sha256 stored in row content; identical content
    must not spawn duplicate ledger entries on every sync pass.
    """
    digest = sha256_text(content)
    try:
        rows = notion.tool_text("notion-fetch", {"id": data_source_id})
    except NotionMCPError:
        return False
    return digest in (rows or "")


def project(root: Path, store, notion: NotionMCP, page_id: str, ledger_id: str | None) -> dict:
    content = render_projection(store)
    digest = sha256_text(content)
    full_body = content + machine_footer(digest)
    raw = notion.tool_text("notion-fetch", {"id": page_id})
    url = extract_page_url(raw) or f"https://app.notion.com/p/{page_id.replace('-', '')}"
    resolved_ledger = ledger_id or _resolve_data_source(notion, page_id) or f"page:{page_id}"

    write_mode = "page-only"
    ledger_written = False
    if resolved_ledger and not resolved_ledger.startswith("page:"):
        try:
            dedupe = _ledger_row_exists(notion, resolved_ledger, content)
            if not dedupe:
                notion.tool("notion-create-pages", {
                    "parent": {"type": "data_source_id", "data_source_id": resolved_ledger},
                    "pages": [{"properties": {"Name": "Exocortex operational projection"},
                               "content": full_body}],
                })
            ledger_written = True
            write_mode = "ledger-update"
        except NotionMCPError:
            pass

    # The projection page is the human-facing surface: keep it current on
    # every pass. Ledger row is the governed write; page mirrors canonical
    # state either way (page-only mode is the ledger-failure fallback).
    notion.tool("notion-update-page", {
        "page_id": page_id,
        "command": "replace_content",
        "new_str": full_body,
    })

    snapshot = root / SNAPSHOT_REL
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(full_body, encoding="utf-8")

    state = load_state(root)
    state.update({
        "schema_version": 1,
        "surface": "notion",
        "page_id": page_id,
        "projection_sha256": digest,
        "projected_at": utc_now(),
        "write_mode": write_mode,
        "page_url": url,
    })
    save_state(root, state)
    return {
        "page_id": page_id,
        "sha256": state["projection_sha256"],
        "write_mode": write_mode,
        "branches": len(store.list_branches(project="Exocortex")),
    }


def _resolve_data_source(notion: NotionMCP, page_id: str) -> str:
    raw = notion.tool_text("notion-fetch", {"id": page_id})
    match = re.search(r'collection://([0-9a-fA-F-]+)', raw)
    return match.group(1) if match else os.environ.get(LEDGER_DATA_SOURCE_ENV, "")


# --------------------------------------------------------------------------
# Sync entry point
# --------------------------------------------------------------------------

def sync(root: Path, notion: NotionMCP, page_id: str, ledger_id: str | None) -> dict:
    root = root.expanduser().resolve()
    store = _open_store()
    raw = notion.tool_text("notion-fetch", {"id": page_id})
    inbound = capture_inbound_edit(root, store, raw, page_id)
    outbound = project(root, store, notion, page_id, ledger_id)
    return {
        "ok": True,
        "inbound": inbound,
        "outbound": outbound,
        "at": utc_now(),
    }


def _open_store():
    from goms_store import GomsStore
    return GomsStore(Path(os.environ.get("GOMS_HOME", ".")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["sync", "project", "ingest"])
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("GOMS_HOME", ".")))
    parser.add_argument("--page-id", default=os.environ.get(PROJECTION_PAGE_ID_ENV, ""))
    parser.add_argument("--ledger-id", default=os.environ.get("NOTION_LEDGER_ID", ""))
    args = parser.parse_args()

    notion = NotionMCP(notion_token_from_env())
    if not args.page_id:
        raise SystemExit("Notion projection page id required (--page-id or env)")

    if args.command == "sync":
        result = sync(args.root, notion, args.page_id, args.ledger_id or None)
    elif args.command == "project":
        store = _open_store()
        result = project(args.root.expanduser().resolve(), store, notion,
                         args.page_id, args.ledger_id or None)
    else:
        store = _open_store()
        raw = notion.tool_text("notion-fetch", {"id": args.page_id})
        result = capture_inbound_edit(
            args.root.expanduser().resolve(), store, raw, args.page_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())