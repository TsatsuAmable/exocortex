import unittest
from unittest.mock import patch
import autopilot

class FakeService:
    def __init__(self):
        self.calls=[]
    def get(self, intent_id):
        return {"id":intent_id,"status":"RESOLVED","provenance":{"submission":{"human_attested":True,"resolved_by":"human:user"}}}
    def submit_intent(self, **kwargs):
        self.calls.append(kwargs)
        return {"intent_id":"intent_test"}

class T(unittest.TestCase):
    def test_failed_executed_check_is_code_failure(self):
        pr={'statusCheckRollup':[{'name':'unit','conclusion':'FAILURE','detailsUrl':'https://github/x/actions/runs/1/job/2'}]}
        cp=type('CP',(),{'returncode':0,'stdout':'{"steps":[{"name":"test"}]}','stderr':''})()
        with patch('autopilot.run',return_value=cp):
            self.assertEqual(autopilot.classify('o/r',pr)[0],'CODE_FAILURE')

    def test_failed_zero_step_check_is_infra(self):
        pr={'statusCheckRollup':[{'name':'unit','conclusion':'FAILURE','detailsUrl':'https://github/x/actions/runs/1/job/2'}]}
        cp=type('CP',(),{'returncode':0,'stdout':'{"steps":[]}','stderr':''})()
        with patch('autopilot.run',return_value=cp):
            self.assertEqual(autopilot.classify('o/r',pr)[0],'INFRA_FAILURE')

    def test_green_is_merge_ready(self):
        self.assertEqual(autopilot.classify('o/r',{'statusCheckRollup':[],'mergeStateStatus':'CLEAN'})[0],'MERGE_READY')

    def test_remediation_creates_approved_durable_intent(self):
        svc=FakeService()
        pr={'number':811,'headRefOid':'abc123','url':'https://github.com/o/r/pull/811'}
        policy={
            'repair_auto_dispatch':True,
            'standing_authority_ref':'intent_authority',
            'standing_authority_resolved_by':'human:user',
        }
        with patch('autopilot._intent_service',return_value=svc):
            action=autopilot.enqueue_remediation('o/r',pr,'CODE_FAILURE',['approval-gate'],policy)
        self.assertEqual(action,'intent:intent_test')
        call=svc.calls[0]
        self.assertEqual(call['execution_policy'],'AUTO_AFTER_APPROVAL')
        self.assertTrue(call['human_attested'])
        self.assertEqual(call['resolved_by'],'human:user')
        self.assertEqual(call['provenance']['standing_authority_ref'],'intent_authority')
        self.assertIn('approval-gate',call['summary'])

if __name__=='__main__':
    unittest.main()
