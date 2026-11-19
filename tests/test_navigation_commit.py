"""New integration/commit SOFTWARE fixtures. No real training or held-out data."""
import contextlib
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import torch
from warirak_ai.navigation_dqn import NavigationDQN,ReplayRing,validate_transition
from warirak_ai.navigation_commit import EpisodeCommitStore

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'work/navigation-episode-preflight'
PROTOCOL=hashlib.sha256((RUN/'protocol.json').read_bytes()).hexdigest()
REQUESTS=json.loads((ROOT/'tests/fixtures/navigation-dqn-vectors.json').read_text(encoding='utf-8'))['requests']


def example(seed=11200):
    # Explicit storage fixture, not a measured episode/performance result.
    return dict(schema='warirak.navigation-r2-episode-result.v1',source='simulation',
        software_unit_example=True,seed=seed,done=True,steps=4,collections=0,collisions=1,timeouts=0,
        reward=-30.,reward_conservation_error=0.,credited_steps=4,passive_prefix_steps=0,pending_credit_steps=0,
        all_physical_steps_accounted=True,assistance_not_early_termination=True,physical_motor_transport=False)


def equal(test,a,b):
    test.assertEqual(type(a),type(b))
    if isinstance(a,torch.Tensor):test.assertTrue(torch.equal(a,b))
    elif isinstance(a,dict):
        test.assertEqual(set(a),set(b))
        for k in a:equal(test,a[k],b[k])
    elif isinstance(a,(list,tuple)):
        test.assertEqual(len(a),len(b))
        for x,y in zip(a,b):equal(test,x,y)
    else:test.assertEqual(a,b)


def add_synthetic_optimizer_state(m):
    t=dict(schema='warirak.navigation-history-transition.v1',source='simulation',
        plant_environment='warirak-pool-mission-v4r2-dev',episode_id='synthetic-commit-unit',
        state_request=REQUESTS[0],action=0,reward=.1,next_request=REQUESTS[1],terminal=False,terminal_reason='none')
    for _ in range(256):m.replay.append(t)
    m.learn()


@contextlib.contextmanager
def store_fixture(budget=3):
    # Verify the absolute target before TemporaryDirectory performs recursive cleanup.
    with tempfile.TemporaryDirectory(prefix='navigation-commit-unit-',dir=ROOT/'work') as folder:
        resolved=Path(folder).resolve()
        assert resolved.parent==(ROOT/'work').resolve() and resolved.name.startswith('navigation-commit-unit-')
        store=EpisodeCommitStore(resolved/'owned-store',PROTOCOL,11200,budget)
        model=NavigationDQN(73,PROTOCOL)
        yield store,model


