#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

import mcp_server
from control_intents import ControlIntentService
from goms_store import GomsStore
from manfred_control import ManfredControl


class MCPControlIntentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mcp-control-intents-")
        self.root = Path(self.tmp.name)
        self.store = GomsStore(self.root)
        self.old_store = mcp_server.store
        mcp_server.store = self.store
        self.svc = ControlIntentService(self.root)

    def tearDown(self):
        mcp_server.store = self.old_store
        self.tmp.cleanup()

    def make_intent(self, attention_id="attn_mcp"):
        branch = self.store.create_branch("MCP branch", "test", status="ACTIVE")
        action = {"type": "checkpoint_branch", "target_id": branch,
                  "payload": {"status": "PARKED", "summary": "Approved through MCP"}}
        ts = "2026-09-14T09:00:00+00:00"
        with self.store.connect() as con:
            con.execute("""INSERT INTO attention_items
              (id,category,severity,title,summary,status,suggested_actions,source,created_at,updated_at)
              VALUES(?,?,?,?,?,'open',?,?,?,?)""",
              (attention_id, "test", "warning", "MCP approval", "Needs decision",
               json.dumps([action]), "test-suite", ts, ts))
        return self.svc.ensure_for_attention(attention_id), branch

    def test_read_tool_returns_same_canonical_intent_as_control_brief(self):
        intent_id, _ = self.make_intent()
        tool = mcp_server.control_intent(intent_id)
        brief = ManfredControl(self.root / "goms.sqlite3").build_brief()
        projected = next(x for x in brief["intents"] if x["id"] == intent_id)
        self.assertTrue(tool["ok"])
        self.assertEqual(tool["intent"]["id"], projected["id"])
        self.assertEqual(tool["intent"]["status"], projected["status"])
        self.assertEqual(tool["intent"]["execution_policy"], projected["execution_policy"])

    def test_approve_requires_explicit_human_attestation(self):
        intent_id, branch = self.make_intent("attn_no_attest")
        result = mcp_server.decide_control_intent(
            intent_id, "APPROVE", "mcp-no-attest", actor="chatgpt",
            human_attested=False, resolved_by="user")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "human_attestation_required")
        self.assertEqual(self.svc.get(intent_id)["status"], "NEEDS_DECISION")
        self.assertEqual(self.store.list_branches(project="test")[0]["status"], "ACTIVE")
    def test_human_attested_approval_executes_once_through_shared_command_ledger(self):
        intent_id, branch = self.make_intent("attn_attested")
        first = mcp_server.decide_control_intent(
            intent_id, "APPROVE", "mcp-approve-1", actor="chatgpt",
            human_attested=True, resolved_by="user")
        replay = mcp_server.decide_control_intent(
            intent_id, "APPROVE", "mcp-approve-1", actor="chatgpt",
            human_attested=True, resolved_by="user")
        self.assertTrue(first["ok"])
        self.assertEqual(first, replay)
        self.assertEqual(first["intent_status"], "RESOLVED")
        with self.store.connect() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM manfred_commands WHERE idempotency_key='mcp-approve-1'").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT count(*) FROM checkpoints WHERE branch_id=?", (branch,)).fetchone()[0], 1)
        brief = ManfredControl(self.root / "goms.sqlite3").build_brief()
        self.assertFalse(any(x["id"] == intent_id for x in brief["intents"]))

    def test_origin_and_execution_links_remain_distinct_and_validate_https_host(self):
        intent_id, _ = self.make_intent("attn_links")
        origin = mcp_server.link_control_intent_conversation(
            intent_id, "origin", "conv-origin", "https://chatgpt.com/c/origin", actor="chatgpt", locator_source="supplied")
        execution = mcp_server.link_control_intent_conversation(
            intent_id, "execution", "conv-exec", "https://chatgpt.com/c/exec", actor="chatgpt", locator_source="observed")
        self.assertTrue(origin["ok"])
        self.assertTrue(execution["ok"])
        intent = self.svc.get(intent_id)
        self.assertEqual(intent["origin_conversation_id"], "conv-origin")
        self.assertEqual(intent["execution_conversation_id"], "conv-exec")
        self.assertEqual(intent["provenance"]["conversation_locators"]["execution"]["source"], "observed")
        bad = mcp_server.link_control_intent_conversation(
            intent_id, "execution", "conv-bad", "javascript:alert(1)", actor="chatgpt", locator_source="supplied")
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"], "invalid_conversation_url")


    def test_mcp_conversation_link_defaults_to_unverified_locator(self):
        intent_id, _ = self.make_intent("attn_unverified_link")
        result = mcp_server.link_control_intent_conversation(
            intent_id, "execution", "conv", "https://chatgpt.com/c/x", actor="chatgpt"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["intent"]["provenance"]["conversation_locators"]["execution"]["source"],
            "unverified",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
