import unittest
from warirak_ai.shadow_control import ShadowSupervisor,ShadowController,SCHEMA,ENVIRONMENT

class ShadowControlTests(unittest.TestCase):
    def setUp(self):
        self.now=1800000000000;self.supervisor=ShadowSupervisor()
        self.sensors=dict(timestamp_unix_ms=self.now,battery_percent=80,clearance_m=[1,1,1],armed=True,manual_override=False)
        self.proposal=dict(schema='warirak.visual-pilot.v1',source='shadow_only',generated_at_ms=self.now,control_enabled=False,left=.18,right=.18,reason='approach_proposal')
    def test_no_new_commands_means_explicit_stop_at_deadline(self):
        out=self.supervisor.submit(self.proposal,self.sensors,self.now);self.assertEqual(out['action'],'FORWARD');self.assertFalse(out['control_enabled'])
        self.assertEqual(self.supervisor.tick(self.now+399)['action'],'FORWARD');self.assertEqual(self.supervisor.tick(self.now+400)['action'],'STOP')
        self.assertEqual(self.supervisor.tick(self.now+501)['reason'],'sensor_watchdog')
    def test_supervisor_independently_blocks_clearance_and_manual_faults(self):
        for sensors in [{**self.sensors,'clearance_m':[1,.4,1]},{**self.sensors,'manual_override':True},{**self.sensors,'battery_percent':24},{**self.sensors,'fault':'ultrasonic_disconnected'}]:
            self.assertEqual(ShadowSupervisor().submit(self.proposal,sensors,self.now)['action'],'STOP')
        self.supervisor.submit(self.proposal,self.sensors,self.now)
        self.assertEqual(self.supervisor.tick(self.now+10,{**self.sensors,'clearance_m':[1,.4,1]})['action'],'STOP')
    def test_replayed_future_legacy_and_out_of_range_proposals_cannot_move(self):
        self.supervisor.submit(self.proposal,self.sensors,self.now)
        self.assertEqual(self.supervisor.submit(self.proposal,self.sensors,self.now+10)['action'],'STOP')
        for change in [dict(generated_at_ms=self.now+1),dict(generated_at_ms=self.now-401),dict(control_enabled=True),dict(left=float('nan')),dict(right=.9),dict(schema='warirak.navigation-proposal.v1')]:
            self.assertEqual(ShadowSupervisor().submit({**self.proposal,**change},self.sensors,self.now)['action'],'STOP')
    def test_clearing_an_obstacle_cannot_resurrect_an_old_command(self):
        self.supervisor.submit(self.proposal,self.sensors,self.now)
        self.assertEqual(self.supervisor.tick(self.now+10,{**self.sensors,'clearance_m':[1,.4,1]})['action'],'STOP')
        self.assertEqual(self.supervisor.tick(self.now+20,self.sensors)['action'],'STOP')
        fresh={**self.proposal,'generated_at_ms':self.now+30}
        self.assertEqual(self.supervisor.submit(fresh,self.sensors,self.now+30)['action'],'FORWARD')
    def test_history_is_bounded_distinct_and_does_not_claim_a_trained_memory_policy(self):
        controller=ShadowController(history_size=3)
        for i in range(10):
            t=self.now+i*100;frame=dict(schema='warirak.detection.v1',source='detector',frame_id=i,captured_at_ms=t,image_size=[640,480],detections=[dict(class_id=0,confidence=.9,xyxy=[300,200,340,260])]);command=controller.step(frame,{**self.sensors,'timestamp_unix_ms':t},t)
        self.assertEqual(command['schema'],SCHEMA);self.assertEqual(command['environment'],ENVIRONMENT);snapshot=controller.snapshot();self.assertEqual(len(snapshot['records']),3);self.assertFalse(snapshot['trained_temporal_policy']);snapshot['records'][0]['command']['left']=99;self.assertNotEqual(controller.snapshot()['records'][0]['command']['left'],99)
    def test_long_gap_does_not_reuse_old_target_confirmation(self):
        controller=ShadowController()
        for i,t in enumerate([self.now,self.now+100,self.now+200,self.now+3000]):
            frame=dict(schema='warirak.detection.v1',source='detector',frame_id=i,captured_at_ms=t,image_size=[640,480],detections=[dict(class_id=0,confidence=.9,xyxy=[300,200,340,260])]);command=controller.step(frame,{**self.sensors,'timestamp_unix_ms':t},t)
        self.assertEqual(command['action'],'STOP');self.assertEqual(command['reason'],'confirming_target')

if __name__=='__main__':unittest.main()
