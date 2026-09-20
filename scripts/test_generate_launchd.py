#!/usr/bin/env python3
"""Tests for scripts/generate_launchd.py."""
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "generate_launchd.py"
INVENTORY = Path(__file__).resolve().parent.parent / (
    "deploy/launchd/service-inventory.example.json")


def run(args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True)


class GenerateLaunchdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="launchd-gen-test-"))
        self.out = self.tmp / "plists"
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

    def test_generates_plists_for_non_external_services(self):
        proc = run(["--out", str(self.out), "--values", str(self.values)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertGreater(len(report["generated"]), 10)
        # External services never emitted.
        self.assertNotIn("sh.brew.neo4j.plist", report["generated"])
        for name in report["generated"]:
            self.assertTrue((self.out / name).exists())

    def test_plist_structure_matches_inventory(self):
        proc = run(["--out", str(self.out), "--values", str(self.values)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        gateway = self.out / "ai.hermes.gateway-gsvaineko.plist"
        tree = ET.parse(gateway)
        d = tree.getroot().find("dict")
        keys = [k.text for k in d.findall("key")]
        self.assertIn("Label", keys)
        self.assertIn("ProgramArguments", keys)
        self.assertIn("RunAtLoad", keys)
        self.assertIn("KeepAlive", keys)
        # Gateway has no env in inventory; env appears on distillation-workers.
        self.assertNotIn("EnvironmentVariables", keys)
        label_idx = keys.index("Label")
        self.assertEqual(d.findall("string")[0].text,
                         "ai.hermes.gateway-gsvaineko")
        # Environment expansion from $HERMES_HOME on distillation-workers.
        workers = self.out / "org.aineko.goms-distillation-workers.plist"
        env_text = "".join(workers.read_text().splitlines())
        self.assertIn("/Users/test/goms", env_text)
        self.assertIn("/Users/test/.local/share/exocortex/current", env_text)
        self.assertNotIn("$GOMS_HOME", env_text)

    def test_interval_service_has_start_interval(self):
        proc = run(["--out", str(self.out), "--values", str(self.values)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        hygiene = self.out / "org.aineko.goms-distillation-hygiene.plist"
        self.assertIn("<integer>300</integer>", hygiene.read_text())

    def test_unresolved_placeholders_skip_service(self):
        empty = self.tmp / "empty.json"
        empty.write_text("{}", encoding="utf-8")
        proc = run(["--out", str(self.out), "--values", str(empty)])
        self.assertEqual(proc.returncode, 0)
        report = json.loads(proc.stdout)
        skipped = {name: missing for name, missing in report["skipped"]}
        self.assertIn("org.aineko.goms-manfred-read.plist", skipped)
        # Skipped services are not written.
        self.assertNotIn("org.aineko.goms-manfred-read.plist",
                         report["generated"])

    def test_strict_mode_fails_on_unresolved(self):
        empty = self.tmp / "empty.json"
        empty.write_text("{}", encoding="utf-8")
        proc = run(["--out", str(self.out), "--values", str(empty),
                    "--strict"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("unresolved", proc.stderr + proc.stdout)

    def test_plist_xml_is_parseable_with_doctype(self):
        proc = run(["--out", str(self.out), "--values", str(self.values)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for name in json.loads(proc.stdout)["generated"]:
            text = (self.out / name).read_text()
            self.assertTrue(text.startswith('<?xml version="1.0"'))
            self.assertIn("PropertyList-1.0.dtd", text)
            ET.fromstring(text)  # must parse


if __name__ == "__main__":
    unittest.main(verbosity=2)