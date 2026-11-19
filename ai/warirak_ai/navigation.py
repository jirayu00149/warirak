"""Shadow-only Q-table navigation proposals. This module has no motor/serial/network transport."""
import argparse,json,math,time,sys
from pathlib import Path

ENVIRONMENT='warirak-pool-v1'
ACTIONS=((.65,.65),(.25,.65),(.65,.25),(-.3,.3),(.3,-.3))
ACTION_NAMES=('เดินหน้า','เลี้ยวซ้าย','เลี้ยวขวา','หมุนซ้าย','หมุนขวา')
def finite(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
def load_policy(path):
    p=json.loads(Path(path).read_text(encoding='utf-8'))
    if p.get('schema')!='warirak.navigation-policy.v1' or p.get('environment')!=ENVIRONMENT or p.get('source')!='simulation' or p.get('action_names')!=list(ACTION_NAMES) or p.get('control_enabled') is not False or p.get('real_world_validated') is not False:raise ValueError('Unsupported or unsafe policy metadata')
    if p.get('state_count')!=408 or len(p.get('q_values',[]))!=2040 or not all(finite(v) for v in p['q_values']):raise ValueError('Invalid Q-table')
    return p
def proposal(policy,observation,now_ms=None):
    now=time.time()*1000 if now_ms is None else now_ms
    result=dict(schema='warirak.navigation-proposal.v1',source='shadow_only',control_enabled=False,left=0.0,right=0.0,reason='invalid_observation',requires_hardware_calibration=True)
    if not isinstance(observation,dict):return result
    timestamp=observation.get('timestamp_unix_ms');battery=observation.get('battery_percent');clearance=observation.get('clearance_m')
    if not finite(timestamp) or timestamp>now+100 or now-timestamp>500:result['reason']='stale_or_future_observation';return result
    if observation.get('armed') is not True or observation.get('manual_override') is not False:result['reason']='disarmed_or_manual_override';return result
    if not finite(battery) or battery<25 or battery>100:result['reason']='low_or_invalid_battery';return result
    if not isinstance(clearance,list) or len(clearance)!=3 or not all(finite(v) and 0<=v<=20 for v in clearance):return result
    if min(clearance)<.35:result['reason']='obstacle_stop';return result
    visible=observation.get('target_visible')
    if not isinstance(visible,bool):return result
    if visible:
        bearing=observation.get('target_bearing_rad');distance=observation.get('target_distance_m')
        if not finite(bearing) or not -math.pi<=bearing<=math.pi or not finite(distance) or not 0<distance<=4.8 or abs(bearing)>=math.pi*.48:return result
        bearing_bin=min(15,max(0,math.floor((bearing+math.pi)/(math.pi*2)*16)));range_bin=0 if distance<.8 else 1 if distance<2 else 2
    else:bearing_bin=16;range_bin=2
    mask=sum(1<<i for i,v in enumerate(clearance) if v<.65);state=(bearing_bin*3+range_bin)*8+mask
    row=policy['q_values'][state*5:state*5+5];action=max(range(5),key=lambda i:row[i]);left,right=ACTIONS[action]
    # Symbolic suggestion only; an independent hardware adapter must implement physical limits and a watchdog.
    scale=min(1,.3/max(abs(left),abs(right)))
    result.update(left=left*scale,right=right*scale,action=action,state=state,reason='shadow_proposal')
    return result
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--policy',required=True);parser.add_argument('--observations',help='JSONL input, or stdin when omitted');args=parser.parse_args()
    policy=load_policy(args.policy);stream=Path(args.observations).open(encoding='utf-8') if args.observations else sys.stdin
    try:
        for line in stream:
            try:observation=json.loads(line)
            except json.JSONDecodeError:observation=None
            print(json.dumps(proposal(policy,observation),ensure_ascii=False),flush=True)
    finally:
        if stream is not sys.stdin:stream.close()
        print(json.dumps(dict(schema='warirak.navigation-proposal.v1',source='shadow_only',control_enabled=False,left=0,right=0,reason='input_ended')),flush=True)
if __name__=='__main__':main()
