"""Runtime core software checks; one synthetic gradient, no R2 stepping here."""
import copy,json,tempfile,unittest
from pathlib import Path
from warirak_ai.navigation_runtime import LearningRuntime,load_runtime_protocol

ROOT=Path(__file__).resolve().parents[1]
PROTOCOL=ROOT/'work/navigation-runtime-preflight/protocol.json'
SYNTHETIC=json.loads((ROOT/'tests/fixtures/navigation-dqn-vectors.json').read_text(encoding='utf-8'))['requests'][0]
DURATION=json.loads((ROOT/'tests/fixtures/navigation-duration-credits.json').read_text(encoding='utf-8'))['cases'][0]['credit']

class TestNavigationRuntime(unittest.TestCase):
    def fixture(self):
        temp=tempfile.TemporaryDirectory(prefix='navigation-runtime-core-unit-',dir=ROOT/'work')
        self.addCleanup(temp.cleanup);p=Path(temp.name).resolve()
        assert p.parent==(ROOT/'work').resolve() and p.name.startswith('navigation-runtime-core-unit-')
        return LearningRuntime(PROTOCOL,p/'checkpoints','initialize'),p

    def first(self,runtime):
        r=copy.deepcopy(SYNTHETIC);r['session_id']='dn-'+runtime.protocol_sha256[:12]+'-000000';r['request_id']=r['session_id']+':inference:1'
        return r

    def test_01_update_schedule_uses_restored_replay_count_not_an_extra_counter(self):
        runtime,_=self.fixture()
        for _ in range(255):runtime.model.replay.append(DURATION)
        self.assertEqual(runtime.model.updates,0)
        result=runtime._consume_credit(DURATION)
        self.assertEqual(runtime.model.replay.total_added,256);self.assertEqual(result['updates'],1)

    def test_02_exact_begin_actor_and_synchronous_time_guards(self):
        runtime,_=self.fixture();r=self.first(runtime)
        runtime.begin(dict(seed=11500,profile='stress',fixture_used=True,first_request=r))
        with self.assertRaises(ValueError):runtime.act(dict(request=r,now_ms=r['encoded_at_ms']+1))
        result=runtime.act(dict(request=r,now_ms=r['encoded_at_ms']))
        self.assertEqual(result['epsilon'],runtime.config['epsilon_start'])
        self.assertTrue(r['allowed_mask'][result['reply']['action']]);self.assertFalse(result['production_ready'])
        with self.assertRaises(ValueError):runtime.act(dict(request=r,now_ms=r['encoded_at_ms']))

    def test_03_incomplete_episode_or_skipped_seed_cannot_commit(self):
        runtime,_=self.fixture();r=self.first(runtime)
        with self.assertRaises(ValueError):runtime.begin(dict(seed=11501,profile='stress',fixture_used=True,first_request=r))
        runtime.begin(dict(seed=11500,profile='stress',fixture_used=True,first_request=r))
        with self.assertRaises(ValueError):runtime.commit({})
        self.assertEqual(runtime.model.cursor['next_episode_index'],0)

    def test_04_incomplete_research_protocol_does_not_authorize_training(self):
        _,folder=self.fixture();p=json.loads(PROTOCOL.read_text(encoding='utf-8'))
        p.update(execution_scope='research_training',schema='warirak.navigation-training-protocol.v1',training_authorized=True)
        p['runtime_config']['fixture_policy']='generated_unmodified'
        file=folder/'not-an-approved-research-protocol.json';file.write_text(json.dumps(p))
        with self.assertRaises(ValueError):load_runtime_protocol(file)

    def test_05_source_hash_or_seed_profile_mismatch_fails_before_learning(self):
        runtime,folder=self.fixture();r=self.first(runtime)
        with self.assertRaises(ValueError):runtime.begin(dict(seed=11500,profile='nominal',fixture_used=True,first_request=r))
        p=json.loads(PROTOCOL.read_text(encoding='utf-8'));p['source_sha256']['ai/navigation_learning_runtime.mjs']='0'*64
        file=folder/'changed-source-protocol.json';file.write_text(json.dumps(p))
        with self.assertRaises(ValueError):load_runtime_protocol(file)

if __name__=='__main__':unittest.main(verbosity=2)
