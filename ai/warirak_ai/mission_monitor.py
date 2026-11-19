"""Advisory motion/actuation monitor. Detecting a stop request is not evidence of station holding.

No actuator transport or HOLD/RECOVERY controller is implemented. This does not replace
ShadowSupervisor's command watchdog or manual/obstacle interlocks.
"""
from dataclasses import dataclass,asdict
import math
from .visual_pilot import finite

@dataclass(frozen=True)
class MonitorLimits:
    max_age_ms:int=500
    evidence_gap_ms:int=500
    evidence_ms:int=600
    stall_ms:int=2000
    ack_timeout_ms:int=500
    stationary_speed_mps:float=.015
    moving_speed_mps:float=.04
    min_confidence:float=.8
    max_uncertainty_mps:float=.015
    def __post_init__(self):
        for key in ['max_age_ms','evidence_gap_ms','evidence_ms','stall_ms','ack_timeout_ms']:
            if type(getattr(self,key)) is not int or not 1<=getattr(self,key)<=10000:raise ValueError('Invalid monitor timing limit')
        if not 0<self.stationary_speed_mps<self.moving_speed_mps<1 or not 0<self.min_confidence<=1 or not 0<self.max_uncertainty_mps<.1:raise ValueError('Invalid motion evidence limits')

class MissionMonitor:
    def __init__(self,input_source='simulation',limits=None):
        if input_source not in ['simulation','recorded']:raise ValueError('Explicit simulation/recorded source required')
        self.input_source=input_source;self.limits=limits or MonitorLimits();self.latched=None;self.latched_mode=None;self.latched_request=None;self.last_now=None;self.last_command=None;self.last_motion_stamp=None;self.phase=None;self.phase_start=None;self.phase_sequence=None;self.evidence=None
    def _fresh(self,stamp,now):return finite(stamp) and -100<=now-stamp<=self.limits.max_age_ms
    def _clear_evidence(self):self.evidence=None
    def _output(self,mode,reason,motion=None,ack_valid=False,request=None):
        return dict(schema='warirak.mission-monitor.v1',source='shadow_only',input_source=self.input_source,mode=mode,reason=reason,motion_state=motion['state'] if motion else'unknown',observed_speed_mps=motion['speed'] if motion else None,motion_estimate_used=motion is not None,actuator_feedback_valid=ack_valid,proposal_allowed=mode=='TRACKING',zero_autonomous_thrust_requested=mode!='TRACKING',assistance_request=request,operator_reset_required=self.latched is not None,latched_reason=self.latched,station_keeping_verified=False,hold_controller_available=False,recovery_controller_available=False,control_enabled=False,real_world_validated=False)
    def _latch(self,reason,mode='MANUAL_ASSIST_REQUIRED',motion=None,ack_valid=False,request='manual_assist'):
        self.latched=reason;self.latched_mode=mode;self.latched_request=request;self._clear_evidence();return self._output(mode,reason,motion,ack_valid,request)
    def _motion(self,value,now):
        expected='simulation' if self.input_source=='simulation' else'measured'
        if not isinstance(value,dict) or value.get('schema')!='warirak.motion-estimate.v1' or value.get('source')!=expected or value.get('calibrated') is not True:return None
        if value.get('frame') not in ['pool_fixed','earth_fixed'] or value.get('units')!='m/s' or not self._fresh(value.get('timestamp_unix_ms'),now):return None
        methods=['simulation_truth'] if expected=='simulation' else['external_tracking','gnss_velocity','calibrated_visual_odometry']
        if value.get('method') not in methods:return None
        vx=value.get('vx_mps');vy=value.get('vy_mps');confidence=value.get('confidence');uncertainty=value.get('speed_std_mps')
        if not all(finite(v) for v in [vx,vy,confidence,uncertainty]) or not self.limits.min_confidence<=confidence<=1 or not 0<=uncertainty<=self.limits.max_uncertainty_mps:return None
        speed=math.hypot(vx,vy)
        if speed>3:return None
        state='stationary' if speed+2*uncertainty<=self.limits.stationary_speed_mps else'moving' if speed-2*uncertainty>=self.limits.moving_speed_mps else'ambiguous'
        stamp=value['timestamp_unix_ms']
        if self.last_motion_stamp is not None and stamp<self.last_motion_stamp:return None
        self.last_motion_stamp=stamp
        return dict(state=state,speed=speed,stamp=stamp)
    def _feedback(self,value,now,current_sequence):
        expected='simulation' if self.input_source=='simulation' else'controller_feedback'
        if not isinstance(value,dict) or value.get('schema')!='warirak.actuator-feedback.v1' or value.get('source')!=expected or value.get('units')!='normalized' or not self._fresh(value.get('timestamp_unix_ms'),now):return None
        sequence=value.get('applied_sequence');left=value.get('left');right=value.get('right')
        if type(sequence) is not int or not self.phase_sequence<=sequence<=current_sequence or value['timestamp_unix_ms']<self.phase_start-100 or not finite(left) or not finite(right) or max(abs(left),abs(right))>1:return None
        return dict(zero=max(abs(left),abs(right))<=.005,active=max(abs(left),abs(right))>=.05,stamp=value['timestamp_unix_ms'])
    def _observe_evidence(self,kind,motion):
        if motion is None or motion['state']=='ambiguous':self._clear_evidence();return False
        stamp=motion['stamp'];e=self.evidence
        if e is None or e['kind']!=kind or stamp<e['last'] or stamp-e['last']>self.limits.evidence_gap_ms:self.evidence=dict(kind=kind,first=stamp,last=stamp,count=1)
        elif stamp>e['last']:e.update(last=stamp,count=e['count']+1)
        e=self.evidence;required=self.limits.stall_ms if kind=='possible_stall' else self.limits.evidence_ms
        return e['count']>=3 and e['last']-e['first']>=required
    def reset(self,sensors,now_ms):
        if not finite(now_ms) or now_ms<=0 or self.last_now is not None and now_ms<self.last_now or not isinstance(sensors,dict) or not self._fresh(sensors.get('timestamp_unix_ms'),now_ms) or sensors.get('armed') is not False:raise ValueError('Operator reset requires fresh disarmed sensor state and a valid clock')
        self.latched=None;self.latched_mode=None;self.latched_request=None;self.last_now=now_ms;self.last_command=None;self.last_motion_stamp=None;self.phase=None;self.phase_start=None;self.phase_sequence=None;self._clear_evidence()
    def update(self,command,sensors,motion=None,actuator_feedback=None,now_ms=None,hold_requested=False):
        if not finite(now_ms) or now_ms<=0:raise ValueError('Finite epoch receiver clock required')
        if self.last_now is not None and now_ms<self.last_now:return self._latch('receiver_clock_regression')
        self.last_now=now_ms;observed=self._motion(motion,now_ms)
        if not isinstance(sensors,dict) or not self._fresh(sensors.get('timestamp_unix_ms'),now_ms):return self._latch('sensor_watchdog','FAULT_STOP',observed)
        if sensors.get('manual_override') is True:self._clear_evidence();self.phase=None;return self._output('MANUAL_OVERRIDE','manual_control_has_priority',observed)
        if sensors.get('armed') is False:self._clear_evidence();self.phase=None;return self._output('DISARMED','autonomous_channel_disarmed',observed)
        if sensors.get('armed') is not True or sensors.get('manual_override') is not False:return self._latch('invalid_arm_state','FAULT_STOP',observed)
        if self.latched:return self._output(self.latched_mode,self.latched,observed,request=self.latched_request)
        battery=sensors.get('battery_percent');clearance=sensors.get('clearance_m')
        if not finite(battery) or not 25<=battery<=100:return self._latch('low_or_invalid_battery','FAULT_STOP',observed)
        if sensors.get('fault') not in [None,False,''] or not isinstance(clearance,list) or len(clearance)!=3 or not all(finite(v) and 0<=v<=20 for v in clearance):return self._latch('invalid_clearance_or_sensor_fault','FAULT_STOP',observed)
        if min(clearance)<.35:return self._latch('obstacle_stop','FAULT_STOP',observed)
        if hold_requested:return self._latch('position_hold_controller_unavailable','HOLD_REQUIRED',observed,request='position_hold_or_manual_assist')
        if not isinstance(command,dict) or command.get('schema')!='warirak.shadow-command.v2' or command.get('environment')!='warirak-visual-history-v2' or command.get('source')!='shadow_only' or command.get('control_enabled') is not False:self.phase=None;self._clear_evidence();return self._output('WAIT_COMMAND','invalid_or_missing_command',observed)
        issued=command.get('issued_at_ms');expires=command.get('valid_until_ms');sequence=command.get('sequence');left=command.get('left');right=command.get('right')
        if not finite(issued) or not finite(expires) or not issued<=now_ms<expires or not 0<expires-issued<=500 or type(sequence) is not int or sequence<0 or not finite(left) or not finite(right) or max(abs(left),abs(right))>.25:self.phase=None;self._clear_evidence();return self._output('WAIT_COMMAND','expired_or_invalid_command',observed)
        signature=(sequence,issued,expires,left,right,command.get('action'))
        if self.last_command and (sequence<self.last_command[0] or sequence==self.last_command[0] and signature!=self.last_command):return self._latch('command_replay_or_conflict','FAULT_STOP',observed)
        self.last_command=signature;stopped=max(abs(left),abs(right))<.001
        expected='STOP' if stopped else'TURN_RIGHT' if left-right>.01 else'TURN_LEFT' if right-left>.01 else'FORWARD'
        if command.get('action')!=expected or not stopped and left+right<-.001:return self._latch('command_action_mismatch','FAULT_STOP',observed)
        phase='stop' if stopped else'move'
        if phase!=self.phase:self.phase=phase;self.phase_start=now_ms;self.phase_sequence=sequence;self._clear_evidence()
        feedback=self._feedback(actuator_feedback,now_ms,sequence)
        matches=feedback is not None and (feedback['zero'] if stopped else feedback['active'])
        if not matches:
            self._clear_evidence()
            if now_ms-self.phase_start>=self.limits.ack_timeout_ms:return self._latch('actuator_ack_missing_or_inconsistent',motion=observed)
            return self._output('WAIT_STOP_ACK' if stopped else'WAIT_ACTUATOR_ACK','fresh_applied_command_feedback_required',observed)
        if observed is None:self._clear_evidence();return self._output('MOTION_UNKNOWN','fresh_calibrated_motion_required',ack_valid=True)
        if stopped:
            if observed['state']=='moving' and self._observe_evidence('motion_after_stop',observed):return self._latch('sustained_motion_after_zero_command','HOLD_REQUIRED',observed,True,'position_hold_or_manual_assist')
            if observed['state']=='stationary' and self._observe_evidence('stationary_after_stop',observed):return self._output('STOPPED_OBSERVED','stationary_evidence_present_now',observed,True)
            if observed['state']=='ambiguous':self._clear_evidence()
            return self._output('STOPPING_OBSERVED','stop_request_is_not_station_holding',observed,True)
        if observed['state']=='stationary' and self._observe_evidence('possible_stall',observed):return self._latch('sustained_low_motion_with_applied_thrust','RECOVERY_REQUIRED',observed,True,'manual_recovery_assessment')
        if observed['state']!='stationary':self._clear_evidence()
        if observed['state']=='ambiguous':return self._output('MOTION_UNKNOWN','motion_uncertainty_overlaps_thresholds',observed,True)
        return self._output('TRACKING','observations_available_not_field_certified',observed,True)

    def configuration(self):return dict(schema='warirak.mission-monitor-config.v1',input_source=self.input_source,limits=asdict(self.limits),defaults_hardware_calibrated=False)
