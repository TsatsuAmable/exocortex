import unittest
import os
from unittest.mock import patch
import hermes_fabric_discovery as f

class FabricDiscoveryTests(unittest.TestCase):
    @patch.dict(os.environ, {"MCP_REMOTE_COMMANDER_API_KEY":"fixture"})
    @patch.object(f, "_http_ok")
    @patch.object(f, "_cmd_ok")
    @patch.object(f.shutil, "which")
    def test_discovers_remote_and_tailscale(self, which, cmd, http):
        which.return_value="/usr/local/bin/tailscale"; cmd.return_value=True
        http.side_effect=lambda url, timeout=2, headers=None: "8771" in url and headers == {"Authorization":"Bearer fixture"}
        rows={r["name"]:r for r in f.discover_fabric()}
        self.assertTrue(rows["remote_commander"]["healthy"])
        self.assertTrue(rows["tailscale_fabric"]["healthy"])
        self.assertFalse(rows["distillation_worker_pool"]["healthy"])

    @patch.dict(os.environ, {}, clear=True)
    @patch.object(f, "_http_ok", return_value=False)
    @patch.object(f, "_cmd_ok", return_value=False)
    @patch.object(f.shutil, "which", return_value=None)
    def test_broken_routes_are_reported_not_invented(self, *_):
        rows={r["name"]:r for r in f.discover_fabric()}
        self.assertFalse(rows["remote_commander"]["available"])
        self.assertFalse(rows["distillation_worker_pool"]["available"])

if __name__=="__main__": unittest.main()
