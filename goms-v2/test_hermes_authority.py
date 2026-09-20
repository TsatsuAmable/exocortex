#!/usr/bin/env python3
import json
import tempfile
import time
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

    # ---- lease semantics ----

    def test_elevated_modes_receive_expiring_lease(self):
        state = self.auth.enter("ADMIN", principal="user", human_authorized=True)
        self.assertIsNotNone(state.expires_at)
        self.assertEqual(state.scope, {})
        recovery = self.auth.enter("RECOVERY", principal="user",
                                   human_authorized=True)
        self.assertIsNotNone(recovery.expires_at)
        emergency = self.auth.enter("EMERGENCY", principal="user",
                                    human_authorized=True)
        self.assertIsNotNone(emergency.expires_at)

    def test_operate_persists_without_lease_when_human_authorized(self):
        state = self.auth.enter("OPERATE", principal="user",
                                human_authorized=True)
        self.assertIsNone(state.expires_at)

    def test_operate_can_be_scoped_with_explicit_ttl(self):
        state = self.auth.enter("OPERATE", principal="user",
                                human_authorized=True, ttl_seconds=120)
        self.assertIsNotNone(state.expires_at)
        self.assertTrue(self.auth.allows("OPERATE"))

    def test_expired_lease_auto_deescalates_to_observe(self):
        self.auth.enter("ADMIN", principal="user", human_authorized=True,
                        ttl_seconds=1)
        self.assertTrue(self.auth.allows("ADMIN"))
        time.sleep(1.2)
        state = self.auth.current()
        self.assertEqual(state.mode, "OBSERVE")
        self.assertEqual(state.reason, "lease_expired")
        self.assertFalse(self.auth.allows("OPERATE"))
        self.auth.require("OBSERVE")

    def test_lease_expiry_is_append_only_audited(self):
        self.auth.enter("RECOVERY", principal="user", human_authorized=True,
                        ttl_seconds=1)
        time.sleep(1.2)
        self.auth.current()
        actions = [json.loads(line)["action"]
                   for line in self.auth.audit_path.read_text().splitlines()]
        self.assertIn("lease_expired", actions)
        expired = [json.loads(line) for line in
                   self.auth.audit_path.read_text().splitlines()
                   if json.loads(line)["action"] == "lease_expired"][0]
        self.assertEqual(expired["result"], "deescalated")
        self.assertEqual(expired["detail"]["from"], "RECOVERY")

    def test_lease_expiry_is_lazy_not_scheduled(self):
        """Expiry must not depend on any scheduler: a stale file self-heals on read."""
        self.auth.enter("EMERGENCY", principal="user", human_authorized=True,
                        ttl_seconds=1)
        # Do not call current() before expiry; a fresh reader must still see OBSERVE.
        time.sleep(1.2)
        fresh = HermesAuthority(Path(self.tmp.name))
        self.assertEqual(fresh.current().mode, "OBSERVE")

    def test_ttl_validation_rejects_non_positive(self):
        for bad in (0, -1, -600):
            with self.assertRaises(ValueError):
                self.auth.enter("ADMIN", principal="user", human_authorized=True,
                                ttl_seconds=bad)

    def test_scope_is_recorded_and_audited(self):
        scope = {"actions": ["launchctl", "kickstart"], "targets": ["org.aineko.test"]}
        state = self.auth.enter("ADMIN", principal="user", human_authorized=True,
                                reason="scoped repair", scope=scope)
        self.assertEqual(state.scope, scope)
        record = json.loads(self.auth.audit_path.read_text().splitlines()[-1])
        self.assertEqual(record["detail"]["scope"], scope)

    def test_scope_must_be_dict(self):
        with self.assertRaises(ValueError):
            self.auth.enter("ADMIN", principal="user", human_authorized=True,
                            scope="launchctl")

    def test_legacy_state_without_lease_is_grandfathered(self):
        """A pre-lease state file keeps its authority rather than being dropped."""
        now = "2026-09-19T06:59:05.181755+00:00"
        self.auth.state_path.write_text(json.dumps({
            "entered_at": now, "mode": "OPERATE",
            "principal": "local-human", "reason": "legacy persistent authority",
        }) + "\n", encoding="utf-8")
        state = self.auth.current()
        self.assertEqual(state.mode, "OPERATE")
        self.assertIsNone(state.expires_at)
        self.assertTrue(self.auth.allows("OPERATE"))
        self.assertFalse(self.auth.allows("ADMIN"))

    def test_corrupt_expiry_deescalates_conservatively(self):
        self.auth.state_path.write_text(json.dumps({
            "entered_at": "2026-09-19T06:59:05.181755+00:00",
            "mode": "EMERGENCY", "principal": "local-human",
            "reason": "corrupt lease", "expires_at": "not-a-timestamp",
        }) + "\n", encoding="utf-8")
        self.assertEqual(self.auth.current().mode, "OBSERVE")

    def test_unknown_state_fields_are_tolerated(self):
        self.auth.state_path.write_text(json.dumps({
            "mode": "OPERATE", "principal": "x", "entered_at": "2026-09-19T00:00:00+00:00",
            "reason": "future", "future_field": 1,
        }) + "\n", encoding="utf-8")
        self.assertEqual(self.auth.current().mode, "OPERATE")


if __name__ == "__main__":
    unittest.main(verbosity=2)