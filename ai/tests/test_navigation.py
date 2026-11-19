import unittest,time
from warirak_ai.navigation import proposal
class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.policy={'q_values':[0.0]*2040};self.now=time.time()*1000
        self.obs=dict(timestamp_unix_ms=self.now,battery_percent=80,clearance_m=[1,1,1],armed=True,manual_override=False,target_visible=True,target_bearing_rad=0,target_distance_m=2)
    def test_shadow_proposals_never_enable_motors(self):
        result=proposal(self.policy,self.obs,self.now);self.assertEqual(result['reason'],'shadow_proposal');self.assertFalse(result['control_enabled']);self.assertLessEqual(abs(result['left']),.3);self.assertLessEqual(abs(result['right']),.3)
    def test_missing_stale_future_and_fault_observations_stop(self):
        cases=[None,{**self.obs,'timestamp_unix_ms':self.now-501},{**self.obs,'timestamp_unix_ms':self.now+101},{**self.obs,'armed':False},{**self.obs,'manual_override':True},{**self.obs,'battery_percent':20},{**self.obs,'clearance_m':[1,.2,1]},{**self.obs,'target_distance_m':None},{**self.obs,'target_bearing_rad':float('nan')}]
        for observation in cases:
            result=proposal(self.policy,observation,self.now);self.assertEqual((result['left'],result['right']),(0,0));self.assertFalse(result['control_enabled'])
    def test_unseen_target_has_a_search_state(self):
        result=proposal(self.policy,{**self.obs,'target_visible':False,'target_distance_m':None,'target_bearing_rad':None},self.now);self.assertEqual(result['state'],400)
if __name__=='__main__':unittest.main()
