"""Deterministic CPU SOFTWARE checks. Only synthetic transitions; no plant/data trials."""
import copy
import json
from pathlib import Path
import random
import tempfile
import unittest

import torch

from warirak_ai.navigation_dqn import (NavigationDQN,ReplayRing,MODEL_SCHEMA,
    validate_transition,masked_double_targets)
from warirak_ai.navigation_wire import vector_digest

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=json.loads((ROOT/'tests/fixtures/navigation-dqn-vectors.json').read_text(encoding='utf-8'))
REQUESTS=FIXTURE['requests']
PROTOCOL='a'*64
CURSOR=dict(schema='warirak.navigation-episode-cursor.v1',phase='between_episodes',next_episode_index=0,environment_steps=0)


def transition(i=0,terminal=False):
    return dict(schema='warirak.navigation-history-transition.v1',source='simulation',
        plant_environment='warirak-pool-mission-v4r2-dev',episode_id='synthetic-unit',
        state_request=copy.deepcopy(REQUESTS[i]),next_request=copy.deepcopy(REQUESTS[i+1]),
        action=i%2,reward=-.015,terminal=terminal,terminal_reason='collision' if terminal else 'none')


def populate(model):
    for i in range(256):
        t=transition(i%3,i%11==0)
        t['reward']=(-1 if i%11==0 else .01*(i%5))
        model.replay.append(t)


def equal(test,a,b):
    test.assertEqual(type(a),type(b))
    if isinstance(a,torch.Tensor):
        test.assertTrue(torch.equal(a,b));test.assertEqual(a.dtype,b.dtype)
    elif isinstance(a,dict):
        test.assertEqual(set(a),set(b))
        for k in a: equal(test,a[k],b[k])
    elif isinstance(a,(list,tuple)):
        test.assertEqual(len(a),len(b))
        for x,y in zip(a,b): equal(test,x,y)
    else: test.assertEqual(a,b)