class TestNavigationCommit(unittest.TestCase):
    def test_01_real_r2_one_step_examples_enter_frozen_replay_without_relabeling(self):
        data=json.loads((RUN/'bridge-transitions.json').read_text(encoding='utf-8'))
        self.assertTrue(data['software_unit_examples']);self.assertFalse(data['training_dataset'])
        ring=ReplayRing()
        epochs=0
        for t in data['one_step']:
            validate_transition(t);ring.append(t)
            epochs+=int(t['next_request']['stream_epoch']!=t['state_request']['stream_epoch'])
        self.assertGreaterEqual(ring.size,5);self.assertGreater(epochs,0)
        for t in data['duration']:
            self.assertGreater(t['duration_steps'],1)
            self.assertEqual(t['next_request']['observation_at_ms']-t['state_request']['observation_at_ms'],100*t['duration_steps'])
            self.assertAlmostEqual(t['continuation_discount'],.985**t['duration_steps'])
        self.assertTrue(data['duration'])

    def test_02_initialize_and_restore_select_the_same_next_seed_and_cursor(self):
        with store_fixture() as (s,m):
            s.initialize(m);restored=s.restore(m)
            self.assertEqual(restored['next_seed'],11200);self.assertEqual(m.cursor['environment_steps'],0)
            with self.assertRaises(ValueError):s.initialize(m)

    def test_03_successful_commits_prune_only_verified_old_generations_and_keep_two(self):
        with store_fixture() as (s,m):
            s.initialize(m)
            for i in range(3):
                s.commit(m,example(11200+i))
                restored=s.restore(m);self.assertEqual(restored['next_seed'],11201+i)
            self.assertEqual(m.cursor['environment_steps'],12)
            self.assertEqual(len(list(s.root.glob('g*'))),2)
            with self.assertRaises(ValueError):s.commit(m,example(11203))

    def test_04_pre_pointer_interruptions_roll_back_rng_replay_weights_and_adam(self):
        for stage in ('checkpoint_written','generation_written','before_pointer'):
            with self.subTest(stage=stage),store_fixture() as (s,m):
                add_synthetic_optimizer_state(m);s.initialize(m);original=m.checkpoint(m.cursor)
                m.choose(REQUESTS[0],1,now_ms=REQUESTS[0]['encoded_at_ms']);m.learn()
                with self.assertRaises(RuntimeError):s.commit(m,example(),failpoint=stage)
                self.assertGreaterEqual(len(list(s.root.glob('g*'))),2)
                with self.assertRaises(ValueError):s.commit(m,example())
                state=s.restore(m);self.assertEqual(state['next_seed'],11200)
                equal(self,original,m.checkpoint(m.cursor))
                s.commit(m,example());self.assertEqual(s.restore(m)['next_seed'],11201)

    def test_05_after_pointer_interruption_recovers_complete_new_generation(self):
        with store_fixture() as (s,m):
            add_synthetic_optimizer_state(m);s.initialize(m)
            m.learn();m.choose(REQUESTS[0],1,now_ms=REQUESTS[0]['encoded_at_ms'])
            cursor=dict(m.cursor,next_episode_index=1,environment_steps=4)
            expected=m.checkpoint(cursor)
            with self.assertRaises(RuntimeError):s.commit(m,example(),failpoint='after_pointer')
            state=s.restore(m);self.assertEqual(state['next_seed'],11201)
            equal(self,expected,m.checkpoint(m.cursor));self.assertEqual(state['committed_result']['seed'],11200)

    def test_06_skipped_seed_censored_outcome_pending_tail_and_nonfinite_result_fail(self):
        with store_fixture() as (s,m):
            s.initialize(m)
            for patch in ({'seed':11201},{'done':False},{'collisions':0},{'pending_credit_steps':1},
                          {'credited_steps':3},{'reward_conservation_error':float('nan')},{'reward':float('inf')}):
                with self.assertRaises(ValueError):s.commit(m,dict(example(),**patch))
            self.assertEqual(s.restore(m)['next_seed'],11200)

    def test_07_changed_checkpoint_hash_or_transaction_lock_is_never_loaded(self):
        with store_fixture() as (s,m):
            s.initialize(m);pointer=json.loads((s.root/'CURRENT.json').read_text())
            path=s.root/pointer['head']['directory']/'checkpoint.pt'
            with path.open('ab') as file:file.write(b'tamper')
            with self.assertRaises(ValueError):s.restore(m)
        with store_fixture() as (s,m):
            s.initialize(m);(s.root/'commit.lock').write_text('inspect owner process')
            with self.assertRaises(ValueError):s.restore(m)

    def test_08_orphans_are_preserved_and_never_silently_promoted(self):
        with store_fixture() as (s,m):
            s.initialize(m)
            for _ in range(2):
                with self.assertRaises(RuntimeError):s.commit(m,example(),failpoint='generation_written')
                self.assertEqual(s.restore(m)['next_seed'],11200)
            self.assertEqual(len(list(s.root.glob('g*'))),3)
            s.commit(m,example());self.assertEqual(s.restore(m)['next_seed'],11201)
            self.assertEqual(len(list(s.root.glob('g*'))),4)

    def test_09_store_paths_and_foreign_protocol_or_unknown_failpoint_are_rejected(self):
        with store_fixture() as (s,m):
            for name in ('../outside','C:/outside','g00000000-12345678/../../outside'):
                with self.assertRaises(ValueError):s._child(name)
            s.initialize(m)
            foreign=EpisodeCommitStore(s.root,'b'*64,11200,3)
            with self.assertRaises(ValueError):foreign.restore(m)
            with self.assertRaises(ValueError):s.commit(m,example(),failpoint='unknown')


if __name__=='__main__':unittest.main(verbosity=2)
