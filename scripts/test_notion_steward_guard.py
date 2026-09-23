#!/usr/bin/env python3
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_notion_surface_steward.sh"

class NotionStewardGuardTest(unittest.TestCase):
    def _fixture(self, captured: bool):
        td = tempfile.TemporaryDirectory()
        base = Path(td.name)
        current = base / "current"
        home = base / "home"
        hermes_home = base / "hermes"
        for p in (current / "scripts", current / "goms-v2",
                  current / "hermes/prompts", home / ".local/bin",
                  hermes_home / "mcp-tokens"):
            p.mkdir(parents=True, exist_ok=True)
        (hermes_home / "mcp-tokens/notion.json").write_text(
            json.dumps({"access_token": "test-token"}))
        (current / "scripts/refresh_notion_token.py").write_text(
            'print("{\"ok\": true}")\n')
        (current / "goms-v2/notion_surface_sync.py").write_text(
            "import json\nprint(json.dumps({"
            f"'ok': True, 'inbound': {{'captured': {captured!r}}}, "
            "'outbound': {}}))\n")
        (current / "hermes/prompts/notion-knowledge-surface-steward.md").write_text(
            "steward test")
        marker = base / "hermes-called"
        fake = home / ".local/bin/hermes"
        fake.write_text(f"#!/bin/zsh\ntouch '{marker}'\nexit 0\n")
        fake.chmod(0o755)
        env = os.environ.copy()
        env.update({
            "HOME": str(home),
            "HERMES_HOME": str(hermes_home),
            "EXOCORTEX_CURRENT": str(current),
            "GOMS_HOME": str(base / "goms"),
            "NOTION_KNOWLEDGE_SURFACE_PAGE_ID": "page",
            "NOTION_COCKPIT_PAGE_ID": "cockpit",
            "NOTION_LEDGER_DATA_SOURCE_ID": "ledger",
        })
        return td, env, marker

    def test_unchanged_sync_skips_llm(self):
        td, env, marker = self._fixture(False)
        with td:
            cp = subprocess.run(["zsh", str(RUNNER)], env=env,
                                text=True, capture_output=True, check=False)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            self.assertIn("skipping LLM steward", cp.stdout)
            self.assertFalse(marker.exists())

    def test_inbound_edit_runs_llm(self):
        td, env, marker = self._fixture(True)
        with td:
            cp = subprocess.run(["zsh", str(RUNNER)], env=env,
                                text=True, capture_output=True, check=False)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            self.assertTrue(marker.exists())

if __name__ == "__main__":
    unittest.main()
