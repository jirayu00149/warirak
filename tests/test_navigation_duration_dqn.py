"""Duration learner SOFTWARE checks only. No R2 stepping or dataset training."""
import copy,hashlib,json,math
from pathlib import Path
import random,tempfile,unittest
import torch
from warirak_ai import navigation_dqn as base
from warirak_ai.navigation_duration_dqn import (DurationNavigationDQN,DurationReplayRing,
    validate_duration_credit,one_step_as_duration,masked_duration_targets,reward_bound,GAMMA,
    MODEL_SCHEMA,CHECKPOINT_SCHEMA)
from warirak_ai.navigation_wire import vector_digest
from warirak_ai.navigation_commit_journal import JournaledEpisodeCommitStore

ROOT=Path(__file__).resolve().parents[1]
DATA=json.loads((ROOT/'tests/fixtures/navigation-duration-credits.json').read_text(encoding='utf-8'))
CASES=[c['credit'] for c in DATA['cases']]
NATIVE_FILE=ROOT/'work/navigation-episode-preflight/bridge-transitions.json'
NATIVE=json.loads(NATIVE_FILE.read_text(encoding='utf-8'))
PROTOCOL='d'*64
CURSOR=dict(schema='warirak.navigation-episode-cursor.v1',phase='between_episodes',next_episode_index=0,environment_steps=0)

def populate(m):
    for i in range(256):m.replay.append(CASES[i%len(CASES)])

def equal(test,a,b):
    test.assertEqual(type(a),type(b))
    if isinstance(a,torch.Tensor):test.assertTrue(torch.equal(a,b));test.assertEqual(a.dtype,b.dtype)
    elif isinstance(a,dict):
        test.assertEqual(set(a),set(b))
        for k in a:equal(test,a[k],b[k])
    elif isinstance(a,(list,tuple)):
        test.assertEqual(len(a),len(b))
        for x,y in zip(a,b):equal(test,x,y)
    else:test.assertEqual(a,b)

def scratch():return tempfile.TemporaryDirectory(prefix='duration-dqn-unit-',dir=ROOT/'work')
def verify_folder(name):
    p=Path(name).resolve();assert p.parent==(ROOT/'work').resolve() and p.name.startswith('duration-dqn-unit-');return p

