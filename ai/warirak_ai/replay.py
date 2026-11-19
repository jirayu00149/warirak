"""Replay paired camera/sensor messages on their recorded arrival clock, without motors or sleeps."""
import argparse,json,math
from collections import Counter
from copy import deepcopy
from itertools import islice
from pathlib import Path
from .shadow_control import ShadowController
from .visual_pilot import finite
from .mission_monitor import MissionMonitor

PAIR_SCHEMA='warirak.observation-pair.v1'
SOURCES={'recorded','simulation'}
MISSION_SCHEMA='warirak.mission-observation.v1'

def _validate_mission_packet(row,index):
    if 'mission_observation' not in row:return
    packet=row['mission_observation']
    if not isinstance(packet,dict) or packet.get('schema')!=MISSION_SCHEMA:raise ValueError(f'Record{index}: explicit mission-observation schema required')
    for key in ['operator_reset','hold_requested']:
        if key in packet and type(packet[key]) is not bool:raise ValueError(f'Record{index}: {key} must be boolean')
    for key in ['observed_command','motion','actuator_feedback']:
        if key in packet and packet[key] is not None and not isinstance(packet[key],dict):raise ValueError(f'Record{index}: {key} must be an object or null')
    if packet.get('operator_reset') and (packet.get('hold_requested') or any(packet.get(k) is not None for k in ['observed_command','motion','actuator_feedback'])):raise ValueError(f'Record{index}: reset must be separate from new command/motion/feedback')

class _MissionReplay:
    """Observe original logged proposals/telemetry; never associate ACKs with replay-generated IDs."""
    def __init__(self,source):
        self.monitor=MissionMonitor(input_source=source);self.source=source;self.sensors=None
        self.latest={key:None for key in ['observed_command','motion','actuator_feedback']}
        self.hold_requested=False;self.trace=[];self.last_assessment=None;self.modes=Counter();self.watchdog_updates=0;self.packets=0;self.resets=0
    def observation(self,row,index,now):
        self.sensors=deepcopy(row.get('sensors'));packet=row.get('mission_observation')
        if packet is not None:
            self.packets+=1
            if packet.get('operator_reset'):
                self.monitor.reset(self.sensors,now);self.latest={key:None for key in self.latest};self.hold_requested=False;self.resets+=1
            else:
                for key in self.latest:
                    if key in packet:self.latest[key]=deepcopy(packet[key])
                if 'hold_requested' in packet:self.hold_requested=packet['hold_requested']
        result=self.update(now,'observation',index,always=True);self.modes[result['mode']]+=1
        return result
    def update(self,now,event,index=None,always=False):
        if event=='watchdog':self.watchdog_updates+=1
        state=self.monitor.update(self.latest['observed_command'],self.sensors,motion=self.latest['motion'],actuator_feedback=self.latest['actuator_feedback'],now_ms=now,hold_requested=self.hold_requested)
        if always or state!=self.last_assessment:
            self.trace.append(dict(schema='warirak.replay-mission.v1',source='shadow_only',input_source=self.source,event=event,record_index=index,replay_at_ms=now,observed_command_origin='input_log_only',sensors=deepcopy(self.sensors),hold_requested=self.hold_requested,**deepcopy(self.latest),assessment=deepcopy(state)))
        self.last_assessment=state
        # A previous autonomous proposal/ACK must not reappear after manual/disarm clears.
        if state['mode'] in ['MANUAL_OVERRIDE','DISARMED']:
            self.latest['observed_command']=None;self.latest['actuator_feedback']=None;self.hold_requested=False
        return state
    def report(self):
        return dict(schema='warirak.replay-mission-report.v1',advisory_only=True,command_origin='input_log_only_not_replay_generated',configuration=self.monitor.configuration(),input_packets=self.packets,operator_resets=self.resets,watchdog_updates=self.watchdog_updates,emitted_assessments=len(self.trace),observed_modes=dict(self.modes),replay_commands_modified=False,receiver_stop_at_end_confirmed=False,control_enabled=False,limitations=['Missing fields retain their original timestamps until stale; explicit null removes a cached value','Recorded ACKs refer only to the original logged shadow proposal sequence, never regenerated replay command IDs','Advisory assessments do not implement HOLD/RECOVERY or modify shadow proposals','End of log and replay STOP do not establish an applied receiver STOP or physical stationary state'])

def _percentile(values,fraction):
    return sorted(values)[max(0,math.ceil(len(values)*fraction)-1)] if values else None

