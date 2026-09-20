#!/usr/bin/env python3
"""Tests for scripts/rescue_executor.py."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PY = sys.executable

VALID_PLAN = {
    "failure_class": "test_class",
    "description": "test",
    "steps": [
        {"id": "step1", "description": "touch file",
         "command": ["touch", "marker1"]},
        {"id": "step2", "description": "another",
         "command": ["bash", "-c", "echo ok"]},
    ],
}


class RescueExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rescue-test-"))
        self.plan_path = self.tmp / "plan.json"
        self.plan_path.write_text(json.dumps(VALID_PLAN))
        self.authority_root = self.tmp / "authority"
        self.journal_root = self.tmp / "journal"
        self.authority_root.mkdir()
        self.journal_root.mkdir()

    def tearDown(self):
        subprocess.run(["chmod", "-R", "u+w", str(self.tmp)],
                       check=False)
        subprocess.run(["rm", "-rf", str(self.tmp)], check=False)

    def _enter_recovery(self):
        goms_v2 = str(SCRIPTS.parent / "goms-v2")
        code = (
            "import sys, pathlib\n"
            "sys.path.insert(0, %r)\n"
            "from hermes_authority import HermesAuthority\n"
            "a = HermesAuthority(%r)\n"
            "a.enter('RECOVERY', principal='test', reason='test',\n"
            "        human_authorized=True, ttl_seconds=3600)\n" % (goms_v2, str(self.authority_root))
        )
        subprocess.run([PY, "-c", code], check=True)

    def _run(self, *extra):
        argv = [PY, str(SCRIPTS / "rescue_executor.py"), "run",
                "--plan", str(self.plan_path),
                "--journal-root", str(self.journal_root),
                "--authority-root", str(self.authority_root), *extra]
        return subprocess.run(argv, capture_output=True, text=True, cwd=str(self.tmp))

    def _journal(self):
        jp = self.journal_root / "test_class" / "journal.jsonl"
        if not jp.exists():
            return []
        return [json.loads(l) for l in jp.read_text().splitlines()]

    def test_validate_ok(self):
        r = subprocess.run([PY, str(SCRIPTS / "rescue_executor.py"), "validate",
                            "--plan", str(self.plan_path)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn('"valid": true', r.stdout)

    def test_run_requires_recovery_authority(self):
        r = self._run()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("RECOVERY", r.stderr)

    def test_run_under_recovery_completes(self):
        self._enter_recovery()
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"outcome": "completed"', r.stdout)
        markers = sorted(p.name for p in self.tmp.glob("marker*"))
        self.assertEqual(markers, ["marker1"])
        events = [rec["event"] for rec in self._journal()]
        self.assertIn("step_completed", events)

    def test_run_resume_skips_completed(self):
        self._enter_recovery()
        self._run()
        self.tmp.joinpath("marker1").unlink()
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"outcome": "skipped_completed"', r.stdout)
        self.assertFalse(self.tmp.joinpath("marker1").exists())

    def test_run_abort_on_failure(self):
        plan = dict(VALID_PLAN)
        plan["steps"] = [
            {"id": "s1", "description": "ok", "command": ["true"]},
            {"id": "s2", "description": "fails", "command": ["false"]},
            {"id": "s3", "description": "never", "command": ["true"]},
        ]
        self.plan_path.write_text(json.dumps(plan))
        self._enter_recovery()
        r = self._run()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('"aborted_at": "s2"', r.stdout)

    def test_run_optional_failure_continues(self):
        plan = dict(VALID_PLAN)
        plan["steps"] = [
            {"id": "s1", "description": "fails but optional",
             "command": ["false"], "optional": True},
            {"id": "s2", "description": "ok", "command": ["true"]},
        ]
        self.plan_path.write_text(json.dumps(plan))
        self._enter_recovery()
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"outcome": "completed"', r.stdout)

    def test_dry_run_no_side_effects(self):
        r = self._run("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"dry_run": true', r.stdout)
        events = [rec["event"] for rec in self._journal()]
        self.assertEqual(events, [])

    def test_run_argv_injects_home(self):
        """Steps using $HOME work even when the ambient env lacks it."""
        import os
        from rescue_executor import run_argv
        saved = os.environ.pop("HOME", None)
        try:
            rc, out, err = run_argv(["bash", "-c", "echo $HOME"])
        finally:
            if saved is not None:
                os.environ["HOME"] = saved
        self.assertEqual(rc, 0, err)
        self.assertTrue(out.strip().startswith("/"), out)

    def test_status_reports_completed(self):
        self._enter_recovery()
        self._run()
        r = subprocess.run([PY, str(SCRIPTS / "rescue_executor.py"), "status",
                            "--failure-class", "test_class",
                            "--journal-root", str(self.journal_root)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("step1", r.stdout)
        self.assertIn("step2", r.stdout)


if __name__ == "__main__":
    unittest.main()