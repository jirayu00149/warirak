"""Check the shipped synthetic replay fixture; no physical or trained-policy performance claim."""
import json,sys
from pathlib import Path
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from warirak_ai.replay import replay,read_jsonl

def run():
    path=Path(__file__).with_name('paired-mission-simulation.jsonl')
    result=replay(read_jsonl(path),mission_monitor=True)
    rows=[r for r in result['mission'] if r['event']=='observation']
    expected={3:'HOLD_REQUIRED',4:'MANUAL_OVERRIDE',5:'HOLD_REQUIRED',6:'DISARMED',10:'STOPPED_OBSERVED',11:'FAULT_STOP'}
    for index,mode in expected.items():assert rows[index]['assessment']['mode']==mode,(index,mode,rows[index]['assessment'])
    assert all(r['assessment']['control_enabled'] is False for r in result['mission'])
    assert result['report']['mission_monitor']['replay_commands_modified'] is False
    assert result['report']['mission_monitor']['receiver_stop_at_end_confirmed'] is False
    return dict(schema='warirak.replay-mission-example-check.v1',all_passed=True,input_source='simulation',records=len(rows),observed_modes=[r['assessment']['mode'] for r in rows],mission_summary=result['report']['mission_monitor'],station_holding_implemented=False,physical_motor_transport=False,field_validated=False,collision_rate_measured=False)

if __name__=='__main__':print(json.dumps(run(),indent=2))
