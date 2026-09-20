import unittest
from hermes_route_selector import select_route
CAPS=[
 {"name":"machine_run","available":True,"authorized":True,"healthy":True},
 {"name":"remote_commander","available":True,"authorized":True,"healthy":True},
 {"name":"tailscale_fabric","available":True,"authorized":True,"healthy":True},
]
class RouteSelectorTests(unittest.TestCase):
    def test_prefers_local_for_machine(self):
        self.assertEqual(select_route(CAPS)["route"],"machine_run")
    def test_recovers_to_remote_after_local_failure(self):
        d=select_route(CAPS, attempted=("machine_run",))
        self.assertEqual((d["decision"],d["route"]),("RECOVER","remote_commander"))
    def test_recovers_to_fabric_after_two_failures(self):
        d=select_route(CAPS, attempted=("machine_run","remote_commander"))
        self.assertEqual(d["route"],"tailscale_fabric")
    def test_escalates_only_when_routes_exhausted(self):
        d=select_route(CAPS, attempted=("machine_run","remote_commander","tailscale_fabric"))
        self.assertEqual(d["decision"],"ESCALATE")
if __name__=="__main__": unittest.main()
