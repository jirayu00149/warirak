"""Duration-aware research learner; preserves frozen one-step implementation.

No environment runner, dataset access, export or physical transport.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import torch
from torch import nn

from . import navigation_dqn as base
from .navigation_wire import validate_request,LAYOUT_SHA256,VECTOR_SIZE

_ROOT=Path(__file__).resolve().parents[1]
_BYTES=(_ROOT/'navigation-duration-dqn-recipe.json').read_bytes()
_R=json.loads(_BYTES)
RECIPE_SHA256=hashlib.sha256(_BYTES).hexdigest()
MODEL_SCHEMA=_R['model_schema']
CHECKPOINT_SCHEMA=_R['checkpoint_schema']
GAMMA=_R['gamma_per_original_100ms']
_FIELDS=json.loads((_ROOT/'navigation-history-layout.json').read_bytes())['field_order']
_REASONS=('none','collection','collision','time_limit')
_KEYS={'schema','source','plant_environment','episode_id','state_request','action','reward',
       'undiscounted_reward','duration_steps','continuation_discount','next_request','terminal',
       'terminal_reason','physical_motor_transport'}
_CLOCKS=('observation_at_ms','encoded_at_ms','record_sequence','stream_epoch')


def reward_bound(duration):
    if not base._integer(duration,1) or duration>_R['maximum_duration_steps']:
        raise ValueError('Duration outside original R2 horizon')
    return _R['per_step_reward_absolute_bound']*(1-GAMMA**duration)/(1-GAMMA)


def _current_frame(r):
    row=r['vector'][-78:]
    if row[0]!=1 or not math.isclose(row[1],(r['encoded_at_ms']-r['observation_at_ms'])/300,rel_tol=1e-10,abs_tol=1e-10):
        raise ValueError('Current frame/original encoding age mismatch')


def validate_duration_credit(t):
    if (type(t) is not dict or set(t)!=_KEYS or t['schema']!=_R['credit_schema'] or
        t['source']!='simulation' or t['plant_environment']!=base._RECIPE['environment'] or
        t['physical_motor_transport'] is not False or type(t['episode_id']) is not str or
        re.fullmatch(r'[A-Za-z0-9_.:-]{1,96}',t['episode_id']) is None):
        raise ValueError('Exact simulation duration-credit schema required')
    d=t['duration_steps'];bound=reward_bound(d)
    s,n=validate_request(t['state_request']),validate_request(t['next_request'])
    _current_frame(s);_current_frame(n)
    if (n['observation_at_ms']-s['observation_at_ms']!=d*_R['step_ms'] or
        n['record_sequence']-s['record_sequence']!=d or n['stream_epoch']<s['stream_epoch']):
        raise ValueError('Original clock/record duration mismatch')
    if n['stream_epoch']!=s['stream_epoch']:
        # The canonical encoder checks each row's epoch. A multi-step wait may
        # legitimately contain several later frames from the NEW epoch.
        for i in range(3):
            row=n['vector'][i*78:(i+1)*78]
            if row[0] and n['encoded_at_ms']-row[1]*300<=s['observation_at_ms']+.5:
                raise ValueError('Starting-epoch frame leaked across boundary')
    if not base._integer(t['action']) or t['action']>6 or not s['allowed_mask'][t['action']]:
        raise ValueError('No invented/passive/operator or prohibited action')
    if (not base._finite(t['continuation_discount']) or not math.isclose(t['continuation_discount'],GAMMA**d,rel_tol=1e-12,abs_tol=1e-15) or
        not base._finite(t['reward']) or abs(t['reward'])>bound+1e-9 or
        not base._finite(t['undiscounted_reward']) or abs(t['undiscounted_reward'])>64*d+1e-9 or
        d==1 and not math.isclose(t['reward'],t['undiscounted_reward'],rel_tol=1e-12,abs_tol=1e-9)):
        raise ValueError('Invalid duration discount/reward; no clipping or retiming')
    if (type(t['terminal']) is not bool or t['terminal_reason'] not in _REASONS or
        t['terminal']!=(t['terminal_reason']!='none')):
        raise ValueError('Only natural episode outcomes terminate bootstrap')
    return t


def one_step_as_duration(transition):
    t=base.validate_transition(transition)
    result=dict(schema=_R['credit_schema'],source='simulation',plant_environment=t['plant_environment'],
        episode_id=t['episode_id'],state_request=copy.deepcopy(t['state_request']),action=t['action'],
        reward=t['reward'],undiscounted_reward=t['reward'],duration_steps=1,continuation_discount=GAMMA,
        next_request=copy.deepcopy(t['next_request']),terminal=t['terminal'],terminal_reason=t['terminal_reason'],
        physical_motor_transport=False)
    return validate_duration_credit(result)


def masked_duration_targets(rewards,terminal,next_online,next_target,next_mask,discounts):
    if (rewards.ndim!=1 or terminal.shape!=rewards.shape or discounts.shape!=rewards.shape or
        next_online.shape!=(len(rewards),7) or next_target.shape!=next_online.shape or next_mask.shape!=next_online.shape or
        terminal.dtype!=torch.bool or next_mask.dtype!=torch.bool or discounts.dtype not in (torch.float32,torch.float64) or
        any(t.dtype!=torch.float32 for t in (rewards,next_online,next_target)) or
        any(t.device.type!='cpu' for t in (rewards,terminal,next_online,next_target,next_mask,discounts))):
        raise ValueError('Invalid variable-duration target shape/type')
    if (not all(torch.isfinite(t).all().item() for t in (rewards,next_online,next_target,discounts)) or
        (discounts<0).any().item() or (discounts>1).any().item() or
        ((~next_mask.any(dim=1)) & ~terminal).any().item()):
        raise ValueError('Invalid finite discount or nonterminal action mask')
    with torch.no_grad():
        selected=next_online.masked_fill(~next_mask,-torch.inf).argmax(dim=1)
        value=next_target.gather(1,selected[:,None]).squeeze(1)
        return torch.where(terminal,rewards,rewards+discounts.to(dtype=torch.float32)*value)


class DurationReplayRing(base.ReplayRing):
    def __init__(self):
        super().__init__();c=base._RECIPE['replay_capacity']
        self.durations=torch.zeros(c,dtype=torch.int64,device='cpu')
        self.discounts=torch.zeros(c,dtype=torch.float64,device='cpu')
        self.raw_rewards=torch.zeros(c,dtype=torch.float64,device='cpu')
        self.reasons=torch.zeros(c,dtype=torch.int64,device='cpu')
        for prefix in ('state','next'):
            for clock in _CLOCKS:setattr(self,prefix+'_'+clock,torch.zeros(c,dtype=torch.int64,device='cpu'))

    def append(self,credit):
        t=validate_duration_credit(credit);i=self.position
        s,n=t['state_request'],t['next_request']
        for name,request in (('states',s),('next_states',n)):
            getattr(self,name)[i]=torch.tensor(request['vector'],dtype=torch.float32,device='cpu')
        self.masks[i]=torch.tensor(s['allowed_mask'],dtype=torch.bool,device='cpu')
        self.next_masks[i]=torch.tensor(n['allowed_mask'],dtype=torch.bool,device='cpu')
        self.actions[i]=t['action'];self.rewards[i]=t['reward'];self.terminal[i]=t['terminal']
        self.durations[i]=t['duration_steps'];self.discounts[i]=t['continuation_discount']
        self.raw_rewards[i]=t['undiscounted_reward'];self.reasons[i]=_REASONS.index(t['terminal_reason'])
        for prefix,request in (('state',s),('next',n)):
            for clock in _CLOCKS:getattr(self,prefix+'_'+clock)[i]=request[clock]
        self.position=(i+1)%base._RECIPE['replay_capacity'];self.size=min(self.size+1,base._RECIPE['replay_capacity']);self.total_added+=1

    def restore(self,state):
        if type(state) is not dict or set(state)!=set(vars(self)):raise ValueError('Duration replay keys mismatch')
        c=base._RECIPE['replay_capacity']
        if (not all(base._integer(state[k]) for k in ('size','position','total_added')) or
            state['size']!=min(c,state['total_added']) or state['position']!=state['total_added']%c):
            raise ValueError('Invalid duration replay cursor')
        for name,current in vars(self).items():
            value=state[name]
            if isinstance(current,torch.Tensor) and (not isinstance(value,torch.Tensor) or value.dtype!=current.dtype or
                value.device.type!='cpu' or value.shape!=current.shape or not torch.isfinite(value).all().item()):
                raise ValueError('Invalid duration replay tensor:'+name)
        n=state['size']
        if n:
            get=lambda name:state[name][:n]
            d=get('durations')
            if ((d<1).any() or (d>960).any() or (get('states').abs()>1).any() or (get('next_states').abs()>1).any() or
                not get('masks').any(dim=1).all() or not get('next_masks').any(dim=1).all() or
                (get('actions')<0).any() or (get('actions')>6).any()):raise ValueError('Invalid duration replay domain')
            if not get('masks').gather(1,get('actions')[:,None]).all().item():raise ValueError('Replay action outside original mask')
            expected=torch.tensor([GAMMA**int(v) for v in d],dtype=torch.float64,device='cpu')
            bound=64*(1-expected)/(1-GAMMA)
            if (not torch.isclose(get('discounts'),expected,rtol=1e-12,atol=1e-15).all() or
                (get('rewards').double().abs()>bound+1e-3).any() or (get('raw_rewards').abs()>64*d.double()+1e-9).any() or
                (get('reasons')<0).any() or (get('reasons')>3).any() or
                not torch.equal(get('terminal'),get('reasons')!=0) or
                (get('next_observation_at_ms')-get('state_observation_at_ms')!=100*d).any() or
                (get('next_record_sequence')-get('state_record_sequence')!=d).any() or
                (get('next_stream_epoch')<get('state_stream_epoch')).any()):raise ValueError('Duration replay evidence mismatch')
            for prefix in ('state','next'):
                at,encoded=get(prefix+'_observation_at_ms'),get(prefix+'_encoded_at_ms')
                if ((at<=0).any() or (at>9007199254740991).any() or (encoded>9007199254740991).any() or (encoded<at).any() or (encoded>=at+300).any() or
                    (get(prefix+'_record_sequence')<0).any() or (get(prefix+'_record_sequence')>9007199254740991).any() or
                    (get(prefix+'_stream_epoch')<0).any() or (get(prefix+'_stream_epoch')>9007199254740991).any()):raise ValueError('Invalid replay original clocks')
        for name,value in state.items():setattr(self,name,value.clone() if isinstance(value,torch.Tensor) else value)


class DurationNavigationDQN(base.NavigationDQN):
    def __init__(self,seed,protocol_sha256):
        super().__init__(seed,protocol_sha256);self.replay=DurationReplayRing()

    def learn(self):
        if self.replay.size<base._RECIPE['minimum_replay']:return None
        self.online.train();r=self.replay
        indices=torch.randperm(r.size,generator=self.sample_rng,device='cpu')[:base._RECIPE['batch_size']]
        with torch.no_grad():targets=masked_duration_targets(r.rewards[indices],r.terminal[indices],
            self.online(r.next_states[indices]),self.target(r.next_states[indices]),r.next_masks[indices],r.discounts[indices])
        values=self.online(r.states[indices]).gather(1,r.actions[indices,None]).squeeze(1)
        loss=nn.functional.smooth_l1_loss(values,targets,beta=1.0)
        if not torch.isfinite(loss).item():raise ValueError('Nonfinite duration loss')
        self.optimizer.zero_grad(set_to_none=True);loss.backward()
        norm=nn.utils.clip_grad_norm_(self.online.parameters(),base._RECIPE['gradient_clip_norm'],error_if_nonfinite=True,foreach=False)
        self.optimizer.step();self.updates+=1
        if self.updates%base._RECIPE['target_update_gradient_steps']==0:self.target.load_state_dict(self.online.state_dict())
        return dict(loss=loss.item(),gradient_norm=norm.item(),updates=self.updates,indices=indices.tolist())

    def checkpoint(self,cursor):
        state=super().checkpoint(cursor)
        state.update(schema=CHECKPOINT_SCHEMA,model_schema=MODEL_SCHEMA,recipe_sha256=RECIPE_SHA256,
                     base_recipe_sha256=base.RECIPE_SHA256)
        return state

    def restore(self,state):
        template=self.checkpoint(dict(schema='warirak.navigation-episode-cursor.v1',phase='between_episodes',next_episode_index=0,environment_steps=0))
        if type(state) is not dict or set(state)!=set(template):raise ValueError('Duration checkpoint keys mismatch')
        for key in ('schema','model_schema','source','physical_motor_transport','production_runtime_supported','seed',
                    'protocol_sha256','layout_sha256','recipe_sha256','base_recipe_sha256','runtime'):
            if json.dumps(state[key],sort_keys=True)!=json.dumps(template[key],sort_keys=True):raise ValueError('Duration checkpoint identity mismatch:'+key)
        replay=DurationReplayRing();replay.restore(state['replay'])
        core=base.NavigationDQN(self.seed,self.protocol_sha256)
        # Reuse the frozen network/Adam/RNG validator with an isolated EMPTY base
        # replay; duration samples are validated above and never retyped as one-step.
        core_state={k:v for k,v in state.items() if k!='base_recipe_sha256'}
        core_state.update(schema=base.CHECKPOINT_SCHEMA,model_schema=base.MODEL_SCHEMA,
                          recipe_sha256=base.RECIPE_SHA256,replay=core.replay.state())
        core.restore(core_state)
        for name in ('online','target','optimizer','choice_rng','sample_rng','updates','choices','cursor'):
            setattr(self,name,getattr(core,name))
        self.replay=replay
