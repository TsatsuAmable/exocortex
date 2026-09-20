#!/usr/bin/env python3
"""Tests for scripts/reconcile_authority_audit.py."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "reconcile_authority_audit.py"


def _ts(minute):
    return f"2026-09-20T10:{minute:02d}:00+00:00"


class ReconcileAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "authority"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_journal(self, entries):
        (self.root / "audit.jsonl").write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n",
            encoding="utf-8")

    def write_state(self, mode):
        (self.root / "state.json").write_text(json.dumps({"mode": mode}),
                                              encoding="utf-8")

    def run_script(self, *extra):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *extra],
            capture_output=True, text=True)

    def test_clean_journal_ok(self):
        self.write_journal([
            {"action": "mode_change", "at": _ts(0), "principal": "local-human",
             "mode": "OBSERVE", "result": "entered", "target": "hermes",
             "detail": {"from": "OBSERVE", "to": "OPERATE", "reason": "r"}},
            {"action": "audited_action", "at": _ts(1), "principal": "local-human",
             "mode": "OPERATE", "result": "ok"},
        ])
        self.write_state("OPERATE")
        proc = self.run_script()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("verdict: OK", proc.stdout)

    def test_corrupt_line_detected(self):
        self.root.joinpath("audit.jsonl").write_text(
            '{"action": "x", "at": "' + _ts(0) + '", "principal": "p", "mode": "OBSERVE"}\n'
            'not-json-at-all\n', encoding="utf-8")
        proc = self.run_script()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("corrupt JSON", proc.stdout)

    def test_missing_fields_detected(self):
        self.write_journal([{"action": "x", "at": _ts(0)}])
        proc = self.run_script()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("missing fields", proc.stdout)

    def test_backwards_timestamp_detected(self):
        self.write_journal([
            {"action": "a", "at": _ts(5), "principal": "p", "mode": "OBSERVE"},
            {"action": "b", "at": _ts(1), "principal": "p", "mode": "OBSERVE"},
        ])
        proc = self.run_script()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("timestamp goes backwards", proc.stdout)

    def test_skip_level_escalation_detected(self):
        # OBSERVE(0) -> RECOVERY(3) skips OPERATE/ADMIN.
        self.write_journal([
            {"action": "mode_change", "at": _ts(0), "principal": "p",
             "mode": "OBSERVE", "detail": {"from": "OBSERVE", "to": "RECOVERY"}},
        ])
        self.write_state("RECOVERY")
        proc = self.run_script()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("skipped levels", proc.stdout)

    def test_silent_deescalation_detected(self):
        self.write_journal([
            {"action": "mode_change", "at": _ts(0), "principal": "p",
             "mode": "OBSERVE", "detail": {"from": "OBSERVE", "to": "ADMIN"}},
            # Silent drop to OBSERVE with no exit/expire event.
            {"action": "audited_action", "at": _ts(1), "principal": "p",
             "mode": "OBSERVE"},
        ])
        self.write_state("OBSERVE")
        proc = self.run_script()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("silent de-escalation", proc.stdout)

    def test_lease_expired_deescalates(self):
        self.write_journal([
            {"action": "mode_change", "at": _ts(0), "principal": "p",
             "mode": "OBSERVE", "detail": {"from": "OBSERVE", "to": "OPERATE"}},
            {"action": "mode_change", "at": _ts(1), "principal": "p",
             "mode": "OPERATE", "detail": {"from": "OPERATE", "to": "ADMIN"}},
            {"action": "lease_expired", "at": _ts(2), "principal": "p",
             "mode": "ADMIN", "result": "deescalated",
             "detail": {"from": "ADMIN", "expired_at": _ts(2)}},
        ])
        self.write_state("OBSERVE")
        proc = self.run_script()
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_state_disagreement_detected(self):
        self.write_journal([
            {"action": "mode_change", "at": _ts(0), "principal": "p",
             "mode": "OBSERVE", "detail": {"from": "OBSERVE", "to": "OPERATE"}},
        ])
        self.write_state("ADMIN")
        proc = self.run_script()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("disagrees with journal-implied mode", proc.stdout)

    def test_missing_state_with_entries_detected(self):
        self.write_journal([
            {"action": "mode_change", "at": _ts(0), "principal": "p",
             "mode": "OBSERVE", "detail": {"from": "OBSERVE", "to": "OPERATE"}},
        ])
        proc = self.run_script()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("state file missing", proc.stdout)

    def test_json_output_flag(self):
        self.write_journal([
            {"action": "mode_change", "at": _ts(0), "principal": "p",
             "mode": "OBSERVE", "detail": {"from": "OBSERVE", "to": "OPERATE"}},
        ])
        self.write_state("OPERATE")
        proc = self.run_script("--json")
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertEqual(data["entries"], 1)
        self.assertTrue(data["state_consistent"])

    def test_empty_journal_no_entries_state_absent_ok(self):
        (self.root / "audit.jsonl").write_text("", encoding="utf-8")
        proc = self.run_script()
        self.assertEqual(proc.returncode, 0, proc.stdout)


if __name__ == "__main__":
    unittest.main()