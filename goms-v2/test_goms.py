#!/usr/bin/env python3
import asyncio
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from goms_store import GomsStore

ROOT = Path(__file__).resolve().parent


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="goms-test-")
        self.store = GomsStore(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_memory_relation_checkpoint_and_hash_chain(self):
        claim = self.store.add_entity("claim", "Claim", "Memory survives runtime replacement.", "test", actor="test")
        evidence = self.store.add_entity("evidence", "Evidence", "State is external to runtime.", "test", actor="test")
        self.store.link(evidence, "supports", claim, actor="test")
        branch = self.store.create_branch("Branch", "test", objective="Round trip", actor="test")
        self.store.checkpoint(branch, "CONCLUDED", "Done", actor="test")
        self.assertEqual(self.store.search("runtime", project="test")[0]["id"], claim)
        self.assertEqual(self.store.get_entity(claim)["relations"][0]["src"], evidence)
        self.assertEqual(self.store.list_branches(project="test")[0]["status"], "CONCLUDED")

        lines = self.store.ledger.read_bytes().splitlines()
        self.assertGreaterEqual(len(lines), 5)
        previous = None
        for raw in lines:
            event = json.loads(raw)
            self.assertEqual(event["prev_line_sha256"], previous)
            recorded = event.pop("event_sha256")
            canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            self.assertEqual(recorded, hashlib.sha256(canonical).hexdigest())
            previous = hashlib.sha256(raw).hexdigest()


    def test_store_connections_close_after_context(self):
        import sqlite3
        with self.store.connect() as con:
            con.execute("select 1").fetchone()
        with self.assertRaises(sqlite3.ProgrammingError):
            con.execute("select 1").fetchone()



class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_roundtrip(self):
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters

        with tempfile.TemporaryDirectory(prefix="goms-mcp-test-") as tmp:
            params = StdioServerParameters(
                command=str(ROOT / ".venv/bin/python"),
                args=[str(ROOT / "mcp_server.py")],
                env={**os.environ, "GOMS_HOME": tmp}, cwd=str(ROOT),
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertGreaterEqual(len(tools.tools), 16)

                    claim = await session.call_tool("record_claim", {
                        "title": "MCP claim", "claim": "GOMS is runtime independent.",
                        "project": "test", "confidence": 0.9,
                    })
                    claim_id = claim.structured_content["claim_id"]
                    evidence = await session.call_tool("record_evidence", {
                        "title": "MCP evidence", "summary": "Canonical state is external.",
                        "project": "test", "claim_id": claim_id, "stance": "supports",
                    })
                    self.assertTrue(evidence.structured_content["ok"])
                    state = await session.call_tool("project_state", {
                        "project": "test", "query": "runtime",
                    })
                    self.assertEqual(state.structured_content["state"]["memories"][0]["id"], claim_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
