#!/usr/bin/env python3
"""Tests for governed GOMS <-> Notion knowledge-surface synchronization."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import notion_surface_sync as nss  # noqa: E402
from goms_store import GomsStore  # noqa: E402


class TempStoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="notion-surface-test-")
        self.root = Path(self.tmp)
        self.store = GomsStore(self.root)
        self.store.init()

    def _seed_exocortex(self):
        self.branch_id = self.store.create_branch(
            "Knowledge-surface projection", project="Exocortex",
            objective="Project Exocortex state to Notion",
            next_action="verify projection",
            unresolved=["round-trip test pending"],
        )

    def test_render_projection_contains_stable_goms_ids(self):
        self._seed_exocortex()
        text = nss.render_projection(self.store)
        self.assertIn(self.branch_id, text)
        self.assertIn("Canonical identity", text)
        self.assertIn("Reconciliation contract", text)
        self.assertIn("round-trip test pending", text)
        self.assertIn("projection; GOMS is authoritative", text)

    def test_render_projection_without_work(self):
        text = nss.render_projection(self.store)
        self.assertIn("None recorded.", text)

    def test_inbound_edit_captured_as_evidence_candidate(self):
        self._seed_exocortex()
        page_id = "3e18cb372fb18149b253f90dae499ad3"
        generated = "## Active work\n\n| GOMS ID | Title |\n|---|---|\n| %s | X |\n" % self.branch_id
        (self.root / nss.SNAPSHOT_REL).parent.mkdir(parents=True, exist_ok=True)
        (self.root / nss.SNAPSHOT_REL).write_text(generated, encoding="utf-8")

        edited = generated.replace("X", "Y — human edited priority")
        raw_page = f"<page>\n<content>\n{edited}\n</content>\n</page>"

        result = nss.capture_inbound_edit(self.root, self.store, raw_page, page_id)
        self.assertTrue(result["captured"])
        entity = self.store.get_entity(result["entity_id"])
        self.assertEqual(entity["type"], "evidence")
        self.assertEqual(entity["status"], "CANDIDATE")
        self.assertEqual(entity["metadata"]["surface"], "notion")
        self.assertFalse(entity["metadata"]["canonical"])
        self.assertTrue(entity["metadata"]["requires_reconciliation"])
        self.assertIn("human edited priority", entity["summary"])

    def test_inbound_edit_is_idempotent_on_rerun(self):
        self._seed_exocortex()
        page_id = "3e18cb372fb18149b253f90dae499ad3"
        generated = "## Active work\n\ncontent\n"
        (self.root / nss.SNAPSHOT_REL).parent.mkdir(parents=True, exist_ok=True)
        (self.root / nss.SNAPSHOT_REL).write_text(generated, encoding="utf-8")
        edited = generated + "human note\n"
        raw_page = f"<page>\n<content>\n{edited}\n</content>\n</page>"
        first = nss.capture_inbound_edit(self.root, self.store, raw_page, page_id)
        second = nss.capture_inbound_edit(self.root, self.store, raw_page, page_id)
        self.assertTrue(first["captured"])
        self.assertEqual(first["entity_id"], second["entity_id"])
        with sqlite3.connect(self.root / "goms.sqlite3") as con:
            count = con.execute(
                "SELECT COUNT(*) FROM entities WHERE id=?",
                (first["entity_id"],)).fetchone()[0]
        self.assertEqual(count, 1)

    def test_no_prior_projection_means_no_capture(self):
        self._seed_exocortex()
        raw_page = "<page>\n<content>\nanything\n</content>\n</page>"
        result = nss.capture_inbound_edit(
            self.root, self.store, raw_page, "3e18cb372fb18149b253f90dae499ad3")
        self.assertFalse(result["captured"])
        self.assertEqual(result["reason"], "no_prior_projection")

    def test_unchanged_content_not_captured(self):
        self._seed_exocortex()
        page_id = "3e18cb372fb18149b253f90dae499ad3"
        content = "## Active work\n\ncontent\n"
        (self.root / nss.SNAPSHOT_REL).parent.mkdir(parents=True, exist_ok=True)
        (self.root / nss.SNAPSHOT_REL).write_text(content, encoding="utf-8")
        raw_page = f"<page>\n<content>\n{content}\n</content>\n</page>"
        result = nss.capture_inbound_edit(self.root, self.store, raw_page, page_id)
        self.assertFalse(result["captured"])
        self.assertEqual(result["reason"], "unchanged")

    def test_adapter_own_write_not_recaptured(self):
        """A snapshot bearing the machine footer must not self-capture."""
        self._seed_exocortex()
        page_id = "3e18cb372fb18149b253f90dae499ad3"
        content = "## Active work\n\ncontent"
        digest = nss.sha256_text(content)
        snapshot = nss.machine_footer(digest)
        (self.root / nss.SNAPSHOT_REL).parent.mkdir(parents=True, exist_ok=True)
        (self.root / nss.SNAPSHOT_REL).write_text(content + snapshot, encoding="utf-8")
        raw_page = "<page>\n<content>\n" + content + snapshot + "\n</content>\n</page>"
        result = nss.capture_inbound_edit(self.root, self.store, raw_page, page_id)
        self.assertFalse(result["captured"])
        self.assertEqual(result["reason"], "unchanged")


class TransportCase(unittest.TestCase):
    def test_extract_page_text(self):
        raw = '<page><content>\n## Canonical identity\n- GOMS branch\n</content></page>'
        self.assertEqual(nss.extract_page_text(raw), "## Canonical identity\n- GOMS branch")

    def test_extract_page_url(self):
        raw = '<page url="https://app.notion.com/p/abc123">'
        self.assertEqual(nss.extract_page_url(raw), "https://app.notion.com/p/abc123")

    def test_tool_error_raises(self):
        client = nss.NotionMCP("tok")
        response = {
            "result": {
                "isError": True,
                "content": [{"type": "text", "text": "APIException: bad"}],
            }
        }
        with patch.object(client, "_post", return_value=response):
            with self.assertRaises(nss.NotionMCPError):
                client.tool_text("notion-fetch", {"id": "x"})

    def test_mcp_error_raises(self):
        client = nss.NotionMCP("tok")
        with patch.object(client, "_post", return_value={"error": {"code": -1, "message": "m"}}):
            with self.assertRaises(nss.NotionMCPError):
                client.call("tools/call", {})

    def test_token_from_env(self):
        with patch.dict(os.environ, {"NOTION_MCP_ACCESS_TOKEN": "envtok"}):
            self.assertEqual(nss.notion_token_from_env(), "envtok")


class ProjectionWriteCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="notion-surface-write-")
        self.root = Path(self.tmp)
        self.store = GomsStore(self.root)
        self.store.init()
        self.store.create_branch(
            "Active branch", project="Exocortex", next_action="work",
            unresolved=["attention item"],
        )
        self.notion = MagicMock()
        self.notion.tool_text.return_value = (
            '<page url="https://app.notion.com/p/3e18cb372fb18149b253f90dae499ad3">'
            '<parent-data-source url="collection://7d087726-0cc9-4c9c-8038-01b852d05c17" />'
            "<content>\nold projection body\n</content></page>"
        )
        self.notion.tool.return_value = {"ok": True}

    def test_project_uses_ledger_update_and_saves_state(self):
        result = nss.project(
            self.root, self.store, self.notion,
            "3e18cb372fb18149b253f90dae499ad3",
            "3d88cb372fb181f5bf49d0bfffd58508")
        self.assertEqual(result["write_mode"], "ledger-update")
        update_payload = json.dumps(self.notion.tool.call_args[0][1])
        self.assertIn("Active branch", update_payload)
        self.assertIn("attention item", update_payload)

    def test_project_falls_back_to_page_replace(self):
        self.notion.tool.side_effect = [nss.NotionMCPError("no ledger write"), {"ok": True}]
        result = nss.project(self.root, self.store, self.notion,
                             "3e18cb372fb18149b253f90dae499ad3", None)
        self.assertEqual(result["write_mode"], "page-only")

    def test_projection_preserves_reconciliation_notice(self):
        nss.project(self.root, self.store, self.notion,
                    "3e18cb372fb18149b253f90dae499ad3", None)
        update_payload = json.dumps(self.notion.tool.call_args[0][1])
        self.assertIn(nss.RECONCILIATION_NOTICE, update_payload)


if __name__ == "__main__":
    unittest.main()