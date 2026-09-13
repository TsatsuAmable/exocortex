#!/usr/bin/env python3
import tempfile, unittest
from goms_store import GomsStore
from commitment_gate import CommitmentGate

class CommitmentGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="gate-test-")
        self.store=GomsStore(self.tmp.name)
        self.gate=CommitmentGate(self.store)

    def tearDown(self): self.tmp.cleanup()

    def test_low_evidence_stays_machine_side(self):
        c=self.gate.add("Speculative idea", project="test", meaningfulness=.9, leverage=.9,
                        evidence=.1, reversibility=.9, human_attention_minutes=5)
        self.assertEqual(c["status"],"EXPLORE")

    def test_evidence_qualified_low_risk_can_run_autonomously(self):
        c=self.gate.add("Automatable research note", project="test", meaningfulness=.9, leverage=.8,
                        evidence=.8, reversibility=.9, human_attention_minutes=0,
                        opportunity_cost=.1, risk_class="low")
        self.assertEqual(c["status"],"AUTONOMOUS")

    def test_irreducible_judgment_escalates_only_when_worth_it(self):
        c=self.gate.add("Change constitutional objective", project="test", meaningfulness=1,
                        leverage=.9, evidence=.8, reversibility=.8, human_attention_minutes=5,
                        human_judgment_required=True)
        self.assertEqual(c["status"],"HUMAN_ATTENTION")

    def test_capacity_yield_uses_observed_outcomes(self):
        c=self.gate.add("Produce artefact", project="test", meaningfulness=1, leverage=1,
                        evidence=1, reversibility=1)
        self.gate.record_outcome(c["id"], True, "paper.md", human_attention_minutes=4)
        m=self.gate.metrics()
        self.assertEqual(m["valuable_durable_outcomes"],1)
        self.assertEqual(m["capacity_yield_per_human_minute"],.25)

if __name__=="__main__": unittest.main(verbosity=2)
