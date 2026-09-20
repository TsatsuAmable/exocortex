#!/usr/bin/env python3
"""Tests for scripts/generate_systemd.py (mirrors test_generate_launchd.py)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "generate_systemd.py"
INVENTORY = Path(__file__).resolve().parent.parent / (
    "deploy/launchd/service-inventory.example.json")


def run(args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True)


class GenerateSystemdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="systemd-gen-test-"))
        self.out = self.tmp / "units"
        self.values = self.tmp / "values.json"
        self.values.write_text(json.dumps({
            "GOMS_HOME": "/Users/test/goms",
            "GOMS_VENV_PYTHON": "/Users/test/goms/.venv/bin/python",
            "HERMES_HOME": "/Users/test/.hermes/profiles/gsvaineko",
            "TAILSCALE_BIND_IP": "100.64.0.9",
            "ALLOWED_CLIENT_IP": "100.64.0.2",
            "DELIVERY_CONTROLLER_ROOT": "/Users/test/delivery",
            "EXOCORTEX_CURRENT": "/Users/test/.local/share/exocortex/current",
        }), encoding="utf-8")

    def test_generates_units_for_non_external_services(self):
        proc = run(["--out", str(self.out), "--values", str(self.values)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertGreater(len(report["generated"]), 10)
        # External services never emitted.
        self.assertNotIn("sh-brew-neo4j.service", report["generated"])
        for name in report["generated"]:
            self.assertTrue((self.out / name).exists())

    def test_unit_structure_matches_inventory(self):
        proc = run(["--out", str(self.out), "--values", str(self.values)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        gateway = self.out / "ai-hermes-gateway-gsvaineko.service"
        text = gateway.read_text()
        self.assertIn("[Unit]", text)
        self.assertIn("[Service]", text)
        self.assertIn("[Install]", text)
        self.assertIn("Description=GSV Aineko messaging/agent gateway", text)
        self.assertIn("ExecStart=", text)
        self.assertIn("Restart=always", text)  # keep_alive maps to Restart
        self.assertIn("WantedBy=default.target", text)
        self.assertIn("--profile", text)       # command args preserved
        self.assertIn("gsvaineko", text)
        # Environment expansion from $HERMES_HOME on distillation-workers.
        workers = self.out / "org-aineko-goms-distillation-workers.service"
        env_text = workers.read_text()
        self.assertIn("Environment=AINEKO_MODEL_ROUTER_PATH=/Users/test/.local/share/exocortex/current/model-routing/router.py", env_text)
        # GOMS_HOME appears expanded inside the ExecStart command.
        self.assertIn("/Users/test/goms/distillation_worker_daemon.py", env_text)
        self.assertNotIn("$GOMS_HOME", env_text)

    def test_interval_service_gets_timer(self):
        proc = run(["--out", str(self.out), "--values", str(self.values)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        timer = "org-aineko-goms-distillation-hygiene.timer"
        self.assertIn(timer, report["generated"])
        text = (self.out / timer).read_text()
        self.assertIn("OnUnitActiveSec=300", text)
        self.assertIn("WantedBy=timers.target", text)

    def test_storage_governor_has_daily_timer(self):
        proc = run(["--out", str(self.out), "--values", str(self.values)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        service = self.out / "org-aineko-goms-storage-governor.service"
        timer = self.out / "org-aineko-goms-storage-governor.timer"
        self.assertTrue(service.exists())
        self.assertTrue(timer.exists())
        self.assertIn("storage_governor.py", service.read_text())
        self.assertIn("OnUnitActiveSec=86400", timer.read_text())

    def test_unresolved_placeholders_skip_service(self):
        empty = self.tmp / "empty.json"
        empty.write_text("{}", encoding="utf-8")
        proc = run(["--out", str(self.out), "--values", str(empty)])
        self.assertEqual(proc.returncode, 0)
        report = json.loads(proc.stdout)
        skipped = {name: missing for name, missing in report["skipped"]}
        self.assertIn("org-aineko-goms-manfred-read.service", skipped)
        self.assertNotIn("org-aineko-goms-manfred-read.service",
                         report["generated"])

    def test_strict_mode_fails_on_unresolved(self):
        empty = self.tmp / "empty.json"
        empty.write_text("{}", encoding="utf-8")
        proc = run(["--out", str(self.out), "--values", str(empty),
                    "--strict"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("unresolved", proc.stderr + proc.stdout)

    def test_working_directory_and_env_sorting(self):
        proc = run(["--out", str(self.out), "--values", str(self.values)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # WorkingDirectory comes from the inventory ($HERMES_HOME on gateway).
        gateway = self.out / "ai-hermes-gateway-gsvaineko.service"
        text = gateway.read_text()
        self.assertIn("WorkingDirectory=/Users/test/.hermes/profiles/gsvaineko", text)
        # Environment entries sorted by key for deterministic output.
        env_lines = [ln for ln in text.splitlines()
                     if ln.startswith("Environment=")]
        self.assertEqual(env_lines, sorted(env_lines))


if __name__ == "__main__":
    unittest.main(verbosity=2)