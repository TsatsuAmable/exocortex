#!/usr/bin/env python3
"""Tests for compute/model-routing/provider_lifecycle.py."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import provider_lifecycle


def run(*argv):
    """Invoke the CLI in-process so tests can patch provider internals."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = provider_lifecycle.main(list(argv))
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    return SimpleNamespace(returncode=code, stdout=stdout.getvalue(),
                           stderr=stderr.getvalue())


from contextlib import contextmanager


@contextmanager
def mock_tags(tags):
    with mock.patch.object(provider_lifecycle, "fetch_ollama_tags",
                           lambda timeout=5.0: tags):
        yield


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fleet_path = self.root / "fleet.json"
        self.digests_path = self.root / "model-digests.json"
        self.audit_path = self.root / "lifecycle-audit.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def write_fleet(self, candidates):
        self.fleet_path.write_text(
            json.dumps({"candidates": candidates}), encoding="utf-8")

    def run_lifecycle(self, *argv):
        # Common options are registered on the subparsers, so the subcommand
        # must come first and options follow it.
        return run(*argv,
                   "--fleet", str(self.fleet_path),
                   "--digests", str(self.digests_path),
                   "--audit", str(self.audit_path))


class DigestTests(Base):
    def test_digest_record_then_demote_on_change(self):
        self.write_fleet([
            {"id": "local-qualified", "provider": "local-ollama",
             "adapter": "ollama", "model": "model-a",
             "qualification": "qualified"},
            {"id": "local-prov", "provider": "local-ollama",
             "adapter": "ollama", "model": "model-b",
             "qualification": "provisional"},
            {"id": "cloud-cand", "provider": "ollama-cloud",
             "adapter": "opencode", "model": "cloud-model",
             "qualification": "qualified"},
        ])
        with mock_tags({"model-a": "d1", "model-b": "d2"}):
            proc = self.run_lifecycle("digest")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["demoted"], [])
        self.assertEqual(out["changed"], [])
        digests = json.loads(self.digests_path.read_text())
        self.assertEqual(digests["local-qualified"]["digest"], "d1")

        with mock_tags({"model-a": "d1-CHANGED", "model-b": "d2"}):
            proc = self.run_lifecycle("digest")
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout)
        self.assertEqual(out["changed"], ["local-qualified"])
        self.assertEqual(out["demoted"], ["local-qualified"])
        fleet = json.loads(self.fleet_path.read_text())
        by_id = {c["id"]: c for c in fleet["candidates"]}
        self.assertEqual(by_id["local-qualified"]["qualification"], "provisional")
        audit_lines = [json.loads(l) for l in
                       self.audit_path.read_text().splitlines() if l.strip()]
        actions = [e["action"] for e in audit_lines]
        self.assertIn("digest_recorded", actions)
        self.assertIn("digest_changed", actions)
        self.assertIn("requalified", actions)

    def test_digest_ollama_unreachable_fails_closed(self):
        self.write_fleet([
            {"id": "local-cand", "provider": "local-ollama",
             "adapter": "ollama", "model": "model-a",
             "qualification": "qualified"},
        ])
        with mock_tags(None):
            proc = self.run_lifecycle("digest")
        self.assertEqual(proc.returncode, 2)
        out = json.loads(proc.stdout)
        self.assertFalse(out["ok"])
        self.assertFalse(self.digests_path.exists())

    def test_digest_skips_disabled_and_cloud(self):
        self.write_fleet([
            {"id": "cloud-only", "provider": "ollama-cloud",
             "adapter": "opencode", "model": "cloud-model"},
            {"id": "local-off", "provider": "local-ollama", "enabled": False,
             "adapter": "ollama", "model": "model-x"},
        ])
        with mock_tags({"model-a": "d1"}):
            proc = self.run_lifecycle("digest")
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout)
        self.assertEqual(out["tracked"], 0)


