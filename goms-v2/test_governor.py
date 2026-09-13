#!/usr/bin/env python3
import unittest

from governor import decide_reconciliation


def resource(kind="Routine", name="example", desired="loaded", observed="loaded",
             authority="system", failure_class=None, repair=None):
    spec = {"desired_state": desired}
    if repair:
        spec["repair"] = repair
    status = {"observed_state": observed}
    if failure_class:
        status["failure_class"] = failure_class
    return {
        "id": "res_test", "kind": kind, "name": name,
        "spec": spec, "status": status, "authority": authority,
        "generation": 1, "observed_generation": 1,
    }


class GovernorPolicyTests(unittest.TestCase):
    def test_converged_resource_needs_no_action(self):
        decision = decide_reconciliation(resource())
        self.assertEqual(decision["disposition"], "CONVERGED")
        self.assertIsNone(decision["action"])

    def test_human_authorization_boundary_never_auto_repairs(self):
        decision = decide_reconciliation(resource(
            kind="ReplicationQueue", name="chatgpt evidence replica",
            desired="healthy", observed="degraded",
            failure_class="human_authorization_required",
            repair="drain_replication",
        ))
        self.assertEqual(decision["disposition"], "HUMAN_REQUIRED")
        self.assertIsNone(decision["action"])
        self.assertIn("authorization", decision["reason"].lower())

    def test_system_owned_safe_repair_can_run_automatically(self):
        decision = decide_reconciliation(resource(
            observed="missing", repair="launchd_kickstart"))
        self.assertEqual(decision["disposition"], "AUTO_REPAIR")
        self.assertEqual(decision["action"], "launchd_kickstart")

    def test_human_owned_resource_escalates_instead_of_mutating(self):
        decision = decide_reconciliation(resource(
            observed="missing", authority="human", repair="launchd_kickstart"))
        self.assertEqual(decision["disposition"], "HUMAN_REQUIRED")
        self.assertIsNone(decision["action"])

    def test_retry_budget_escalates_after_three_failed_repairs(self):
        item = resource(observed="missing", repair="launchd_kickstart")
        item["attempt_count"] = 3
        decision = decide_reconciliation(item)
        self.assertEqual(decision["disposition"], "ESCALATE")
        self.assertIsNone(decision["action"])

    def test_generation_drift_waits_for_observation_before_repair(self):
        item = resource(observed="missing", repair="launchd_kickstart")
        item["generation"] = 2
        item["observed_generation"] = 1
        decision = decide_reconciliation(item)
        self.assertEqual(decision["disposition"], "OBSERVE_WAIT")
        self.assertIsNone(decision["action"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
