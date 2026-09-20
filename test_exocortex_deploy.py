#!/usr/bin/env python3
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import exocortex_deploy


class DeployTests(unittest.TestCase):
    def test_install_is_machine_neutral_and_rollbackable(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "runtime"
            source = Path(__file__).resolve().parent
            first = exocortex_deploy.install(prefix, source)
            self.assertTrue((first / "goms-v2" / "mcp_server.py").is_file())
            self.assertTrue((first / "goms-v2" / "uv.lock").is_file())
            self.assertTrue((first / "model-routing" / "router.py").is_file())
            self.assertTrue((first / "model-routing" / "fleet.json").is_file())
            self.assertTrue((first / "hermes" / "SOUL.md").is_file())
            self.assertTrue((first / "hermes" / "install_profile.py").is_file())
            self.assertTrue((first / "delivery-controller" / "delivery.py").is_file())
            self.assertTrue((first / "hermes" / "skills" / "exocortex-executive" / "SKILL.md").is_file())
            self.assertFalse((first / "goms-v2" / ".venv").exists())
            self.assertFalse((first / "goms-v2" / "goms.sqlite3").exists())
            self.assertFalse((first / "goms-v2" / "events.jsonl").exists())
            cfg = exocortex_deploy.hermes_fragment(first)
            server = cfg["mcp_servers"]["goms"]
            self.assertEqual(
                cfg["mcp_servers"]["goms"]["command"],
                str((prefix / "venvs" / "goms" / "bin" / "python").resolve()),
            )
            self.assertEqual(server["env"]["EXOCORTEX_GOMS_ROOT"],
                             str(first / "goms-v2"))
            self.assertEqual(server["env"]["AINEKO_MODEL_ROUTER_PATH"],
                             str(first / "model-routing" / "router.py"))
            self.assertEqual(Path(server["env"]["GOMS_HOME"]),
                             (prefix / "data" / "goms").resolve())
            self.assertNotIn("/Users/", server["args"][0])
            self.assertNotIn("/Users/", server["env"]["EXOCORTEX_GOMS_ROOT"])
            self.assertNotIn("/Users/", server["env"]["AINEKO_MODEL_ROUTER_PATH"])
            self.assertNotIn("/Users/", server["env"]["GOMS_HOME"])
            exocortex_deploy.install(prefix, source)
            self.assertTrue((prefix / ".previous" / "goms-v2" / "mcp_server.py").is_file())

    def test_runtime_sync_uses_packaged_lock_and_stable_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "runtime"
            source = Path(__file__).resolve().parent
            release = exocortex_deploy.install(prefix, source)
            python = (prefix / "venvs" / "goms" / "bin" / "python").resolve()
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\n")
            with mock.patch.object(exocortex_deploy.subprocess, "run") as run:
                result = exocortex_deploy.ensure_goms_runtime(release)
            self.assertEqual(result, python)
            args = run.call_args.args[0]
            self.assertEqual(args[:2], ["uv", "sync"])
            self.assertIn(str(release / "goms-v2"), args)
            self.assertEqual(
                run.call_args.kwargs["env"]["UV_PROJECT_ENVIRONMENT"],
                str((prefix / "venvs" / "goms").resolve()),
            )




if __name__ == "__main__":
    unittest.main(verbosity=2)
