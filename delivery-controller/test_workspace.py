import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import workspace
from delivery import Store


class WorkspacePolicyTests(unittest.TestCase):
    def test_patch_paths_extracts_both_existing_and_new_files(self):
        text = """diff --git a/src/a.ts b/src/a.ts
--- a/src/a.ts
+++ b/src/a.ts
@@ -1 +1 @@
-x
+y
diff --git a/tests/b.ts b/tests/b.ts
--- /dev/null
+++ b/tests/b.ts
"""
        self.assertEqual(workspace.patch_paths(text), ["src/a.ts", "tests/b.ts"])

    def test_policy_blocks_governance_paths(self):
        policy = {"blocked_paths": [".github", "governance", "AGENTS.md"]}
        with self.assertRaisesRegex(workspace.WorkspaceError, "policy blocks"):
            workspace.ensure_allowed([".github/workflows/ci.yml"], policy)

    def test_observe_authority_cannot_write(self):
        job = {"id": "job_x", "authority": "observe", "pr_number": 7}
        with self.assertRaisesRegex(workspace.WorkspaceError, "lacks PR write authority"):
            workspace.require_pr_authority(job)

    def test_pr_authority_is_sufficient_for_bounded_tools(self):
        workspace.require_pr_authority({"id": "job_x", "authority": "pr", "pr_number": 7})


class WorkspacePushTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.store = Store(self.root / "delivery.sqlite3")
        self.job = self.store.submit("o/r", "patch", "pr", "none", 7, NoGoms())

    def tearDown(self):
        self.td.cleanup()


class NoGoms:
    def create(self, *args, **kwargs): return None
    def checkpoint(self, *args, **kwargs): return None
