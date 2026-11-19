import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from warirak_ai.replay import replay,PAIR_SCHEMA,MISSION_SCHEMA

T=1800000000000
def row(i,t=None,move=False,speed=0,ack=True,source='simulation'):
    t=i*200 if t is None else t;stamp=T+t;seq=80+i
    command=dict(schema='warirak.shadow-command.v2',environment='warirak-visual-history-v2',source='shadow_only',control_enabled=False,sequence=seq,issued_at_ms=stamp,valid_until_ms=stamp+400,action='FORWARD' if move else'STOP',left=.18 if move else 0,right=.18 if move else 0)
    motion=dict(schema='warirak.motion-estimate.v1',source='simulation' if source=='simulation' else'measured',method='simulation_truth' if source=='simulation' else'external_tracking',calibrated=True,frame='pool_fixed',units='m/s',timestamp_unix_ms=stamp,vx_mps=speed,vy_mps=0,confidence=.95,speed_std_mps=.002)
    feedback=dict(schema='warirak.actuator-feedback.v1',source='simulation' if source=='simulation' else'controller_feedback',units='normalized',timestamp_unix_ms=stamp,applied_sequence=seq,left=command['left'],right=command['right']) if ack else None
    return dict(schema=PAIR_SCHEMA,source=source,received_at_ms=stamp,detection=dict(schema='warirak.detection.v1',source='detector',frame_id=i,captured_at_ms=stamp,image_size=[640,480],detections=[dict(class_id=0,confidence=.9,xyxy=[300,200,340,260])]),sensors=dict(timestamp_unix_ms=stamp,battery_percent=80,clearance_m=[1,1,1],armed=True,manual_override=False),mission_observation=dict(schema=MISSION_SCHEMA,observed_command=command,motion=motion,actuator_feedback=feedback))

def observations(result):return [r for r in result['mission'] if r['event']=='observation']