class RequalifyTests(Base):
    def test_requalify_transition_and_audit(self):
        self.write_fleet([
            {"id": "c1", "provider": "ollama-cloud", "adapter": "opencode",
             "qualification": "provisional"},
        ])
        proc = self.run_lifecycle("requalify", "--id", "c1",
                                  "--to", "unqualified",
                                  "--reason", "benchmarks below threshold")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        fleet = json.loads(self.fleet_path.read_text())
        self.assertEqual(fleet["candidates"][0]["qualification"], "unqualified")
        audit = [json.loads(l) for l in
                 self.audit_path.read_text().splitlines() if l.strip()]
        self.assertEqual(audit[-1]["action"], "requalified")
        self.assertEqual(audit[-1]["to"], "unqualified")

    def test_upgrade_to_qualified_requires_reason(self):
        self.write_fleet([
            {"id": "c1", "provider": "ollama-cloud", "adapter": "opencode",
             "qualification": "provisional"},
        ])
        proc = self.run_lifecycle("requalify", "--id", "c1", "--to", "qualified")
        self.assertEqual(proc.returncode, 2)
        out = json.loads(proc.stdout)
        self.assertFalse(out["ok"])
        self.assertIn("reason", out["error"])
        fleet = json.loads(self.fleet_path.read_text())
        self.assertEqual(fleet["candidates"][0]["qualification"], "provisional")

    def test_upgrade_to_qualified_with_reason_writes_fleet(self):
        self.write_fleet([
            {"id": "c1", "provider": "ollama-cloud", "adapter": "opencode",
             "qualification": "provisional"},
        ])
        proc = self.run_lifecycle("requalify", "--id", "c1", "--to", "qualified",
                                  "--reason", "12/12 benchmark pass, latency ok")
        self.assertEqual(proc.returncode, 0)
        fleet = json.loads(self.fleet_path.read_text())
        self.assertEqual(fleet["candidates"][0]["qualification"], "qualified")

    def test_requalify_unknown_id_fails(self):
        self.write_fleet([
            {"id": "c1", "provider": "ollama-cloud", "adapter": "opencode"},
        ])
        proc = self.run_lifecycle("requalify", "--id", "nope", "--to", "provisional")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown candidate", proc.stdout)

    def test_requalify_invalid_target_fails(self):
        self.write_fleet([
            {"id": "c1", "provider": "ollama-cloud", "adapter": "opencode"},
        ])
        proc = self.run_lifecycle("requalify", "--id", "c1", "--to", "bogus")
        self.assertEqual(proc.returncode, 2)
        # argparse choices guard fires before JSON output; usage goes to stderr.
        combined = proc.stdout + proc.stderr
        self.assertIn("invalid choice", combined)

    def test_retire_at_set_and_cleared(self):
        self.write_fleet([
            {"id": "c1", "provider": "ollama-cloud", "adapter": "opencode",
             "qualification": "qualified", "retire_at": "2026-09-25T00:00:00Z"},
        ])
        proc = self.run_lifecycle("requalify", "--id", "c1", "--to", "qualified",
                                  "--retire-at", "none")
        self.assertEqual(proc.returncode, 0)
        fleet = json.loads(self.fleet_path.read_text())
        self.assertNotIn("retire_at", fleet["candidates"][0])

        proc = self.run_lifecycle("requalify", "--id", "c1", "--to", "qualified",
                                  "--retire-at", "2026-10-25T00:00:00Z")
        self.assertEqual(proc.returncode, 0)
        fleet = json.loads(self.fleet_path.read_text())
        self.assertEqual(fleet["candidates"][0]["retire_at"],
                         "2026-10-25T00:00:00Z")

    def test_missing_fleet_file_fails(self):
        proc = self.run_lifecycle("verify")
        self.assertNotEqual(proc.returncode, 0)


class VerifyTests(Base):
    def test_verify_ok_on_healthy_fixture(self):
        self.write_fleet([
            {"id": "local-ok", "provider": "local-ollama", "adapter": "ollama",
             "model": "model-a", "qualification": "qualified"},
            {"id": "cloud-ok", "provider": "ollama-cloud", "adapter": "opencode",
             "model": "cloud-model", "qualification": "provisional"},
        ])
        self.digests_path.write_text(json.dumps(
            {"local-ok": {"model": "model-a", "digest": "d1",
                          "recorded_at": "2026-09-20T00:00:00+00:00"}}))
        with mock_tags({"model-a": "d1"}):
            proc = self.run_lifecycle("verify")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        out = json.loads(proc.stdout)
        self.assertEqual(out["verdict"], "OK")
        self.assertEqual(out["findings"], [])

    def test_verify_detects_missing_local_model(self):
        self.write_fleet([
            {"id": "local-gone", "provider": "local-ollama", "adapter": "ollama",
             "model": "missing-model", "qualification": "qualified"},
        ])
        with mock_tags({"model-a": "d1"}):
            proc = self.run_lifecycle("verify")
        self.assertEqual(proc.returncode, 1)
        out = json.loads(proc.stdout)
        checks = [f["check"] for f in out["findings"]]
        self.assertIn("model_present", checks)

    def test_verify_detects_digest_change(self):
        self.write_fleet([
            {"id": "local-ok", "provider": "local-ollama", "adapter": "ollama",
             "model": "model-a", "qualification": "qualified"},
        ])
        self.digests_path.write_text(json.dumps(
            {"local-ok": {"model": "model-a", "digest": "OLD",
                          "recorded_at": "2026-09-20T00:00:00+00:00"}}))
        with mock_tags({"model-a": "NEW"}):
            proc = self.run_lifecycle("verify")
        self.assertEqual(proc.returncode, 1)
        out = json.loads(proc.stdout)
        checks = [f["check"] for f in out["findings"]]
        self.assertIn("digest", checks)

    def test_verify_detects_missing_config(self):
        self.write_fleet([
            {"id": "bad-cloud", "provider": "ollama-cloud",
             "model": "cloud-model", "qualification": "qualified"},
        ])
        with mock_tags({"model-a": "d1"}):
            proc = self.run_lifecycle("verify")
        self.assertEqual(proc.returncode, 1)
        out = json.loads(proc.stdout)
        checks = [f["check"] for f in out["findings"]]
        self.assertIn("config", checks)

    def test_verify_detects_bad_qualification(self):
        self.write_fleet([
            {"id": "odd", "provider": "ollama-cloud", "adapter": "opencode",
             "qualification": "vibes"},
        ])
        with mock_tags({"model-a": "d1"}):
            proc = self.run_lifecycle("verify")
        self.assertEqual(proc.returncode, 1)
        out = json.loads(proc.stdout)
        checks = [f["check"] for f in out["findings"]]
        self.assertIn("qualification", checks)


if __name__ == "__main__":
    unittest.main()