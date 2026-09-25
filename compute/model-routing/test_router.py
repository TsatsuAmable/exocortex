#!/usr/bin/env python3
import importlib.util
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("router_under_test", HERE / "router.py")
router = importlib.util.module_from_spec(spec)
spec.loader.exec_module(router)


class LifecycleTests(unittest.TestCase):
    def test_retiring_candidate_enters_draining_state(self):
        state, penalty = router.lifecycle_state(
            {"retire_at": "2026-09-25T00:00:00Z"},
            now=datetime(2026, 9, 20, tzinfo=timezone.utc),
        )
        self.assertEqual(state, "draining")
        self.assertGreater(penalty, 0)

    def test_unqualified_candidate_is_ineligible(self):
        self.assertFalse(router.eligible(
            {"privacy": "non_sensitive", "mode": "direct", "context": 0},
            {"qualification": "unqualified", "privacy": "non_sensitive"},
        ))

    def test_retired_candidate_is_ineligible(self):
        with mock.patch.object(router, "lifecycle_state", return_value=("retired", 99)):
            self.assertFalse(router.eligible(
                {"privacy": "non_sensitive", "mode": "direct", "context": 0},
                {"privacy": "non_sensitive"},
            ))


class FleetRoutingTests(unittest.TestCase):
    def test_goms_cold_start_prefers_active_qualified_nonretiring_model(self):
        # This scenario verifies pre-retirement drain ordering, not today's fleet
        # state. Freeze lifecycle evaluation before the candidate's retire_at so
        # the test remains valid after 2026-09-25.
        lifecycle_state = router.lifecycle_state
        fixed_now = datetime(2026, 9, 20, tzinfo=timezone.utc)
        with mock.patch.object(
            router, "lifecycle_state",
            side_effect=lambda candidate, now=None: lifecycle_state(candidate, now=fixed_now),
        ):
            rows = router.rank_candidates({
                "prompt": "Extract durable semantic state as JSON",
                "family": "goms-distillation",
                "privacy": "non_sensitive",
                "mode": "direct",
                "context": 8192,
            })
        self.assertTrue(rows)
        self.assertEqual(rows[0]["model"], "glm-5.3-flash:cloud")
        retiring = next(x for x in rows if x["model"] == "deepseek-v4-flash:cloud")
        self.assertEqual(retiring["lifecycle_state"], "draining")
        self.assertNotEqual(rows[0]["model"], retiring["model"])

    def test_router_exposes_adapter_and_billing_metadata(self):
        row = router.rank_candidates({
            "prompt": "hello",
            "family": "general",
            "privacy": "non_sensitive",
            "mode": "direct",
            "context": 1,
        })[0]
        self.assertIn("adapter", row)
        self.assertIn("billing_class", row)


if __name__ == "__main__":
    unittest.main()