def replay(records,tick_ms=50,thresholds=None,max_records=100000,max_duration_ms=3600000,mission_monitor=False):
    if type(tick_ms) is not int or not 10<=tick_ms<=100:raise ValueError('Watchdog tick must be10..100ms')
    if type(max_records) is not int or max_records<1:raise ValueError('Invalid record bound')
    if type(mission_monitor) is not bool:raise ValueError('mission_monitor must be boolean')
    rows=list(islice(records,max_records+1))
    if not rows or len(rows)>max_records:raise ValueError('Empty replay or record limit exceeded')
    source=None;previous=None
    for i,row in enumerate(rows,1):
        if not isinstance(row,dict) or row.get('schema')!=PAIR_SCHEMA or row.get('source') not in SOURCES:raise ValueError(f'Record{i}: explicit observation-pair schema/source required')
        if source is None:source=row['source']
        if row['source']!=source:raise ValueError('Do not mix simulation with recorded observations')
        stamp=row.get('received_at_ms')
        if not finite(stamp) or stamp<=0 or previous is not None and stamp<previous:raise ValueError(f'Record{i}: invalid or regressing arrival clock')
        if previous is not None and stamp-rows[0]['received_at_ms']>max_duration_ms:raise ValueError('Replay duration limit exceeded; split the recording')
        if mission_monitor:_validate_mission_packet(row,i)
        previous=stamp
    controller=ShadowController(thresholds=thresholds);commands=[];reasons=Counter();latencies=[];sensor_ages=[];moving_ms=0.;watchdog_ticks=0
    mission=_MissionReplay(source) if mission_monitor else None
    current=None;clock=rows[0]['received_at_ms'];previous_arrival=None
    def advance(stamp):
        nonlocal clock,moving_ms
        if current and current['action']!='STOP':moving_ms+=max(0,stamp-clock)
        clock=stamp
    def emit(command,event,record_index=None,always=False):
        nonlocal current
        signature=lambda x:(x['action'],x['left'],x['right'],x['reason'])
        changed=current is None or signature(command)!=signature(current)
        current=command
        if changed or always:commands.append(dict(schema='warirak.replay-command.v1',source='shadow_only',input_source=source,event=event,record_index=record_index,replay_at_ms=clock,command=dict(command)))
    for index,row in enumerate(rows):
        arrival=row['received_at_ms']
        if previous_arrival is not None:
            tick=previous_arrival+tick_ms
            while tick<arrival:
                advance(tick);emit(controller.supervisor.tick(tick),'watchdog');watchdog_ticks+=1
                if mission:mission.update(tick,'watchdog')
                tick+=tick_ms
        advance(arrival);detection=row.get('detection');sensors=row.get('sensors')
        command=controller.step(detection,sensors,arrival);emit(command,'observation',index,always=True);reasons[command['reason']]+=1
        if mission:mission.observation(row,index,arrival)
        for data,key,target in [(detection,'captured_at_ms',latencies),(sensors,'timestamp_unix_ms',sensor_ages)]:
            stamp=data.get(key) if isinstance(data,dict) else None
            if finite(stamp) and arrival>=stamp:target.append(arrival-stamp)
        previous_arrival=arrival
    terminal=controller.supervisor.cancel(clock,'replay_ended');emit(terminal,'end_of_input',always=True)
    report=dict(schema='warirak.replay-report.v1',source='shadow_only',input_source=source,clock='recorded_received_at_ms; original capture/sensor timestamps preserved',records=len(rows),started_at_ms=rows[0]['received_at_ms'],ended_at_ms=clock,duration_ms=clock-rows[0]['received_at_ms'],watchdog_tick_ms=tick_ms,watchdog_ticks=watchdog_ticks,emitted_commands=len(commands),observed_proposal_reasons=dict(reasons),virtual_nonzero_command_duration_ms=moving_ms,frame_age_at_arrival_ms=dict(samples=len(latencies),p50=_percentile(latencies,.5),p95=_percentile(latencies,.95),max=max(latencies) if latencies else None),sensor_age_at_arrival_ms=dict(samples=len(sensor_ages),p95=_percentile(sensor_ages,.95)),collection_confirmed=False,control_enabled=False,real_world_validated=False,ground_truth_metrics_available=False,trained_temporal_policy=False,limitations=['Virtual-time command proposals, not physical motor response','No detection accuracy, navigation success or collision rate without separately annotated ground truth','Arrival/capture/sensor clocks must use the same synchronized epoch; no automatic clock correction'])
    history={**controller.snapshot(),'input_source':source}
    result=dict(report=report,commands=commands,history=history)
    if mission:report['mission_monitor']=mission.report();result['mission']=mission.trace
    return result

def read_jsonl(file):
    if file.stat().st_size>64*1024*1024:raise ValueError('Input exceeds64MiB; split the recording')
    with file.open(encoding='utf-8') as stream:
        for line_number,line in enumerate(stream,1):
            if not line.strip():continue
            try:yield json.loads(line)
            except json.JSONDecodeError as e:raise ValueError(f'Invalid JSON at line{line_number}: {e.msg}') from e

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--thresholds',type=Path);parser.add_argument('--tick-ms',type=int,default=50);parser.add_argument('--mission-monitor',action='store_true',help='Audit original logged command/motion/ACK without changing shadow proposals');args=parser.parse_args()
    if args.out.exists():parser.exit(2,'Output exists; choose a new directory to preserve previous replay evidence.\n')
    try:
        thresholds=None
        if args.thresholds:
            from .calibration import load_calibration
            from . import CLASSES
            selected=load_calibration(args.thresholds)['thresholds'];thresholds={i:selected[c] for i,c in enumerate(CLASSES)}
        result=replay(read_jsonl(args.input),tick_ms=args.tick_ms,thresholds=thresholds,mission_monitor=args.mission_monitor)
        args.out.mkdir(parents=True)
        (args.out/'report.json').write_text(json.dumps(result['report'],indent=2),encoding='utf-8')
        (args.out/'history.json').write_text(json.dumps(result['history'],ensure_ascii=False,indent=2),encoding='utf-8')
        with(args.out/'commands.jsonl').open('x',encoding='utf-8') as output:
            for row in result['commands']:output.write(json.dumps(row,ensure_ascii=False)+'\n')
        if args.mission_monitor:
            with(args.out/'mission.jsonl').open('x',encoding='utf-8') as output:
                for row in result['mission']:output.write(json.dumps(row,ensure_ascii=False)+'\n')
        print(json.dumps(dict(replayed=True,input_source=result['report']['input_source'],records=result['report']['records'],control_enabled=False,out=str(args.out))))
    except (ValueError,OSError,TypeError) as e:parser.exit(2,str(e)+'\n')

if __name__=='__main__':main()
