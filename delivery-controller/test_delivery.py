import tempfile
import unittest
from pathlib import Path

from delivery import Store, Controller, PrObservation


class NoGoms:
    def create(self, *args, **kwargs): return None
    def checkpoint(self, *args, **kwargs): return None


class FakeGitHub:
    def __init__(self, obs): self.obs = obs
    def observe_pr(self, repo, number): return self.obs


class DeliveryControllerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.td.name) / "test.sqlite3")
        self.goms = NoGoms()

    def tearDown(self):
        self.td.cleanup()

    def test_submit_is_non_destructive_without_pr(self):
        jid = self.store.submit("o/r", "do thing", "observe", "none", None, self.goms)
        Controller(self.store, self.goms, FakeGitHub(None)).tick(jid)
        self.assertEqual(self.store.get(jid)["state"], "CREATED")

    def test_failed_ci_moves_to_wait_ci(self):
        jid = self.store.submit("o/r", "fix", "observe", "none", 7, self.goms)
        obs = PrObservation(False, False, "failed", ["unit"], [], "", "DIRTY", "https://example/pr/7")
        Controller(self.store, self.goms, FakeGitHub(obs)).tick(jid)
        job = self.store.get(jid)
        self.assertEqual(job["state"], "WAIT_CI")
        self.assertIn("unit", job["last_result"])

    def test_approval_gate_waits_for_human_policy_evidence(self):
        jid = self.store.submit("o/r", "fix", "observe", "none", 10, self.goms)
        obs = PrObservation(False, False, "failed", ["approval-gate"], [], "", "BLOCKED", "https://example/pr/10")
        Controller(self.store, self.goms, FakeGitHub(obs)).tick(jid)
        job = self.store.get(jid)
        self.assertEqual(job["state"], "WAIT_APPROVAL")
        self.assertIn("observe-only", job["next_action"])

    def test_green_pr_stops_at_merge_gate(self):
        jid = self.store.submit("o/r", "fix", "observe", "none", 8, self.goms)
        obs = PrObservation(False, False, "green", [], [], "APPROVED", "CLEAN", "https://example/pr/8")
        Controller(self.store, self.goms, FakeGitHub(obs)).tick(jid)
        job = self.store.get(jid)
        self.assertEqual(job["state"], "MERGE_GATE")
        self.assertIn("never auto-merges", job["next_action"])

    def test_merged_pr_is_observed(self):
        jid = self.store.submit("o/r", "fix", "observe", "none", 9, self.goms)
        obs = PrObservation(True, False, "green", [], [], "APPROVED", "CLEAN", "https://example/pr/9")
        Controller(self.store, self.goms, FakeGitHub(obs)).tick(jid)
        self.assertEqual(self.store.get(jid)["state"], "MERGED")


if __name__ == "__main__":
    unittest.main()