class TestNavigationDurationDQN(unittest.TestCase):
    def test_01_saved_real_bridge_credits_enter_without_changing_original_packets(self):
        before=hashlib.sha256(NATIVE_FILE.read_bytes()).hexdigest();ring=DurationReplayRing()
        for t in NATIVE['one_step']:ring.append(one_step_as_duration(t))
        for t in NATIVE['duration']:ring.append(t)
        self.assertGreater(ring.size,5);self.assertEqual(ring.durations[ring.size-1].item(),2)
        self.assertEqual(ring.discounts.dtype,torch.float64)
        self.assertEqual(hashlib.sha256(NATIVE_FILE.read_bytes()).hexdigest(),before)

    def test_02_variable_targets_mask_online_argmax_and_use_original_time_discount(self):
        q=torch.tensor([[1.,4.,999.,0.,0.,0.,0.]]*3)
        target=torch.tensor([[100.,2.,5000.,0.,0.,0.,0.]]*3)
        mask=torch.tensor([[True,True,False,False,False,False,False]]*3)
        discounts=torch.tensor([GAMMA,GAMMA**2,GAMMA**960],dtype=torch.float64)
        out=masked_duration_targets(torch.tensor([3.,3.,3.]),torch.tensor([False]*3),q,target,mask,discounts)
        expected=3+discounts.float()*2
        self.assertTrue(torch.equal(out,expected));self.assertEqual(out.dtype,torch.float32);self.assertFalse(out.requires_grad)

    def test_03_natural_terminal_has_no_bootstrap_and_assistance_is_not_terminal(self):
        out=masked_duration_targets(torch.tensor([-30.]),torch.tensor([True]),torch.full((1,7),999.),torch.full((1,7),999.),torch.zeros((1,7),dtype=torch.bool),torch.tensor([.7]))
        self.assertEqual(out.item(),-30.)
        c=copy.deepcopy(CASES[0]);c.update(terminal=True,terminal_reason='assistance')
        with self.assertRaises(ValueError):validate_duration_credit(c)

    def test_04_long_credit_above64_is_preserved_not_clipped(self):
        c=CASES[3];self.assertGreater(c['reward'],64);ring=DurationReplayRing();ring.append(c)
        self.assertEqual(ring.rewards[0].item(),100.);self.assertEqual(ring.raw_rewards[0].item(),500.)
        self.assertEqual(ring.next_observation_at_ms[0]-ring.state_observation_at_ms[0],96000)

    def test_05_invalid_duration_discount_reward_null_or_operator_action_rejected(self):
        for patch in ({'duration_steps':0},{'duration_steps':961},{'duration_steps':True},{'continuation_discount':.5},
            {'reward':float('nan')},{'reward':1e9},{'undiscounted_reward':1e9},{'action':None},{'action':7},{'action':True},{'physical_motor_transport':True},{'seed':123}):
            with self.assertRaises(ValueError):validate_duration_credit(dict(copy.deepcopy(CASES[0]),**patch))

    def test_06_original_clock_and_record_duration_must_match_without_retiming(self):
        for field in ('record_sequence','observation_at_ms','encoded_at_ms'):
            c=copy.deepcopy(CASES[0]);c['next_request'][field]+=1
            with self.assertRaises(ValueError):validate_duration_credit(c)

    def test_07_new_epoch_can_accumulate_its_own_frames_but_not_starting_epoch_frames(self):
        self.assertTrue(any(CASES[2]['next_request']['vector'][:156]));validate_duration_credit(CASES[2])
        c=copy.deepcopy(CASES[1]);n=c['next_request'];n['vector'][79]=2/3
        n['vector_sha256']=vector_digest(n['vector'])
        with self.assertRaises(ValueError):validate_duration_credit(c)

    def test_08_ring_is_bounded_and_owns_input_and_original_metadata(self):
        r=DurationReplayRing();c=copy.deepcopy(CASES[0]);r.append(c);original=r.states[0].clone()
        c['state_request']['vector'][0]=99;self.assertTrue(torch.equal(original,r.states[0]))
        for i in range(8192):r.append(CASES[i%4])
        self.assertEqual((r.size,r.position,r.total_added),(8192,1,8193));self.assertEqual(r.durations[0].item(),960)

    def test_09_replay_restore_rejects_corrupt_discount_clock_reason_or_shape_atomically(self):
        r=DurationReplayRing();r.append(CASES[0]);good=r.state()
        for key,value in [('discounts',.7),('durations',0),('next_observation_at_ms',1),('reasons',3),('raw_rewards',1e9)]:
            bad=copy.deepcopy(good);bad[key][0]=value
            with self.assertRaises(ValueError):r.restore(bad)
            equal(self,good,r.state())

    def test_10_warmup_and_finite_variable_duration_gradient(self):
        m=DurationNavigationDQN(73,PROTOCOL);self.assertIsNone(m.learn());populate(m)
        old=copy.deepcopy(m.online.state_dict());target=copy.deepcopy(m.target.state_dict());result=m.learn()
        self.assertTrue(math.isfinite(result['loss']));self.assertEqual(len(set(result['indices'])),64)
        self.assertTrue(any(not torch.equal(old[k],m.online.state_dict()[k]) for k in old));equal(self,target,m.target.state_dict())

    def test_11_target_sync_at_frozen_gradient_boundary_uses_duration_network(self):
        m=DurationNavigationDQN(73,PROTOCOL);populate(m);m.updates=249;m.learn()
        equal(self,m.online.state_dict(),m.target.state_dict())

    def test_12_private_rng_paths_do_not_advance_caller_rng(self):
        t=torch.get_rng_state().clone();p=random.getstate();m=DurationNavigationDQN(73,PROTOCOL);populate(m);m.learn()
        r=CASES[0]['state_request'];m.choose(r,1,now_ms=r['encoded_at_ms'])
        self.assertTrue(torch.equal(t,torch.get_rng_state()));self.assertEqual(p,random.getstate())

    def test_13_safe_file_resume_is_exact_for_three_variable_duration_updates_and_choices(self):
        m=DurationNavigationDQN(73,PROTOCOL);populate(m);m.learn();m.learn();r=CASES[0]['state_request']
        with scratch() as name:
            folder=verify_folder(name);path=folder/'duration.pt';digest=m.save(path,CURSOR)
            first=[(m.choose(r,.8,now_ms=r['encoded_at_ms']),m.learn()) for _ in range(3)]
            expected=m.checkpoint(CURSOR)
            resumed=DurationNavigationDQN(73,PROTOCOL);resumed.load(path,expected_sha256=digest)
            second=[(resumed.choose(r,.8,now_ms=r['encoded_at_ms']),resumed.learn()) for _ in range(3)]
            self.assertEqual(first,second);equal(self,expected,resumed.checkpoint(CURSOR))
            self.assertEqual(expected['schema'],CHECKPOINT_SCHEMA);self.assertEqual(expected['model_schema'],MODEL_SCHEMA)

    def test_14_one_step_and_duration_checkpoints_cannot_be_confused(self):
        a=base.NavigationDQN(73,PROTOCOL);b=DurationNavigationDQN(73,PROTOCOL)
        with self.assertRaises(ValueError):a.restore(b.checkpoint(CURSOR))
        with self.assertRaises(ValueError):b.restore(a.checkpoint(CURSOR))

    def test_15_journal_store_accepts_new_identity_and_restores_duration_replay(self):
        m=DurationNavigationDQN(73,PROTOCOL);populate(m);m.learn()
        with scratch() as name:
            folder=verify_folder(name);s=JournaledEpisodeCommitStore(folder/'store',PROTOCOL,11400,1);s.initialize(m)
            result=dict(schema='warirak.navigation-r2-episode-result.v1',source='simulation',software_unit_example=True,seed=11400,done=True,steps=4,collections=0,collisions=1,timeouts=0,reward=-30.,reward_conservation_error=0.,credited_steps=4,passive_prefix_steps=0,pending_credit_steps=0,all_physical_steps_accounted=True,assistance_not_early_termination=True,physical_motor_transport=False)
            s.commit(m,result);expected=m.checkpoint(m.cursor)
            other=DurationNavigationDQN(73,PROTOCOL);self.assertEqual(s.restore(other)['next_seed'],11401)
            equal(self,expected,other.checkpoint(other.cursor))

    def test_16_failed_checkpoint_identity_or_optimizer_restore_leaves_state_intact(self):
        m=DurationNavigationDQN(73,PROTOCOL);populate(m);m.learn();original=m.checkpoint(CURSOR)
        for mutate in (lambda s:s.update(base_recipe_sha256='0'*64),lambda s:s.update(recipe_sha256='0'*64),lambda s:s['optimizer']['param_groups'][0].update(lr=1)):
            bad=copy.deepcopy(original);mutate(bad)
            with self.assertRaises(ValueError):m.restore(bad)
            equal(self,original,m.checkpoint(CURSOR))

    def test_17_bad_target_mask_discount_dtype_or_nonfinite_values_fail(self):
        args=[torch.zeros(1),torch.tensor([False]),torch.zeros((1,7)),torch.zeros((1,7)),torch.ones((1,7),dtype=torch.bool),torch.tensor([.9])]
        for i,value in [(4,torch.zeros((1,7),dtype=torch.bool)),(5,torch.tensor([2.])),(5,torch.tensor([float('nan')])),(1,torch.zeros(1))]:
            a=list(args);a[i]=value
            with self.assertRaises(ValueError):masked_duration_targets(*a)

    def test_18_geometric_reward_bound_matches_duration_and_current_frame_age_is_not_faked(self):
        self.assertAlmostEqual(reward_bound(1),64.);self.assertGreater(reward_bound(960),4000)
        c=copy.deepcopy(CASES[3]);c['reward']=reward_bound(960)+1
        with self.assertRaises(ValueError):validate_duration_credit(c)
        c=copy.deepcopy(CASES[0]);n=c['next_request'];n['vector'][157]=.1;n['vector_sha256']=vector_digest(n['vector'])
        with self.assertRaises(ValueError):validate_duration_credit(c)

if __name__=='__main__':unittest.main(verbosity=2)
