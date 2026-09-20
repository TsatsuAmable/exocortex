import unittest
from hermes_execution_supervisor import HermesExecutionSupervisor

CAPS=[
 {"name":"machine_run","available":True,"authorized":True,"healthy":True},
 {"name":"remote_commander","available":True,"authorized":True,"healthy":True},
 {"name":"tailscale_fabric","available":True,"authorized":True,"healthy":True},
]
class SupervisorTests(unittest.TestCase):
    def test_first_route_success(self):
        s=HermesExecutionSupervisor(lambda:CAPS,{"machine_run":lambda t:{"ok":True,"v":t}})
        r=s.execute("x")
        self.assertTrue(r["ok"]); self.assertEqual(r["route"],"machine_run")

    def test_failure_fails_over_and_verifies(self):
        s=HermesExecutionSupervisor(lambda:CAPS,{
          "machine_run":lambda t:{"ok":False},
          "remote_commander":lambda t:{"ok":True,"verified":True}})
        r=s.execute("x",verifier=lambda x:x.get("verified",False))
        self.assertTrue(r["ok"]); self.assertEqual(r["route"],"remote_commander")
        self.assertEqual(r["decision"],"RECOVER")

    def test_exception_does_not_escape_when_alternate_exists(self):
        def boom(_): raise RuntimeError("broken")
        s=HermesExecutionSupervisor(lambda:CAPS,{"machine_run":boom,"remote_commander":lambda t:{"ok":True}})
        self.assertEqual(s.execute("x")["route"],"remote_commander")

    def test_escalates_after_exhaustion(self):
        s=HermesExecutionSupervisor(lambda:CAPS,{n:(lambda t:{"ok":False}) for n in ("machine_run","remote_commander","tailscale_fabric")})
        r=s.execute("x")
        self.assertFalse(r["ok"]); self.assertEqual(r["decision"],"ESCALATE")
        self.assertEqual(len(r["attempts"]),3)

if __name__=="__main__": unittest.main()
