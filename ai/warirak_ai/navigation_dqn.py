"""CPU research learner foundation. No episode runner, hardware or launch-on-import.

SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import sys

import torch
from torch import nn

from .navigation_wire import (LAYOUT_SHA256, VECTOR_SIZE, validate_request,
                              validation_fixture_reply)

_ROOT = Path(__file__).resolve().parents[1]
_RECIPE_BYTES = (_ROOT / 'navigation-dqn-recipe.json').read_bytes()
_RECIPE = json.loads(_RECIPE_BYTES)
RECIPE_SHA256 = hashlib.sha256(_RECIPE_BYTES).hexdigest()
MODEL_SCHEMA = _RECIPE['model_schema']
CHECKPOINT_SCHEMA = 'warirak.navigation-history-dqn-checkpoint.v1'
TRANSITION_SCHEMA = 'warirak.navigation-history-transition.v1'
_TRANSITION_KEYS = {'schema','source','plant_environment','episode_id','state_request',
                    'action','reward','next_request','terminal','terminal_reason'}
_HEX = re.compile(r'[0-9a-f]{64}')
_FIELDS = json.loads((_ROOT / 'navigation-history-layout.json').read_bytes())['field_order']


def _integer(v, minimum=0):
    return type(v) is int and minimum <= v <= 9007199254740991


def _finite(v):
    if type(v) not in (int,float):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:
        return False


def validate_transition(t):
    if type(t) is not dict or set(t) != _TRANSITION_KEYS:
        raise ValueError('Unexpected transition keys')
    if (t['schema'] != TRANSITION_SCHEMA or t['source'] != 'simulation' or
        t['plant_environment'] != _RECIPE['environment'] or
        type(t['episode_id']) is not str or re.fullmatch(r'[A-Za-z0-9_.:-]{1,96}',t['episode_id']) is None):
        raise ValueError('Synthetic transition identity required')
    s,n = validate_request(t['state_request']),validate_request(t['next_request'])
    if (n['observation_at_ms']-s['observation_at_ms'] != _RECIPE['step_ms'] or
        n['record_sequence'] != s['record_sequence']+1 or n['stream_epoch'] < s['stream_epoch']):
        raise ValueError('Consecutive original step/record required')
    if n['stream_epoch'] != s['stream_epoch']:
        # Memory boundaries clear features, not the environmental reward/collision tail.
        current = n['vector'][-78:]
        if any(v != 0 for v in n['vector'][:-78]) or current[_FIELDS.index('previous_request.UNKNOWN')] != 1:
            raise ValueError('Epoch changed without a cleared next history')
    a = t['action']
    if not _integer(a) or a > 6 or not s['allowed_mask'][a]:
        raise ValueError('Recorded navigation request outside original mask')
    if not _finite(t['reward']) or abs(t['reward']) > _RECIPE['reward_absolute_bound']:
        raise ValueError('Invalid bounded reward')
    if type(t['terminal']) is not bool or t['terminal_reason'] not in ('none','collection','collision','time_limit'):
        raise ValueError('Invalid terminal accounting')
    if t['terminal'] != (t['terminal_reason'] != 'none'):
        raise ValueError('Terminal reason mismatch; assistance is not termination')
    return t


class QNetwork(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(VECTOR_SIZE,64,device='cpu',dtype=torch.float32),nn.ReLU(),
                                    nn.Linear(64,64,device='cpu',dtype=torch.float32),nn.ReLU(),
                                    nn.Linear(64,7,device='cpu',dtype=torch.float32))

    def forward(self, vector):
        return self.layers(vector)


def masked_double_targets(rewards, terminal, next_online, next_target, next_mask,
                          gamma=_RECIPE['gamma']):
    """Pure target calculation; an unavailable action never supplies bootstrap value."""
    if (next_online.ndim != 2 or next_online.shape[1] != 7 or
        next_target.shape != next_online.shape or next_mask.shape != next_online.shape or
        rewards.shape != terminal.shape or rewards.ndim != 1 or
        rewards.shape[0] != next_online.shape[0] or terminal.dtype != torch.bool or
        next_mask.dtype != torch.bool or not _finite(gamma) or not 0 <= gamma <= 1 or
        any(t.device.type != 'cpu' for t in (rewards,terminal,next_online,next_target,next_mask)) or
        any(t.dtype != torch.float32 for t in (rewards,next_online,next_target))):
        raise ValueError('Invalid Double-DQN target shape/type')
    if not all(torch.isfinite(t).all().item() for t in (rewards,next_online,next_target)):
        raise ValueError('Nonfinite target input')
    if ((~next_mask.any(dim=1)) & ~terminal).any().item():
        raise ValueError('Nonterminal next state needs at least one permitted request')
    with torch.no_grad():
        selected = next_online.masked_fill(~next_mask,-torch.inf).argmax(dim=1)
        continuation = next_target.gather(1,selected[:,None]).squeeze(1)
        return torch.where(terminal,rewards,rewards+gamma*continuation)


class ReplayRing:
    def __init__(self):
        c,v = _RECIPE['replay_capacity'],VECTOR_SIZE
        self.states = torch.zeros((c,v),dtype=torch.float32,device='cpu')
        self.next_states = torch.zeros((c,v),dtype=torch.float32,device='cpu')
        self.masks = torch.zeros((c,7),dtype=torch.bool,device='cpu')
        self.next_masks = torch.zeros((c,7),dtype=torch.bool,device='cpu')
        self.actions = torch.zeros(c,dtype=torch.int64,device='cpu')
        self.rewards = torch.zeros(c,dtype=torch.float32,device='cpu')
        self.terminal = torch.zeros(c,dtype=torch.bool,device='cpu')
        self.position = self.size = self.total_added = 0

    def append(self, transition):
        t = validate_transition(transition)
        i,s,n = self.position,t['state_request'],t['next_request']
        self.states[i] = torch.tensor(s['vector'],dtype=torch.float32,device='cpu')
        self.next_states[i] = torch.tensor(n['vector'],dtype=torch.float32,device='cpu')
        self.masks[i] = torch.tensor(s['allowed_mask'],dtype=torch.bool,device='cpu')
        self.next_masks[i] = torch.tensor(n['allowed_mask'],dtype=torch.bool,device='cpu')
        self.actions[i],self.rewards[i],self.terminal[i] = t['action'],t['reward'],t['terminal']
        self.position = (i+1) % _RECIPE['replay_capacity']
        self.size = min(self.size+1,_RECIPE['replay_capacity'])
        self.total_added += 1

    def state(self):
        return {name:(value.clone() if isinstance(value,torch.Tensor) else value)
                for name,value in vars(self).items()}

    def restore(self, state):
        if type(state) is not dict or set(state) != set(vars(self)):
            raise ValueError('Replay state shape mismatch')
        c = _RECIPE['replay_capacity']
        if (not all(_integer(state[k]) for k in ('size','position','total_added')) or
            state['size'] != min(c,state['total_added']) or state['position'] != state['total_added'] % c):
            raise ValueError('Invalid replay cursor')
        for name,current in vars(self).items():
            value = state[name]
            if isinstance(current,torch.Tensor):
                if (not isinstance(value,torch.Tensor) or value.device.type != 'cpu' or
                    value.dtype != current.dtype or value.shape != current.shape or not torch.isfinite(value).all().item()):
                    raise ValueError('Invalid replay tensor '+name)
        n = state['size']
        if n:
            if ((state['states'][:n].abs()>1).any() or (state['next_states'][:n].abs()>1).any() or
                not state['masks'][:n].any(dim=1).all() or not state['next_masks'][:n].any(dim=1).all() or
                (state['actions'][:n]<0).any() or (state['actions'][:n]>6).any() or
                (state['rewards'][:n].abs()>_RECIPE['reward_absolute_bound']).any()):
                raise ValueError('Invalid replay values/masks')
            if not state['masks'][:n].gather(1,state['actions'][:n,None]).all().item():
                raise ValueError('Replay action violates original mask')
        for name,value in state.items():
            setattr(self,name,value.clone() if isinstance(value,torch.Tensor) else value)


def _cursor(cursor):
    if (type(cursor) is not dict or set(cursor) != {'schema','phase','next_episode_index','environment_steps'} or
        cursor['schema'] != 'warirak.navigation-episode-cursor.v1' or cursor['phase'] != 'between_episodes' or
        not _integer(cursor['next_episode_index']) or not _integer(cursor['environment_steps'])):
        raise ValueError('Explicit between-episode cursor required; mid-episode resume unsupported')
    return copy.deepcopy(cursor)


class NavigationDQN:
    def __init__(self, seed, protocol_sha256):
        if not _integer(seed) or seed > 2147483647 or type(protocol_sha256) is not str or not _HEX.fullmatch(protocol_sha256):
            raise ValueError('Explicit bounded seed and protocol hash required')
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        self.seed,self.protocol_sha256 = seed,protocol_sha256
        # Local CPU initialization does not seed or allocate CUDA, or advance caller RNG.
        with torch.random.fork_rng(devices=[]):
            torch.set_rng_state(torch.Generator(device='cpu').manual_seed(seed).get_state())
            self.online = QNetwork()
        self.target = copy.deepcopy(self.online).requires_grad_(False)
        o = _RECIPE['optimizer']
        self.optimizer = torch.optim.Adam(self.online.parameters(),lr=o['lr'],betas=tuple(o['betas']),eps=o['eps'],foreach=False)
        self.replay = ReplayRing()
        self.choice_rng = random.Random(seed ^ 0x43A7149)
        self.sample_rng = torch.Generator(device='cpu').manual_seed(seed ^ 0x17BC921)
        self.updates = self.choices = 0
        self.cursor = None

    def q_values(self, request, *, now_ms):
        validate_request(request,now_ms=now_ms)
        with torch.no_grad():
            q = self.online(torch.tensor(request['vector'],dtype=torch.float32,device='cpu')[None,:])[0]
        if not torch.isfinite(q).all().item():
            raise ValueError('Nonfinite model output')
        return q.tolist()

    def choose(self, request, epsilon, *, now_ms):
        if not _finite(epsilon) or not 0 <= epsilon <= 1:
            raise ValueError('Invalid explicit epsilon')
        q = self.q_values(request,now_ms=now_ms)
        allowed = [i for i,ok in enumerate(request['allowed_mask']) if ok]
        action = self.choice_rng.choice(allowed) if self.choice_rng.random() < epsilon else max(allowed,key=lambda a:q[a])
        self.choices += 1
        return action

    def preflight_reply(self, request, *, now_ms):
        # Untrained/unit-checkpoint outputs are always the forbidden-by-default fixture schema.
        return validation_fixture_reply(request,self.q_values(request,now_ms=now_ms),now_ms=now_ms)

    def learn(self):
        if self.replay.size < _RECIPE['minimum_replay']:
            return None
        self.online.train()
        indices = torch.randperm(self.replay.size,generator=self.sample_rng,device='cpu')[:_RECIPE['batch_size']]
        r = self.replay
        with torch.no_grad():
            targets = masked_double_targets(r.rewards[indices],r.terminal[indices],
                self.online(r.next_states[indices]),self.target(r.next_states[indices]),r.next_masks[indices])
        values = self.online(r.states[indices]).gather(1,r.actions[indices,None]).squeeze(1)
        loss = nn.functional.smooth_l1_loss(values,targets,beta=1.0)
        if not torch.isfinite(loss).item():
            raise ValueError('Nonfinite loss')
        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        norm = nn.utils.clip_grad_norm_(self.online.parameters(),_RECIPE['gradient_clip_norm'],error_if_nonfinite=True,foreach=False)
        self.optimizer.step()
        self.updates += 1
        if self.updates % _RECIPE['target_update_gradient_steps'] == 0:
            self.target.load_state_dict(self.online.state_dict())
        return dict(loss=loss.item(),gradient_norm=norm.item(),updates=self.updates,indices=indices.tolist())

    def checkpoint(self, cursor):
        return dict(schema=CHECKPOINT_SCHEMA,model_schema=MODEL_SCHEMA,source='simulation',
            physical_motor_transport=False,production_runtime_supported=False,seed=self.seed,
            protocol_sha256=self.protocol_sha256,layout_sha256=LAYOUT_SHA256,recipe_sha256=RECIPE_SHA256,
            runtime=dict(torch=str(torch.__version__),python=sys.version,device='cpu',threads=1),
            online=copy.deepcopy(self.online.state_dict()),target=copy.deepcopy(self.target.state_dict()),
            optimizer=copy.deepcopy(self.optimizer.state_dict()),replay=self.replay.state(),
            choice_rng=self.choice_rng.getstate(),sample_rng=self.sample_rng.get_state().clone(),
            updates=self.updates,choices=self.choices,cursor=_cursor(cursor))

    def restore(self, state):
        template = self.checkpoint(dict(schema='warirak.navigation-episode-cursor.v1',phase='between_episodes',next_episode_index=0,environment_steps=0))
        if type(state) is not dict or set(state) != set(template):
            raise ValueError('Unexpected checkpoint keys')
        for key in ('schema','model_schema','source','physical_motor_transport','production_runtime_supported',
                    'seed','protocol_sha256','layout_sha256','recipe_sha256','runtime'):
            if json.dumps(state[key],sort_keys=True) != json.dumps(template[key],sort_keys=True):
                raise ValueError('Checkpoint identity/runtime mismatch: '+key)
        if not _integer(state['updates']) or not _integer(state['choices']):
            raise ValueError('Invalid checkpoint counters')
        cursor = _cursor(state['cursor'])
        for key,network in (('online',self.online),('target',self.target)):
            if type(state[key]) not in (dict,type(network.state_dict())) or set(state[key]) != set(network.state_dict()):
                raise ValueError('Model state keys mismatch')
            for name,value in state[key].items():
                expected = network.state_dict()[name]
                if (not isinstance(value,torch.Tensor) or value.dtype != expected.dtype or
                    value.device.type != 'cpu' or value.shape != expected.shape or not torch.isfinite(value).all().item()):
                    raise ValueError('Invalid model tensor '+name)
        # Validate using temporary state owners, so a malformed restore cannot partly change this learner.
        replay = ReplayRing();replay.restore(state['replay'])
        choice = random.Random();choice.setstate(state['choice_rng'])
        sampler = torch.Generator(device='cpu');sampler.set_state(state['sample_rng'])
        online = copy.deepcopy(self.online);online.load_state_dict(state['online'])
        target = copy.deepcopy(self.target);target.load_state_dict(state['target'])
        o = _RECIPE['optimizer']
        optimizer = torch.optim.Adam(online.parameters(),lr=o['lr'],betas=tuple(o['betas']),eps=o['eps'],foreach=False)
        optimizer.load_state_dict(copy.deepcopy(state['optimizer']))
        if len(optimizer.param_groups) != 1 or state['optimizer']['param_groups'] != template['optimizer']['param_groups']:
            raise ValueError('Invalid optimizer groups')
        group=optimizer.param_groups[0]
        if any(group[key] != expected for key,expected in [('lr',o['lr']),('betas',tuple(o['betas'])),('eps',o['eps']),('foreach',False)]):
            raise ValueError('Optimizer recipe mismatch')
        if len(optimizer.state) != (len(list(online.parameters())) if state['updates'] else 0):
            raise ValueError('Adam state/update counter mismatch')
        for parameter,values in optimizer.state.items():
            if set(values) != {'step','exp_avg','exp_avg_sq'}:
                raise ValueError('Invalid Adam slots')
            for name,value in values.items():
                if (not isinstance(value,torch.Tensor) or value.device.type != 'cpu' or not torch.isfinite(value).all().item() or
                    (name == 'step' and (value.ndim != 0 or value.item() != state['updates'])) or
                    (name != 'step' and (value.shape != parameter.shape or value.dtype != parameter.dtype)) or
                    (name == 'exp_avg_sq' and (value < 0).any().item())):
                    raise ValueError('Invalid Adam state')
        self.online,self.target,self.optimizer,self.replay = online,target,optimizer,replay
        self.choice_rng,self.sample_rng,self.updates,self.choices = choice,sampler,state['updates'],state['choices']
        self.cursor = cursor

    def save(self, path, cursor):
        path = Path(path)
        temp = path.with_name(path.name+'.pending')
        if temp.exists():
            raise ValueError('Inspect existing pending checkpoint before overwriting')
        with temp.open('xb') as file:
            torch.save(self.checkpoint(cursor),file)
            file.flush();os.fsync(file.fileno())
        if temp.stat().st_size > _RECIPE['checkpoint_maximum_mib']*1048576:
            raise ValueError('Checkpoint budget exceeded; pending file preserved')
        digest = hashlib.sha256(temp.read_bytes()).hexdigest()
        os.replace(temp,path)
        return digest

    def load(self, path, *, expected_sha256):
        path = Path(path)
        if type(expected_sha256) is not str or not _HEX.fullmatch(expected_sha256):
            raise ValueError('Expected trusted checkpoint hash required')
        if path.stat().st_size > _RECIPE['checkpoint_maximum_mib']*1048576:
            raise ValueError('Checkpoint size bound exceeded')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
            raise ValueError('Checkpoint file hash mismatch')
        self.restore(torch.load(path,map_location='cpu',weights_only=True))
