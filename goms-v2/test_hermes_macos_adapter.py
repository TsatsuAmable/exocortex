#!/usr/bin/env python3
import subprocess
import tempfile
import unittest
from pathlib import Path

from hermes_authority import HermesAuthority
from hermes_macos_adapter import MacAuthorityAdapter


class MacAuthorityAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hermes-macos-")
        self.auth = HermesAuthority(Path(self.tmp.name))
        self.calls = []
        def runner(argv, **kwargs):
            self.calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")
        self.adapter = MacAuthorityAdapter(self.auth, runner)

    def tearDown(self):
        self.tmp.cleanup()

    def test_observe_cannot_execute_user_or_admin_commands(self):
        with self.assertRaises(PermissionError):
            self.adapter.run_user(["true"])
        with self.assertRaises(PermissionError):
            self.adapter.run_admin(["true"])
        self.assertEqual(self.calls, [])

    def test_operate_can_execute_user_command_but_not_admin(self):
        self.auth.enter("OPERATE", principal="user", human_authorized=True)
        result = self.adapter.run_user(["printf", "hello"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.calls[0][0], ["printf", "hello"])
        with self.assertRaises(PermissionError):
            self.adapter.run_admin(["true"])

    def test_admin_uses_os_owned_sudo_without_credentials(self):
        self.auth.enter("ADMIN", principal="user", human_authorized=True)
        self.adapter.run_admin(["launchctl", "list"])
        self.assertEqual(self.calls[0][0], ["sudo", "--", "launchctl", "list"])

    def test_recovery_restart_requires_recovery_mode(self):
        self.auth.enter("ADMIN", principal="user", human_authorized=True)
        with self.assertRaises(PermissionError):
            self.adapter.recovery("service_restart", label="ai.hermes.gateway")
        self.auth.enter("RECOVERY", principal="user", human_authorized=True)
        self.adapter.recovery("service_restart", label="ai.hermes.gateway")
        argv = self.calls[-1][0]
        self.assertEqual(argv[:3], ["launchctl", "kickstart", "-k"])
        self.assertTrue(argv[-1].endswith("/ai.hermes.gateway"))

    def test_recovery_is_allowlisted_not_arbitrary_shell(self):
        self.auth.enter("RECOVERY", principal="user", human_authorized=True)
        with self.assertRaises(ValueError):
            self.adapter.recovery("shell", label="anything")
        self.assertEqual(self.calls, [])

    def test_execution_is_locally_audited(self):
        self.auth.enter("OPERATE", principal="user", human_authorized=True)
        self.adapter.run_user(["true"])
        lines = self.auth.audit_path.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn('"action": "user_command"', lines[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
