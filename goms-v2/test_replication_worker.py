#!/usr/bin/env python3
import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

from replication_worker import (
    classify_failure,
    redact_auth_output,
    retry_allowed,
    mark_job_failure,
    queue_has_human_authorization_boundary,
    _run,
)


class ReplicationWorkerPolicyTests(unittest.TestCase):
    def test_tailscale_additional_check_is_human_authorization_boundary(self):
        text = "# Tailscale SSH requires an additional check.\n# To authenticate, visit: https://login.tailscale.com/a/secret"
        self.assertEqual(classify_failure(text), "human_authorization_required")

    def test_authentication_url_is_not_persisted(self):
        text = "To authenticate, visit: https://login.tailscale.com/a/secret-token"
        cleaned = redact_auth_output(text)
        self.assertNotIn("login.tailscale.com", cleaned)
        self.assertNotIn("secret-token", cleaned)
        self.assertIn("authentication URL redacted", cleaned)

    def test_human_authorization_failure_never_auto_retries(self):
        job = {"status": "human_authorization_required"}
        self.assertFalse(retry_allowed(job, now=datetime.now(timezone.utc)))

    def test_timeout_preserves_partial_auth_output_for_classification(self):
        timeout = __import__('subprocess').TimeoutExpired(
            cmd=['tailscale','ssh'], timeout=30,
            output=b'', stderr=b'# Tailscale SSH requires an additional check.\n')
        with patch('replication_worker.subprocess.run', side_effect=timeout):
            cp=_run(['tailscale','ssh'],30)
        self.assertEqual(cp.returncode,124)
        self.assertEqual(classify_failure((cp.stdout or '')+(cp.stderr or '')),
                         'human_authorization_required')

    def test_queue_pauses_when_any_job_requires_human_authorization(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'a.json').write_text(json.dumps({'status':'pending'}))
            (root/'b.json').write_text(json.dumps({'status':'human_authorization_required'}))
            self.assertTrue(queue_has_human_authorization_boundary(root))
            (root/'b.json').write_text(json.dumps({'status':'pending'}))
            self.assertFalse(queue_has_human_authorization_boundary(root))

    def test_transient_failure_uses_backoff(self):
        now = datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc)
        job = {"status": "retryable", "next_retry_at": (now + timedelta(minutes=5)).isoformat()}
        self.assertFalse(retry_allowed(job, now=now))
        self.assertTrue(retry_allowed(job, now=now + timedelta(minutes=6)))

    def test_mark_human_required_preserves_job_and_redacts_detail(self):
        now = datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "job.json"
            p.write_text(json.dumps({"status": "pending", "conversation_id": "c1"}))
            mark_job_failure(
                p,
                "human_authorization_required",
                "visit https://login.tailscale.com/a/secret-token",
                now=now,
            )
            self.assertTrue(p.exists())
            data = json.loads(p.read_text())
            self.assertEqual(data["status"], "human_authorization_required")
            self.assertEqual(data["failure_class"], "human_authorization_required")
            self.assertNotIn("login.tailscale.com", data["last_error"])
            self.assertEqual(data.get("attempt_count", 0), 0)

    def test_transient_failure_increments_attempt_and_sets_retry_time(self):
        now = datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "job.json"
            p.write_text(json.dumps({"status": "pending"}))
            mark_job_failure(p, "transient", "connection reset", now=now)
            data = json.loads(p.read_text())
            self.assertEqual(data["status"], "retryable")
            self.assertEqual(data["attempt_count"], 1)
            self.assertGreater(datetime.fromisoformat(data["next_retry_at"]), now)


if __name__ == "__main__":
    unittest.main(verbosity=2)
