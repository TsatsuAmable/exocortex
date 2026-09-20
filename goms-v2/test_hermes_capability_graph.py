import tempfile, unittest
from hermes_authority import HermesAuthority
from hermes_capability_graph import HermesCapabilityGraph

class CapabilityGraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.auth=HermesAuthority(self.tmp.name)
        self.auth.enter("OPERATE", principal="test", human_authorized=True)

    def tearDown(self): self.tmp.cleanup()

    def test_operate_discovers_authorized_normal_routes(self):
        names={x["name"] for x in HermesCapabilityGraph(self.auth).candidates()}
        self.assertIn("machine_run", names)
        self.assertIn("goms_context", names)
        self.assertNotIn("machine_recovery", names)

    def test_health_probe_removes_broken_route(self):
        graph=HermesCapabilityGraph(self.auth, {"machine_run": lambda: False})
        names={x["name"] for x in graph.candidates()}
        self.assertNotIn("machine_run", names)

    def test_discovery_reports_authority_ceiling(self):
        row={x["name"]:x for x in HermesCapabilityGraph(self.auth).discover()}
        self.assertFalse(row["machine_recovery"]["authorized"])
        self.assertEqual(row["machine_recovery"]["required_mode"], "RECOVERY")

if __name__=="__main__": unittest.main()
