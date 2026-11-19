import unittest
from warirak_ai.visual_pilot import VisualPilot
from warirak_ai.infer import detection_event

class VisualPilotTests(unittest.TestCase):
    def setUp(self):
        self.pilot=VisualPilot();self.now=1800000000000
        self.sensors=dict(timestamp_unix_ms=self.now,battery_percent=80,clearance_m=[1,1,1],armed=True,manual_override=False)
    def frame(self,index=1,x=320):return dict(schema='warirak.detection.v1',source='detector',frame_id=index,captured_at_ms=self.now-100+index,image_size=[640,480],detections=[dict(class_id=0,confidence=.9,xyxy=[x-20,200,x+20,260])])
    def test_requires_three_distinct_consistent_frames_and_never_confirms_collection(self):
        for n in [1,2]:self.assertEqual(self.pilot.propose(self.frame(n),self.sensors,self.now)['reason'],'confirming_target')
        out=self.pilot.propose(self.frame(3),self.sensors,self.now);self.assertEqual(out['reason'],'approach_proposal');self.assertGreater(out['left'],0);self.assertEqual(out['left'],out['right']);self.assertFalse(out['control_enabled']);self.assertFalse(out['collection_confirmed']);self.assertFalse(out['conveyor_enabled']);self.assertIsNone(out['target_distance_m'])
    def test_danger_stale_and_repeated_inputs_stop(self):
        cases=[(self.frame(),{**self.sensors,'clearance_m':[1,.2,1]}),(self.frame(),{**self.sensors,'battery_percent':20}),({**self.frame(),'captured_at_ms':self.now-2000},self.sensors),(self.frame(),{**self.sensors,'timestamp_unix_ms':self.now-501}),(self.frame(),{**self.sensors,'manual_override':True}),({**self.frame(),'image_size':None},self.sensors)]
        for frame,sensor in cases:
            out=VisualPilot().propose(frame,sensor,self.now);self.assertEqual((out['left'],out['right']),(0,0))
        self.pilot.propose(self.frame(),self.sensors,self.now);self.assertEqual(self.pilot.propose(self.frame(),self.sensors,self.now)['reason'],'repeated_or_out_of_order_frame')
    def test_target_loss_clears_temporal_confirmation(self):
        for n in [1,2,3]:self.pilot.propose(self.frame(n),self.sensors,self.now)
        out=self.pilot.propose({**self.frame(4),'detections':[]},self.sensors,self.now);self.assertEqual(out['reason'],'target_not_confirmed')
        self.assertEqual(self.pilot.propose(self.frame(5),self.sensors,self.now)['reason'],'confirming_target')
    def test_right_target_requests_right_turn_in_declared_motor_layout(self):
        for n in [1,2,3]:out=self.pilot.propose(self.frame(n,430),self.sensors,self.now)
        self.assertGreater(out['left'],out['right']);self.assertLessEqual(max(abs(out['left']),abs(out['right'])),.25)
    def test_capture_time_is_not_replaced_by_inference_completion(self):
        event=detection_event(1,640,480,[],3000,captured_at_ms=1000);self.assertEqual(event['captured_at_ms'],1000);self.assertGreater(event['inference_completed_at_ms'],1000)

if __name__=='__main__':unittest.main()
