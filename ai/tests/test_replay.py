import unittest,tempfile,subprocess,sys,json
from pathlib import Path
from warirak_ai.replay import replay,PAIR_SCHEMA

T=1800000000000
def pair(index,arrival,capture=None,source='simulation'):
    return dict(schema=PAIR_SCHEMA,source=source,received_at_ms=T+arrival,detection=dict(schema='warirak.detection.v1',source='detector',frame_id=index,captured_at_ms=T+(arrival if capture is None else capture),image_size=[640,480],detections=[dict(class_id=0,confidence=.9,xyxy=[300,200,340,260])]),sensors=dict(timestamp_unix_ms=T+arrival,battery_percent=80,clearance_m=[1,1,1],armed=True,manual_override=False))

class ReplayTests(unittest.TestCase):
    def test_recorded_arrival_gap_runs_watchdog_and_never_retimes_stale_capture(self):
        rows=[pair(0,0),pair(1,100),pair(2,200),pair(3,2200,capture=100)]
        result=replay(rows);trace=result['commands'];motion=[c for c in trace if c['command']['action']=='FORWARD'];self.assertEqual(motion[0]['replay_at_ms'],T+200)
        stopped=next(c for c in trace if c['event']=='watchdog' and c['command']['action']=='STOP');self.assertEqual(stopped['replay_at_ms'],T+600)
        self.assertEqual(result['report']['virtual_nonzero_command_duration_ms'],400)
        self.assertEqual(result['report']['observed_proposal_reasons']['stale_or_invalid_frame'],1)
        self.assertEqual(result['report']['frame_age_at_arrival_ms']['max'],2100)
        self.assertEqual(rows[-1]['detection']['captured_at_ms'],T+100)
    def test_ends_with_stop_and_labels_simulation_without_inventing_accuracy(self):
        r=replay([pair(i,i*100) for i in range(5)])
        self.assertEqual(r['commands'][-1]['command']['reason'],'replay_ended');self.assertEqual(r['commands'][-1]['command']['action'],'STOP')
        self.assertEqual(r['report']['input_source'],'simulation');self.assertFalse(r['report']['ground_truth_metrics_available']);self.assertFalse(r['report']['real_world_validated']);self.assertFalse(r['report']['trained_temporal_policy']);self.assertTrue(all(c['command']['control_enabled'] is False for c in r['commands']))
    def test_mixed_sources_and_reordered_clocks_are_rejected(self):
        for rows in [[pair(0,100),pair(1,0)],[pair(0,0),pair(1,100,source='recorded')],[{**pair(0,0),'received_at_ms':float('nan')}],[{**pair(0,0),'source':'hardware'}]]:
            with self.assertRaises(ValueError):replay(rows)
    def test_empty_oversized_and_overlong_logs_are_rejected(self):
        for rows,options in [([],{}),([pair(0,0),pair(1,10)],dict(max_records=1)),([pair(0,0),pair(1,10000)],dict(max_duration_ms=100))]:
            with self.assertRaises(ValueError):replay(rows,**options)
    def test_virtual_replay_is_deterministic_and_history_bounded(self):
        rows=[pair(i,i*100,source='recorded') for i in range(20)]
        self.assertEqual(replay(rows),replay(rows));self.assertEqual(len(replay(rows)['history']['records']),8)
    def test_missing_sensors_stop_instead_of_being_fabricated(self):
        row=pair(0,0);row.pop('sensors');r=replay([row]);self.assertEqual(r['commands'][0]['command']['action'],'STOP');self.assertEqual(r['report']['sensor_age_at_arrival_ms']['samples'],0)
    def test_cli_preserves_existing_evidence_and_rejects_bad_logs_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder);source=directory/'pairs.jsonl';out=directory/'result';source.write_text(json.dumps(pair(0,0))+'\n',encoding='utf-8')
            command=[sys.executable,'-m','warirak_ai.replay','--input',str(source),'--out',str(out)]
            first=subprocess.run(command,capture_output=True,text=True);self.assertEqual(first.returncode,0,first.stderr)
            original=(out/'report.json').read_bytes();again=subprocess.run(command,capture_output=True,text=True);self.assertEqual(again.returncode,2);self.assertEqual((out/'report.json').read_bytes(),original)
            bad=directory/'bad.jsonl';bad.write_text('{invalid',encoding='utf-8');failed=directory/'failed'
            last=subprocess.run([sys.executable,'-m','warirak_ai.replay','--input',str(bad),'--out',str(failed)],capture_output=True,text=True);self.assertEqual(last.returncode,2);self.assertFalse(failed.exists())

if __name__=='__main__':unittest.main()