class MissionReplayTests(unittest.TestCase):
    def test_opt_in_monitor_does_not_change_existing_shadow_commands_or_report(self):
        rows=[row(i,speed=.08) for i in range(5)];before=copy.deepcopy(rows)
        legacy=replay(rows);audited=replay(rows,mission_monitor=True)
        report=copy.deepcopy(audited['report']);report.pop('mission_monitor')
        self.assertEqual(legacy,dict(report=report,commands=audited['commands'],history=audited['history']))
        self.assertEqual(rows,before);self.assertNotIn('mission',legacy)
        self.assertTrue(any(x['command']['action']=='FORWARD' for x in audited['commands']))
        self.assertEqual(observations(audited)[-1]['assessment']['mode'],'HOLD_REQUIRED')
        self.assertFalse(audited['report']['mission_monitor']['replay_commands_modified'])
    def test_ack_sequence_is_compared_only_to_explicit_original_log_command(self):
        r=replay([row(0)],mission_monitor=True);m=r['mission'][0]
        self.assertEqual(m['observed_command']['sequence'],80)
        self.assertNotEqual(r['commands'][0]['command']['sequence'],80)
        self.assertEqual(m['assessment']['mode'],'STOPPING_OBSERVED');self.assertTrue(m['assessment']['actuator_feedback_valid'])
        p=row(0);p['mission_observation'].pop('observed_command')
        self.assertEqual(replay([p],mission_monitor=True)['mission'][0]['assessment']['mode'],'WAIT_COMMAND')
    def test_stop_with_continued_motion_latches_request_without_hold_controller(self):
        r=replay([row(i,speed=.08) for i in range(5)],mission_monitor=True)
        a=observations(r)[-1]['assessment'];self.assertEqual(a['mode'],'HOLD_REQUIRED');self.assertTrue(a['operator_reset_required'])
        self.assertFalse(a['hold_controller_available']);self.assertFalse(a['control_enabled']);self.assertFalse(a['station_keeping_verified'])
        self.assertFalse(r['report']['mission_monitor']['receiver_stop_at_end_confirmed'])
    def test_recovery_requires_distinct_motion_and_ack_evidence(self):
        r=replay([row(i,move=True) for i in range(12)],mission_monitor=True)
        self.assertEqual(observations(r)[-1]['assessment']['mode'],'RECOVERY_REQUIRED')
        self.assertFalse(observations(r)[-1]['assessment']['recovery_controller_available'])
        self.assertFalse(r['report']['ground_truth_metrics_available'])
    def test_missing_and_command_derived_motion_are_never_replaced_with_speed(self):
        for value in [None,{**row(0)['mission_observation']['motion'],'method':'motor_command'}]:
            rows=[row(i) for i in range(5)]
            for p in rows:p['mission_observation']['motion']=copy.deepcopy(value)
            r=replay(rows,mission_monitor=True)
            self.assertTrue(all(x['assessment']['mode']=='MOTION_UNKNOWN' for x in observations(r)))
            self.assertTrue(all(x['assessment']['observed_speed_mps'] is None for x in observations(r)))
    def test_repeated_motion_does_not_accumulate_fresh_evidence_and_then_goes_stale(self):
        rows=[row(i) for i in range(5)]
        for p in rows[1:]:p['mission_observation'].pop('motion')
        r=replay(rows,mission_monitor=True)
        self.assertNotIn('STOPPED_OBSERVED',[x['assessment']['mode'] for x in r['mission']])
        last=observations(r)[-1];self.assertEqual(last['assessment']['mode'],'MOTION_UNKNOWN')
        self.assertEqual(last['motion']['timestamp_unix_ms'],T)
    def test_recorded_source_requires_measured_motion_and_original_controller_ack(self):
        good=replay([row(i,source='recorded') for i in range(5)],mission_monitor=True)
        self.assertEqual(observations(good)[-1]['assessment']['mode'],'STOPPED_OBSERVED')
        rows=[row(i,source='recorded') for i in range(5)]
        for p in rows:p['mission_observation']['actuator_feedback']['source']='simulation'
        self.assertEqual(observations(replay(rows,mission_monitor=True))[-1]['assessment']['mode'],'MANUAL_ASSIST_REQUIRED')
        p=row(0,source='recorded');p['mission_observation']['motion']['source']='simulation'
        self.assertEqual(replay([p],mission_monitor=True)['mission'][0]['assessment']['mode'],'MOTION_UNKNOWN')
    def test_ambiguous_uncertainty_is_not_stationary_evidence(self):
        rows=[row(i,speed=.02) for i in range(5)]
        for p in rows:p['mission_observation']['motion']['speed_std_mps']=.01
        r=replay(rows,mission_monitor=True)
        self.assertNotIn('STOPPED_OBSERVED',[x['assessment']['mode'] for x in r['mission']])
        self.assertEqual(observations(r)[-1]['assessment']['motion_state'],'ambiguous')
    def test_motion_clock_regression_is_preserved_and_rejected_as_evidence(self):
        rows=[row(i) for i in range(4)];rows[-1]['mission_observation']['motion']['timestamp_unix_ms']=T+300
        last=observations(replay(rows,mission_monitor=True))[-1]
        self.assertEqual(last['motion']['timestamp_unix_ms'],T+300)
        self.assertEqual(last['assessment']['mode'],'MOTION_UNKNOWN')
    def test_gap_watchdog_observes_stale_original_sensors_without_fabricating_stop_ack(self):
        rows=[row(0),row(1,t=1800)];r=replay(rows,mission_monitor=True)
        fault=next(x for x in r['mission'] if x['event']=='watchdog' and x['assessment']['reason']=='sensor_watchdog')
        self.assertEqual(fault['replay_at_ms'],T+550);self.assertEqual(fault['sensors']['timestamp_unix_ms'],T)
        self.assertEqual(fault['actuator_feedback']['timestamp_unix_ms'],T)
        self.assertEqual(observations(r)[-1]['assessment']['mode'],'FAULT_STOP')
    def test_manual_override_clears_cached_proposal_and_requires_new_logged_command(self):
        rows=[row(0,move=True,speed=.08),row(1,t=100),row(2,t=200)]
        rows[1]['sensors']['manual_override']=True
        rows[2]['mission_observation']=dict(schema=MISSION_SCHEMA,motion=rows[2]['mission_observation']['motion'])
        states=observations(replay(rows,mission_monitor=True))
        self.assertEqual(states[0]['assessment']['mode'],'TRACKING');self.assertEqual(states[1]['assessment']['mode'],'MANUAL_OVERRIDE')
        self.assertEqual(states[2]['assessment']['mode'],'WAIT_COMMAND');self.assertIsNone(states[2]['observed_command'])
    def test_latch_only_clears_with_explicit_fresh_disarmed_reset_then_new_data(self):
        rows=[row(i,speed=.08) for i in range(4)];reset=row(4);reset['sensors']['armed']=False
        reset['mission_observation']=dict(schema=MISSION_SCHEMA,operator_reset=True);rows.append(reset)
        empty=row(5);empty['mission_observation']=dict(schema=MISSION_SCHEMA);rows.append(empty)
        states=observations(replay(rows,mission_monitor=True))
        self.assertEqual(states[3]['assessment']['mode'],'HOLD_REQUIRED');self.assertEqual(states[4]['assessment']['mode'],'DISARMED')
        self.assertEqual(states[5]['assessment']['mode'],'WAIT_COMMAND');self.assertIsNone(states[5]['actuator_feedback'])
        reset['sensors']['armed']=True
        with self.assertRaises(ValueError):replay(rows,mission_monitor=True)
    def test_malformed_packets_boolean_flags_and_wrong_sequence_do_not_pass(self):
        for packet in [None,dict(schema='wrong'),dict(schema=MISSION_SCHEMA,hold_requested='false'),dict(schema=MISSION_SCHEMA,operator_reset=1),dict(schema=MISSION_SCHEMA,motion=1),dict(schema=MISSION_SCHEMA,operator_reset=True,motion={})]:
            p=row(0);p['mission_observation']=packet
            with self.assertRaises(ValueError):replay([p],mission_monitor=True)
        p=row(0);p['mission_observation']['actuator_feedback']['applied_sequence']=1
        self.assertEqual(replay([p],mission_monitor=True)['mission'][0]['assessment']['mode'],'WAIT_STOP_ACK')
    def test_explicit_null_removes_cached_telemetry_and_replay_is_deterministic(self):
        rows=[row(0),row(1,t=100)];rows[1]['mission_observation']=dict(schema=MISSION_SCHEMA,motion=None)
        r=replay(rows,mission_monitor=True);self.assertIsNone(observations(r)[-1]['motion'])
        self.assertEqual(observations(r)[-1]['assessment']['mode'],'MOTION_UNKNOWN');self.assertEqual(r,replay(rows,mission_monitor=True))
    def test_cli_writes_separate_trace_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);src=base/'pairs.jsonl';src.write_text(json.dumps(row(0))+'\n',encoding='utf-8');out=base/'result'
            cmd=[sys.executable,'-m','warirak_ai.replay','--input',str(src),'--out',str(out),'--mission-monitor']
            r=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
            first=(out/'mission.jsonl').read_bytes();self.assertIn('mission_monitor',json.loads((out/'report.json').read_text('utf-8')))
            r=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(r.returncode,2);self.assertEqual(first,(out/'mission.jsonl').read_bytes())
            bad=base/'bad.jsonl';bad.write_text(json.dumps({**row(0),'mission_observation':dict(schema='wrong')})+'\n',encoding='utf-8')
            failed=base/'failed';r=subprocess.run([sys.executable,'-m','warirak_ai.replay','--input',str(bad),'--out',str(failed),'--mission-monitor'],capture_output=True,text=True)
            self.assertEqual(r.returncode,2);self.assertFalse(failed.exists())

if __name__=='__main__':unittest.main()
