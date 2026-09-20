#!/usr/bin/env python3
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import model_router_bridge as bridge


class RouterBridgeTests(unittest.TestCase):
    def test_repo_router_is_discoverable(self):
        path = bridge.resolve_router_path()
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "router.py")

    def test_rank_models_returns_shared_router_rows(self):
        rows = bridge.rank_models(
            "Extract durable semantic state as JSON",
            family="goms-distillation",
            privacy="non_sensitive",
            context=8192,
            limit=3,
        )
        self.assertTrue(rows)
        self.assertEqual(rows[0]["model"], "glm-5.3-flash:cloud")

    def test_environment_override_wins(self):
        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / "router.py"
            candidate.write_text("def rank_candidates(task, threshold=0.65): return []\n")
            with mock.patch.dict(os.environ, {"AINEKO_MODEL_ROUTER_PATH": str(candidate)}):
                self.assertEqual(bridge.resolve_router_path(), candidate)


if __name__ == "__main__":
    unittest.main()
