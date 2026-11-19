"""STOP/watchdog supervisor and bounded history. Software proposals only; no motor transport.

This v2 contract is distinct from the 5-action Q-table environment. History is a recording
interface for future temporal learning, not a newly trained history policy.
"""
from collections import deque
from copy import deepcopy
from .visual_pilot import VisualPilot,finite

SCHEMA='warirak.shadow-command.v2'
ENVIRONMENT='warirak-visual-history-v2'
ACTIONS=('STOP','FORWARD','TURN_LEFT','TURN_RIGHT')

class ShadowSupervisor:
    def __init__(self,ttl_ms=400):
        if not isinstance(ttl_ms,int) or not 50<=ttl_ms<=500:raise ValueError('TTL must be 50..500ms')
        self.ttl=ttl_ms;self.sequence=0;self.last=None;self.sensors=None;self.last_issue=None
    def _stop(self,reason,now):
        return dict(schema=SCHEMA,environment=ENVIRONMENT,source='shadow_only',sequence=self.sequence,issued_at_ms=now,valid_until_ms=now+self.ttl,action='STOP',left=0.,right=0.,reason=reason,control_enabled=False,collection_confirmed=False)
    def _sensor_fault(self,sensors,now):
        if not isinstance(sensors,dict):return 'missing_sensors'
        timestamp=sensors.get('timestamp_unix_ms')
        if not finite(timestamp) or not -100<=now-timestamp<=500:return 'sensor_watchdog'
        if sensors.get('armed') is not True or sensors.get('manual_override') is not False:return 'disarmed_or_manual'
        if sensors.get('fault') not in (None,False,''):return 'sensor_fault'
        battery=sensors.get('battery_percent');distance=sensors.get('clearance_m')
        if not finite(battery) or not 25<=battery<=100:return 'low_or_invalid_battery'
        if not isinstance(distance,list) or len(distance)!=3 or not all(finite(x) and 0<=x<=20 for x in distance):return 'invalid_clearance'
        if min(distance)<.35:return 'obstacle_stop'
    def submit(self,proposal,sensors,now_ms):
        if not finite(now_ms):raise ValueError('Finite receiver clock required')
        self.sequence+=1;self.sensors=deepcopy(sensors) if isinstance(sensors,dict) else None
        fault=self._sensor_fault(sensors,now_ms)
        command=self._stop(fault or 'invalid_proposal',now_ms)
        if not fault and isinstance(proposal,dict):
            issued=proposal.get('generated_at_ms');left=proposal.get('left');right=proposal.get('right')
            valid=proposal.get('schema')=='warirak.visual-pilot.v1' and proposal.get('source')=='shadow_only' and proposal.get('control_enabled') is False and finite(issued) and 0<=now_ms-issued<=self.ttl and (self.last_issue is None or issued>self.last_issue)
            if valid and finite(left) and finite(right) and max(abs(left),abs(right))<=.25:
                self.last_issue=issued;front=sensors['clearance_m'][1];turn=left-right
                if left+right<-.001:command['reason']='reverse_blocked'
                elif left+right>.001 and front<.65:command['reason']='forward_clearance_stop'
                elif turn>.01 and sensors['clearance_m'][2]<.65 or turn<-.01 and sensors['clearance_m'][0]<.65:command['reason']='turn_clearance_stop'
                else:
                    action='STOP' if max(abs(left),abs(right))<.001 else 'TURN_RIGHT' if turn>.01 else 'TURN_LEFT' if turn<-.01 else 'FORWARD'
                    command.update(action=action,left=left,right=right,reason=proposal.get('reason','proposal'))
        self.last=command;return dict(command)
    def tick(self,now_ms,sensors=None):
        if not finite(now_ms):raise ValueError('Finite receiver clock required')
        def halt(reason):self.last=None;return self._stop(reason,now_ms)
        if sensors is not None:self.sensors=deepcopy(sensors) if isinstance(sensors,dict) else None
        fault=self._sensor_fault(self.sensors,now_ms)
        if fault:return halt(fault)
        if self.last is None or now_ms<self.last['issued_at_ms'] or now_ms>=self.last['valid_until_ms']:return halt('command_watchdog')
        # Recheck fresh distances even when the last command has not expired.
        left,right=self.last['left'],self.last['right'];dist=self.sensors['clearance_m']
        if left+right>.001 and dist[1]<.65:return halt('forward_clearance_stop')
        if left-right>.01 and dist[2]<.65 or right-left>.01 and dist[0]<.65:return halt('turn_clearance_stop')
        return dict(self.last)
    def cancel(self,now_ms,reason='cancelled'):
        if not finite(now_ms):raise ValueError('Finite receiver clock required')
        self.sequence+=1;self.last=None
        return self._stop(reason,now_ms)

class ShadowController:
    def __init__(self,history_size=8,**pilot_options):
        if not isinstance(history_size,int) or not 2<=history_size<=64:raise ValueError('History size must be 2..64')
        self.pilot=VisualPilot(**pilot_options);self.supervisor=ShadowSupervisor();self.history=deque(maxlen=history_size)
    def step(self,detection,sensors,now_ms):
        proposal=self.pilot.propose(detection,sensors,now_ms);command=self.supervisor.submit(proposal,sensors,now_ms)
        self.history.append(deepcopy(dict(timestamp_unix_ms=now_ms,frame_id=detection.get('frame_id') if isinstance(detection,dict) else None,target=proposal.get('target'),confirmed_frames=proposal.get('confirmed_frames',0),sensor_clearance_m=list(sensors['clearance_m']) if isinstance(sensors,dict) and isinstance(sensors.get('clearance_m'),list) else None,command=dict(command))))
        return command
    def snapshot(self):
        return dict(schema='warirak.control-history.v2',environment=ENVIRONMENT,source='shadow_only',trained_temporal_policy=False,control_enabled=False,records=deepcopy(list(self.history)))
