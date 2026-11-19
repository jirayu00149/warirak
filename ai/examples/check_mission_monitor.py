"""Canonical synthetic monitor cases; no training, physical motion or collision-rate estimate."""
import json
import sys
from pathlib import Path
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from warirak_ai.mission_monitor import MissionMonitor

T=1793192400000
def packet(t,i,move=False,speed=None,ack=True):
    return dict(command=dict(schema='warirak.shadow-command.v2',environment='warirak-visual-history-v2',source='shadow_only',control_enabled=False,sequence=i,issued_at_ms=t,valid_until_ms=t+400,action='FORWARD' if move else'STOP',left=.18 if move else 0,right=.18 if move else 0),sensors=dict(timestamp_unix_ms=t,armed=True,manual_override=False,battery_percent=80,clearance_m=[1,1,1]),motion=None if speed is None else dict(schema='warirak.motion-estimate.v1',source='simulation',method='simulation_truth',calibrated=True,frame='pool_fixed',units='m/s',timestamp_unix_ms=t,vx_mps=speed,vy_mps=0,confidence=.95,speed_std_mps=.002),actuator_feedback=dict(schema='warirak.actuator-feedback.v1',source='simulation',units='normalized',timestamp_unix_ms=t,applied_sequence=i,left=.18 if move else 0,right=.18 if move else 0) if ack else None,now_ms=t)

def run():
    cases=[]
    for name,expected,speed,move,count,ack in [('stop_unknown','MOTION_UNKNOWN',None,False,5,True),('stop_observed_stationary','STOPPED_OBSERVED',0,False,5,True),('motion_after_stop','HOLD_REQUIRED',.08,False,5,True),('applied_thrust_without_motion','RECOVERY_REQUIRED',0,True,12,True),('missing_actuator_ack','MANUAL_ASSIST_REQUIRED',0,True,5,False)]:
        monitor=MissionMonitor(input_source='simulation');trace=[]
        for i in range(count):trace.append(monitor.update(**packet(T+i*200,i,move,speed,ack)))
        assert trace[-1]['mode']==expected,name
        assert all(r['control_enabled'] is False and r['hold_controller_available'] is False for r in trace)
        cases.append(dict(name=name,expected=expected,actual=trace[-1]['mode'],trace=trace))
    return dict(schema='warirak.mission-monitor-canonical-cases.v1',input_source='simulation',cases=cases,all_passed=True,training_started=False,physical_motor_transport=False,collision_rate_measured=False,station_holding_implemented=False)

if __name__=='__main__':print(json.dumps(run(),ensure_ascii=False,indent=2))
