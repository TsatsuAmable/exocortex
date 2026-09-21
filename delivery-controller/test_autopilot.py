import unittest
from unittest.mock import patch
import autopilot
class T(unittest.TestCase):
 def test_failed_executed_check_is_code_failure(self):
  pr={'statusCheckRollup':[{'name':'unit','conclusion':'FAILURE','detailsUrl':'https://github/x/actions/runs/1/job/2'}]}
  cp=type('CP',(),{'returncode':0,'stdout':'{"steps":[{"name":"test"}]}','stderr':''})()
  with patch('autopilot.run',return_value=cp): self.assertEqual(autopilot.classify('o/r',pr)[0],'CODE_FAILURE')
 def test_failed_zero_step_check_is_infra(self):
  pr={'statusCheckRollup':[{'name':'unit','conclusion':'FAILURE','detailsUrl':'https://github/x/actions/runs/1/job/2'}]}
  cp=type('CP',(),{'returncode':0,'stdout':'{"steps":[]}','stderr':''})()
  with patch('autopilot.run',return_value=cp): self.assertEqual(autopilot.classify('o/r',pr)[0],'INFRA_FAILURE')
 def test_green_is_merge_ready(self): self.assertEqual(autopilot.classify('o/r',{'statusCheckRollup':[],'mergeStateStatus':'CLEAN'})[0],'MERGE_READY')
if __name__=='__main__': unittest.main()
