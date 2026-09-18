#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

import exocortex_deploy


class DeployTests(unittest.TestCase):
    def test_install_is_machine_neutral_and_rollbackable(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "runtime"
            source = Path(__file__).resolve().parent
            first = exocortex_deploy.install(prefix, source)
            self.assertTrue((first / "goms-v2" / "mcp_server.py").is_file())
            self.assertFalse((first / "goms-v2" / ".venv").exists())
            cfg = exocortex_deploy.hermes_fragment(first)
            server = cfg["mcp_servers"]["goms"]
            self.assertEqual(server["env"]["EXOCORTEX_GOMS_ROOT"],
                             str(first / "goms-v2"))
            self.assertNotIn("/Users/", server["args"][0])
            self.assertNotIn("/Users/", server["env"]["EXOCORTEX_GOMS_ROOT"])
            exocortex_deploy.install(prefix, source)
            self.assertTrue((prefix / ".previous" / "goms-v2" / "mcp_server.py").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