class TestNavigationDQN(unittest.TestCase):
    def test_01_architecture_is_small_cpu_float32(self):
        m=NavigationDQN(73,PROTOCOL)
        self.assertEqual(sum(p.numel() for p in m.online.parameters()),19655)
        self.assertTrue(all(p.device.type=='cpu' and p.dtype==torch.float32 for p in m.online.parameters()))
        self.assertTrue(all(not p.requires_grad for p in m.target.parameters()))
        self.assertEqual(MODEL_SCHEMA,'warirak.navigation-history-double-dqn.v1')

    def test_02_double_target_masks_online_choice_and_uses_target_value(self):
        q=torch.tensor([[1.,4.,999.,3.,2.,1.,0.]])
        target=torch.tensor([[100.,2.,5000.,0.,0.,0.,0.]])
        mask=torch.tensor([[True,True,False,False,False,False,False]])
        out=masked_double_targets(torch.tensor([3.]),torch.tensor([False]),q,target,mask)
        self.assertAlmostEqual(out.item(),3.+.985*2,places=5)
        self.assertFalse(out.requires_grad)

    def test_03_terminal_target_never_bootstraps_even_without_next_mask(self):
        out=masked_double_targets(torch.tensor([-30.]),torch.tensor([True]),torch.full((1,7),999.),torch.full((1,7),999.),torch.zeros((1,7),dtype=torch.bool))
        self.assertEqual(out.item(),-30.)

    def test_04_nonterminal_empty_mask_nonfinite_and_bad_types_fail(self):
        args=[torch.tensor([0.]),torch.tensor([False]),torch.zeros((1,7)),torch.zeros((1,7)),torch.zeros((1,7),dtype=torch.bool)]
        with self.assertRaises(ValueError): masked_double_targets(*args)
        args[-1][:]=True;args[2][0,0]=torch.nan
        with self.assertRaises(ValueError): masked_double_targets(*args)
        args[2].zero_();args[-1]=torch.ones((1,7))
        with self.assertRaises(ValueError): masked_double_targets(*args)

    def test_05_exploration_and_greedy_cannot_choose_prohibited_requests(self):
        m=NavigationDQN(73,PROTOCOL)
        for eps in (0,1,.4):
            for _ in range(20):
                a=m.choose(REQUESTS[4],eps,now_ms=REQUESTS[4]['encoded_at_ms'])
                self.assertEqual(a,0)
        with self.assertRaises(ValueError):m.choose(REQUESTS[0],1.1,now_ms=REQUESTS[0]['encoded_at_ms'])

    def test_06_expired_and_future_inference_do_not_become_fresh(self):
        m=NavigationDQN(73,PROTOCOL);r=REQUESTS[0]
        for now in (r['encoded_at_ms']-1,r['valid_until_ms'],r['valid_until_ms']+300):
            with self.assertRaises(ValueError):m.choose(r,0,now_ms=now)
        self.assertEqual(m.choices,0)

    def test_07_transition_preserves_original_action_mask_and_reward_types(self):
        for field,value in [('action',7),('action',True),('action',6),('reward',float('nan')),('reward',True),('reward',1000),('terminal_reason','assistance')]:
            t=transition();t[field]=value
            with self.assertRaises(ValueError):validate_transition(t)
        t=transition();t['seed']=123
        with self.assertRaises(ValueError):validate_transition(t)

    def test_08_consecutive_original_clocks_and_records_required(self):
        for field in ('observation_at_ms','record_sequence'):
            t=transition();t['next_request'][field]+=1
            with self.assertRaises(ValueError):validate_transition(t)

    def test_09_epoch_clears_memory_without_erasing_nonterminal_drift_reward(self):
        t=transition(3);t['reward']=-10
        self.assertFalse(validate_transition(t)['terminal'])
        ring=ReplayRing();ring.append(t)
        self.assertEqual(ring.rewards[0].item(),-10.)
        self.assertFalse(ring.terminal[0].item())
        self.assertTrue((ring.next_states[0,:156]==0).all().item())
        bad=transition();bad['next_request']['stream_epoch']=1
        with self.assertRaises(ValueError):validate_transition(bad)

    def test_10_replay_ring_is_bounded_and_owns_copied_input(self):
        ring=ReplayRing();t=transition()
        ring.append(t);before=ring.states[0].clone();t['state_request']['vector'][0]=99
        self.assertTrue(torch.equal(ring.states[0],before))
        for _ in range(8192):ring.append(transition())
        self.assertEqual((ring.size,ring.position,ring.total_added),(8192,1,8193))

    def test_11_warmup_then_synthetic_gradient_is_finite_and_changes_online_only(self):
        m=NavigationDQN(73,PROTOCOL)
        self.assertIsNone(m.learn());populate(m)
        before=copy.deepcopy(m.online.state_dict());target=copy.deepcopy(m.target.state_dict())
        result=m.learn()
        self.assertTrue(result['loss']>=0);self.assertTrue(torch.isfinite(torch.tensor(result['gradient_norm'])))
        self.assertEqual(len(set(result['indices'])),64)
        self.assertTrue(any(not torch.equal(before[k],m.online.state_dict()[k]) for k in before))
        equal(self,target,m.target.state_dict())

    def test_12_target_sync_occurs_at_the_frozen_gradient_boundary(self):
        m=NavigationDQN(73,PROTOCOL);populate(m)
        # Artificial unit counter tests the boundary without launching250 training updates.
        m.updates=249;m.learn()
        equal(self,m.online.state_dict(),m.target.state_dict())

    def test_13_private_rng_initialization_and_sampling_do_not_advance_global_rng(self):
        t=torch.get_rng_state().clone();p=random.getstate()
        m=NavigationDQN(73,PROTOCOL);populate(m);m.learn();m.choose(REQUESTS[0],1,now_ms=REQUESTS[0]['encoded_at_ms'])
        self.assertTrue(torch.equal(t,torch.get_rng_state()));self.assertEqual(p,random.getstate())

    def test_14_safe_file_resume_is_bit_exact_for_rng_replay_adam_and_subsequent_updates(self):
        m=NavigationDQN(73,PROTOCOL);populate(m);m.learn();m.learn()
        with tempfile.TemporaryDirectory(prefix='warirak-dqn-unit-') as folder:
            path=Path(folder)/'unit-checkpoint.pt';digest=m.save(path,CURSOR)
            self.assertLess(path.stat().st_size,64*1048576)
            first=[]
            for _ in range(3):
                first.append((m.choose(REQUESTS[0],.8,now_ms=REQUESTS[0]['encoded_at_ms']),m.learn()))
            expected=m.checkpoint(CURSOR)
            resumed=NavigationDQN(73,PROTOCOL);resumed.load(path,expected_sha256=digest)
            second=[]
            for _ in range(3):
                second.append((resumed.choose(REQUESTS[0],.8,now_ms=REQUESTS[0]['encoded_at_ms']),resumed.learn()))
            self.assertEqual(first,second);equal(self,expected,resumed.checkpoint(CURSOR))

    def test_15_mismatched_identity_runtime_cursor_or_adam_cannot_partly_restore(self):
        m=NavigationDQN(73,PROTOCOL);populate(m);m.learn();original=m.checkpoint(CURSOR)
        for mutate in (lambda s:s.update(protocol_sha256='b'*64),lambda s:s.update(seed=True),lambda s:s['runtime'].update(torch='different'),lambda s:s['cursor'].update(phase='mid_episode'),lambda s:s['optimizer']['param_groups'][0].update(lr=1)):
            bad=copy.deepcopy(original);mutate(bad)
            with self.assertRaises(ValueError):m.restore(bad)
            equal(self,original,m.checkpoint(CURSOR))

    def test_16_wrong_file_hash_replay_corruption_and_pending_checkpoint_fail(self):
        m=NavigationDQN(73,PROTOCOL)
        with tempfile.TemporaryDirectory(prefix='warirak-dqn-unit-') as folder:
            path=Path(folder)/'unit.pt';digest=m.save(path,CURSOR)
            with self.assertRaises(ValueError):m.load(path,expected_sha256='0'*64)
            path.with_name('unit.pt.pending').write_text('preserve interrupted file')
            with self.assertRaises(ValueError):m.save(path,CURSOR)
        bad=m.replay.state();bad['total_added']=1
        with self.assertRaises(ValueError):m.replay.restore(bad)

    def test_17_seed_determinism_and_fixture_reply_are_explicit(self):
        a,b=NavigationDQN(73,PROTOCOL),NavigationDQN(73,PROTOCOL)
        self.assertEqual(a.q_values(REQUESTS[0],now_ms=REQUESTS[0]['encoded_at_ms']),b.q_values(REQUESTS[0],now_ms=REQUESTS[0]['encoded_at_ms']))
        reply=a.preflight_reply(REQUESTS[0],now_ms=REQUESTS[0]['encoded_at_ms'])
        self.assertEqual(reply['model_schema'],'warirak.navigation-validation-fixture.v1')
        self.assertFalse(reply['physical_motor_transport']);self.assertEqual(a.updates,0)

    def test_18_unchanged_original_vector_digest_is_required_before_float32_conversion(self):
        m=NavigationDQN(73,PROTOCOL);r=copy.deepcopy(REQUESTS[0]);r['vector'][-1]=.1
        self.assertNotEqual(vector_digest(r['vector']),r['vector_sha256'])
        with self.assertRaises(ValueError):m.q_values(r,now_ms=r['encoded_at_ms'])


if __name__=='__main__':unittest.main(verbosity=2)
