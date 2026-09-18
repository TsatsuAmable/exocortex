#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from hermes_authority import HermesAuthority


class HermesAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hermes-authority-")
        self.auth = HermesAuthority(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_to_observe_without_goms(self):
        state = self.auth.current()
        self.assertEqual(state.mode, "OBSERVE")
        self.assertFalse(self.auth.allows("OPERATE"))

    def test_elevation_requires_explicit_human_authorization(self):
        with self.assertRaises(PermissionError):
            self.auth.enter("ADMIN", principal="user", reason="maintenance")
        self.assertEqual(self.auth.current().mode, "OBSERVE")
        state = self.auth.enter("ADMIN", principal="user", reason="maintenance",
                                human_authorized=True)
        self.assertEqual(state.mode, "ADMIN")
        self.assertTrue(self.auth.allows("OPERATE"))
        self.assertFalse(self.auth.allows("RECOVERY"))

    def test_recovery_and_emergency_are_available_without_goms(self):
        self.auth.enter("RECOVERY", principal="user", reason="repair MCP",
                        human_authorized=True)
        self.assertTrue(self.auth.allows("RECOVERY"))
        self.auth.enter("EMERGENCY", principal="user", reason="break glass",
                        human_authorized=True)
        self.assertTrue(self.auth.allows("EMERGENCY"))

    def test_deescalation_does_not_require_new_authorization(self):
        self.auth.enter("ADMIN", principal="user", human_authorized=True)
        state = self.auth.enter("OBSERVE", principal="user")
        self.assertEqual(state.mode, "OBSERVE")

    def test_mode_changes_and_actions_are_append_only_audited(self):
        self.auth.enter("OPERATE", principal="user", reason="routine",
                        human_authorized=True)
        self.auth.audit("process_start", target="worker", result="ok",
                        detail={"pid": 42})
        lines = self.auth.audit_path.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        first, second = map(json.loads, lines)
        self.assertEqual(first["action"], "mode_change")
        self.assertEqual(first["detail"]["to"], "OPERATE")
        self.assertEqual(second["mode"], "OPERATE")
        self.assertEqual(second["target"], "worker")

    def test_require_enforces_mode_ceiling(self):
        with self.assertRaises(PermissionError):
            self.auth.require("ADMIN")
        self.auth.enter("ADMIN", principal="user", human_authorized=True)
        self.auth.require("ADMIN")


if __name__ == "__main__":
    unittest.main(verbosity=2)
