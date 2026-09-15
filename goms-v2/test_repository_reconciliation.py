#!/usr/bin/env python3
import subprocess
import tempfile
import unittest
from pathlib import Path

from goms_store import GomsStore
from repository_reconciliation import (
    RepositoryReconciliationPolicy,
    reconcile_repository_tasks,
)


def git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=path, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return result.stdout.strip()


class RepositoryReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="repo-reconcile-")
        self.root = Path(self.tmp.name)
        self.remote = self.root / "remote.git"
        self.repo = self.root / "repo"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True,
                       stdout=subprocess.DEVNULL)
        subprocess.run(["git", "clone", str(self.remote), str(self.repo)], check=True,
                       stdout=subprocess.DEVNULL)
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Test User")
        (self.repo / "README.md").write_text("baseline\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "baseline")
        git(self.repo, "branch", "-M", "main")
        git(self.repo, "push", "-u", "origin", "main")
        git(self.repo, "branch", "archive/preserved-snapshot")

        self.goms = self.root / "goms"
        self.store = GomsStore(self.goms)
        self.store.create_branch(
            "Repository reconciliation",
            project="test",
            status="BLOCKED",
            objective="Safely reconcile local checkout with upstream.",
            last_result="Local checkout may contain unique work.",
            next_action="Verify preservation and synchronization.",
            branch_id="repo-local",
            actor="test",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def policy(self, *refs: str) -> RepositoryReconciliationPolicy:
        return RepositoryReconciliationPolicy(
            task_id="repo-local",
            repository=self.repo,
            canonical_branch="main",
            upstream_ref="origin/main",
            required_preservation_refs=tuple(refs),
        )

    def branch(self):
        with self.store.connect() as con:
            return dict(con.execute(
                "SELECT status,last_result,unresolved,next_action,blocker FROM branches WHERE id=?",
                ("repo-local",),
            ).fetchone())

    def test_clean_aligned_repository_with_preservation_is_concluded(self):
        result = reconcile_repository_tasks(
            self.goms, [self.policy("refs/heads/archive/preserved-snapshot")]
        )
        self.assertEqual(result[0]["disposition"], "CONCLUDED")
        branch = self.branch()
        self.assertEqual(branch["status"], "CONCLUDED")
        self.assertEqual(branch["blocker"], "")
        self.assertIn("exactly aligned", branch["last_result"])
        self.assertIn("routine synchronization", branch["next_action"])

    def test_dirty_repository_remains_blocked(self):
        (self.repo / "local.txt").write_text("uncommitted\n")
        result = reconcile_repository_tasks(
            self.goms, [self.policy("refs/heads/archive/preserved-snapshot")]
        )
        self.assertEqual(result[0]["disposition"], "BLOCKED")
        self.assertIn("dirty_worktree", result[0]["reasons"])
        self.assertEqual(self.branch()["status"], "BLOCKED")

    def test_missing_preservation_ref_remains_blocked(self):
        result = reconcile_repository_tasks(
            self.goms, [self.policy("refs/heads/archive/missing-snapshot")]
        )
        self.assertEqual(result[0]["disposition"], "BLOCKED")
        self.assertIn("missing_preservation_ref", result[0]["reasons"])
        self.assertEqual(self.branch()["status"], "BLOCKED")

    def test_moved_preservation_ref_remains_blocked(self):
        actual = git(self.repo, "rev-parse", "refs/heads/archive/preserved-snapshot")
        policy = RepositoryReconciliationPolicy(
            task_id="repo-local", repository=self.repo,
            canonical_branch="main", upstream_ref="origin/main",
            required_preservation_refs=("refs/heads/archive/preserved-snapshot",),
            required_preservation_commits=((
                "refs/heads/archive/preserved-snapshot", "0" * 40,
            ),),
        )
        self.assertNotEqual(actual, "0" * 40)
        result = reconcile_repository_tasks(self.goms, [policy])
        self.assertEqual(result[0]["disposition"], "BLOCKED")
        self.assertIn("preservation_ref_mismatch", result[0]["reasons"])
        self.assertEqual(self.branch()["status"], "BLOCKED")

    def test_local_ahead_repository_remains_blocked(self):
        (self.repo / "ahead.txt").write_text("local-only\n")
        git(self.repo, "add", "ahead.txt")
        git(self.repo, "commit", "-m", "local ahead")
        result = reconcile_repository_tasks(
            self.goms, [self.policy("refs/heads/archive/preserved-snapshot")]
        )
        self.assertEqual(result[0]["disposition"], "BLOCKED")
        self.assertIn("not_aligned", result[0]["reasons"])
        self.assertEqual(self.branch()["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
