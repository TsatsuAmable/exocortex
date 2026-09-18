#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

from hermes_authority import HermesAuthority
from hermes_machine_tools import HermesMachineTools


class FakeAdapter:
    def __init__(self):
        self.calls = []
    def run_user(self, argv, timeout=120):
        self.calls.append(("user", argv))
        return type("R", (), {"returncode": 0, "stdout": "user-ok", "stderr": ""})()
    def run_admin(self, argv, timeout=120):
        self.calls.append(("admin", argv))
        return type("R", (), {"returncode": 0, "stdout": "admin-ok", "stderr": ""})()
    def recovery(self, action, **kwargs):
        self.calls.append(("recovery", action))
        return type("R", (), {"returncode": 0, "stdout": "recovered", "stderr": ""})()


class HermesMachineToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hermes-tools-")
        self.auth = HermesAuthority(Path(self.tmp.name))
        self.adapter = FakeAdapter()
        self.tools = HermesMachineTools(self.auth, self.adapter)
    def tearDown(self):
        self.tmp.cleanup()
    def test_status_is_observe_by_default(self):
        self.assertEqual(self.tools.authority_status()["mode"], "OBSERVE")
    def test_explicit_human_authorization_controls_elevation(self):
        with self.assertRaises(PermissionError):
            self.tools.authority_enter("OPERATE", principal="user")
        out = self.tools.authority_enter("OPERATE", principal="user",
                                         human_authorized=True)
        self.assertEqual(out["mode"], "OPERATE")
    def test_machine_surface_uses_argv_not_shell_string(self):
        self.auth.enter("OPERATE", principal="user", human_authorized=True)
        out = self.tools.machine_run(["printf", "hello"])
        self.assertTrue(out["ok"])
        self.assertEqual(self.adapter.calls[-1], ("user", ["printf", "hello"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
