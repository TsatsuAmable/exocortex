#!/usr/bin/env python3
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_goms_config import discover_goms_root, hermes_mcp_config


class HermesGomsConfigTests(unittest.TestCase):
    def test_discovers_module_directory_without_machine_specific_home(self):
        root = discover_goms_root()
        self.assertTrue((root / "mcp_server.py").is_file())
    def test_override_supports_portable_install_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mcp_server.py").write_text("# test\n")
            with mock.patch.dict(os.environ, {"EXOCORTEX_GOMS_ROOT": tmp}):
                self.assertEqual(discover_goms_root(), root.resolve())
    def test_config_points_to_discovered_server(self):
        root = discover_goms_root()
        cfg = hermes_mcp_config(root)
        self.assertEqual(cfg["args"], [str(root / "mcp_server.py")])
        self.assertTrue(cfg["enabled"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
