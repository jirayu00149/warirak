import unittest,subprocess,sys,os,json
from pathlib import Path
from warirak_ai.mission_monitor import MissionMonitor,MonitorLimits

T=1800000000000
def sensors(t):return dict(timestamp_unix_ms=t,armed=True,manual_override=False,battery_percent=80,clearance_m=[1,1,1])
def command(t,seq,move=False):return dict(schema='warirak.shadow-command.v2',environment='warirak-visual-history-v2',source='shadow_only',control_enabled=False,sequence=seq,issued_at_ms=t,valid_until_ms=t+400,action='FORWARD' if move else'STOP',left=.18 if move else 0,right=.18 if move else 0)
def motion(t,speed=0):return dict(schema='warirak.motion-estimate.v1',source='simulation',method='simulation_truth',calibrated=True,frame='pool_fixed',units='m/s',timestamp_unix_ms=t,vx_mps=speed,vy_mps=0,confidence=.95,speed_std_mps=.002)
def feedback(t,seq,move=False):return dict(schema='warirak.actuator-feedback.v1',source='simulation',units='normalized',timestamp_unix_ms=t,applied_sequence=seq,left=.18 if move else 0,right=.18 if move else 0)

class MissionMonitorTests(unittest.TestCase):
    def test_stop_without_measured_motion_is_never_stationary_confirmation(self):
        m=MissionMonitor()
        for i in range(10):
            t=T+i*200;r=m.update(command(t,i),sensors(t),actuator_feedback=feedback(t,i),now_ms=t)
            self.assertEqual(r['mode'],'MOTION_UNKNOWN');self.assertIsNone(r['observed_speed_mps']);self.assertFalse(r['station_keeping_verified'])
    def test_sustained_measured_motion_after_stop_requests_hold_without_actuation(self):
        m=MissionMonitor()
        for i in range(4):
            t=T+i*200;r=m.update(command(t,i),sensors(t),motion(t,.08),feedback(t,i),t)
        self.assertEqual(r['mode'],'HOLD_REQUIRED');self.assertTrue(r['zero_autonomous_thrust_requested']);self.assertFalse(r['control_enabled']);self.assertFalse(r['hold_controller_available'])
        r=m.update(command(T+800,4),sensors(T+800),motion(T+800,0),feedback(T+800,4),T+800);self.assertTrue(r['operator_reset_required']);self.assertFalse(r['proposal_allowed'])
    def test_stationarity_requires_distinct_fresh_consistent_measurements(self):
        m=MissionMonitor()
        for i in range(4):
            t=T+i*200;r=m.update(command(t,i),sensors(t),motion(t),feedback(t,i),t)
        self.assertEqual(r['mode'],'STOPPED_OBSERVED');self.assertFalse(r['station_keeping_verified'])
        m=MissionMonitor()
        for i in range(4):
            t=T+i*100;r=m.update(command(t,i),sensors(t),motion(T),feedback(t,i),t)
        self.assertNotEqual(r['mode'],'STOPPED_OBSERVED')
    def test_stall_requires_applied_feedback_and_actual_low_motion(self):
        m=MissionMonitor()
        for i in range(11):
            t=T+i*200;r=m.update(command(t,i,True),sensors(t),motion(t),feedback(t,i,True),t)
        self.assertEqual(r['mode'],'RECOVERY_REQUIRED');self.assertFalse(r['recovery_controller_available']);self.assertFalse(r['proposal_allowed'])
        m=MissionMonitor()
        for i in range(4):
            t=T+i*200;r=m.update(command(t,i,True),sensors(t),motion(t),now_ms=t)
        self.assertNotEqual(r['mode'],'RECOVERY_REQUIRED');self.assertEqual(r['latched_reason'],'actuator_ack_missing_or_inconsistent')
    def test_command_derived_stale_uncertain_or_wrong_units_are_not_velocity_evidence(self):
        changes=[dict(method='motor_command'),dict(calibrated=False),dict(units='pixels/s'),dict(frame='boat_body'),dict(confidence=.2),dict(timestamp_unix_ms=T-501),dict(speed_std_mps=.1),dict(source='measured')]
        for change in changes:
            r=MissionMonitor().update(command(T,0),sensors(T),{**motion(T),**change},feedback(T,0),T);self.assertEqual(r['mode'],'MOTION_UNKNOWN');self.assertIsNone(r['observed_speed_mps'])
    def test_manual_override_and_disarm_take_priority_without_automatic_latch_clear(self):
        m=MissionMonitor();m.update(command(T,0),sensors(T),motion(T,.08),feedback(T,0),T,hold_requested=True)
        r=m.update(command(T+100,1,True),{**sensors(T+100),'manual_override':True},motion(T+100,.1),feedback(T+100,1,True),T+100);self.assertEqual(r['mode'],'MANUAL_OVERRIDE');self.assertTrue(r['operator_reset_required']);self.assertFalse(r['proposal_allowed'])
        with self.assertRaises(ValueError):m.reset(sensors(T+200),T+200)
        m.reset({**sensors(T+200),'armed':False},T+200);self.assertIsNone(m.latched)
    def test_explicit_hold_never_silently_runs_an_unimplemented_hold_controller(self):
        r=MissionMonitor().update(command(T,0),sensors(T),motion(T),feedback(T,0),T,hold_requested=True);self.assertEqual(r['mode'],'HOLD_REQUIRED');self.assertFalse(r['hold_controller_available']);self.assertFalse(r['proposal_allowed'])
    def test_source_boundaries_prevent_simulation_feedback_being_treated_as_recorded(self):
        r=MissionMonitor(input_source='recorded').update(command(T,0),sensors(T),motion(T),feedback(T,0),T);self.assertEqual(r['mode'],'WAIT_STOP_ACK')
    def test_sensor_obstacle_battery_and_clock_faults_do_not_allow_proposals(self):
        for change in [dict(timestamp_unix_ms=T-501),dict(clearance_m=[1,.2,1]),dict(battery_percent=20)]:
            r=MissionMonitor().update(command(T,0,True),{**sensors(T),**change},motion(T,.1),feedback(T,0,True),T);self.assertEqual(r['mode'],'FAULT_STOP');self.assertFalse(r['proposal_allowed'])
        m=MissionMonitor();m.update(command(T,0),sensors(T),motion(T),feedback(T,0),T);self.assertEqual(m.update(command(T-1,1),sensors(T-1),motion(T-1),feedback(T-1,1),T-1)['reason'],'receiver_clock_regression')
    def test_normal_tracking_uses_real_estimates_not_commanded_speed(self):
        r=MissionMonitor().update(command(T,0,True),sensors(T),motion(T,.07),feedback(T,0,True),T);self.assertEqual(r['mode'],'TRACKING');self.assertEqual(r['observed_speed_mps'],.07);self.assertFalse(r['control_enabled'])
    def test_interrupted_evidence_and_out_of_order_motion_do_not_confirm_stop(self):
        m=MissionMonitor()
        for i in range(3):
            t=T+i*200;m.update(command(t,i),sensors(t),motion(t),feedback(t,i),t)
        t=T+600;r=m.update(command(t,3),sensors(t),motion(T+300),feedback(t,3),t);self.assertEqual(r['mode'],'MOTION_UNKNOWN')
        t=T+800;r=m.update(command(t,4),sensors(t),motion(t),feedback(t,4),t);self.assertNotEqual(r['mode'],'STOPPED_OBSERVED')
    def test_uncertainty_band_cannot_be_counted_as_stationary(self):
        m=MissionMonitor()
        for i in range(5):
            t=T+i*200;r=m.update(command(t,i),sensors(t),{**motion(t,.02),'speed_std_mps':.01},feedback(t,i),t)
        self.assertEqual(r['motion_state'],'ambiguous');self.assertNotEqual(r['mode'],'STOPPED_OBSERVED')
    def test_replayed_conflicting_commands_and_unrelated_feedback_are_not_accepted(self):
        m=MissionMonitor();m.update(command(T,2),sensors(T),motion(T),feedback(T,2),T)
        r=m.update(command(T+100,1),sensors(T+100),motion(T+100),feedback(T+100,1),T+100);self.assertEqual(r['mode'],'FAULT_STOP')
        r=MissionMonitor().update(command(T,0),sensors(T),motion(T),{**feedback(T,0),'applied_sequence':1},T);self.assertEqual(r['mode'],'WAIT_STOP_ACK')
        r=MissionMonitor().update({**command(T,0),'environment':'other'},sensors(T),motion(T),feedback(T,0),T);self.assertEqual(r['mode'],'WAIT_COMMAND')
    def test_latched_hold_retains_its_mode_and_reset_cannot_use_a_regressing_clock(self):
        m=MissionMonitor();r=m.update(command(T,0),sensors(T),motion(T),feedback(T,0),T,hold_requested=True)
        r=m.update(command(T+100,1),sensors(T+100),motion(T+100),feedback(T+100,1),T+100);self.assertEqual(r['mode'],'HOLD_REQUIRED')
        with self.assertRaises(ValueError):m.reset({**sensors(T),'armed':False},T)
    def test_action_labels_cannot_hide_reverse_or_wrong_direction_values(self):
        for change in [dict(action='STOP'),dict(left=-.18,right=-.18),dict(action='TURN_RIGHT',left=.1,right=.2)]:
            r=MissionMonitor().update({**command(T,0,True),**change},sensors(T),motion(T,.1),feedback(T,0,True),T);self.assertEqual(r['mode'],'FAULT_STOP');self.assertFalse(r['proposal_allowed'])
    def test_documented_example_runs_without_a_preconfigured_pythonpath(self):
        ai=Path(__file__).resolve().parents[1];env=dict(os.environ);env.pop('PYTHONPATH',None)
        r=subprocess.run([sys.executable,'examples/check_mission_monitor.py'],cwd=ai,env=env,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr);report=json.loads(r.stdout);self.assertTrue(report['all_passed']);self.assertFalse(report['station_holding_implemented'])

if __name__=='__main__':unittest.main()
