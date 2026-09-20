import unittest
from hermes_attention_gate import Capability, Decision, decide

class AttentionGateTests(unittest.TestCase):
    def test_executes_available_route_instead_of_human_handoff(self):
        d = decide(capabilities=[Capability("machine_run")])
        self.assertEqual((d.decision, d.route), (Decision.ACT, "machine_run"))

    def test_failed_first_route_recovers_via_alternate(self):
        d = decide(capabilities=[
            Capability("remote_commander", healthy=False),
            Capability("local_machine", healthy=True),
        ], attempted_routes=("remote_commander",))
        self.assertEqual((d.decision, d.route), (Decision.ACT, "local_machine"))

    def test_no_route_is_genuine_escalation(self):
        d = decide(capabilities=[Capability("machine_run", authorized=False)])
        self.assertEqual(d.decision, Decision.ESCALATE)

    def test_policy_boundary_escalates_even_with_tool(self):
        d = decide(capabilities=[Capability("machine_run")], human_required=True)
        self.assertEqual(d.decision, Decision.ESCALATE)

    def test_irreversible_choice_escalates(self):
        self.assertEqual(decide(irreversible=True).decision, Decision.ESCALATE)

    def test_physical_or_secret_requirement_escalates(self):
        self.assertEqual(decide(physical_required=True).decision, Decision.ESCALATE)

    def test_values_choice_escalates(self):
        self.assertEqual(decide(values_required=True).decision, Decision.ESCALATE)

if __name__ == "__main__":
    unittest.main()
