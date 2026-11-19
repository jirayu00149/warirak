"""Additive journal checks only. Earlier20 episode/store tests are not rerun."""
import contextlib
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from warirak_ai.navigation_dqn import NavigationDQN
from warirak_ai.navigation_commit import EpisodeCommitStore
from warirak_ai.navigation_commit_journal import JournaledEpisodeCommitStore

ROOT=Path(__file__).resolve().parents[1]
PROTOCOL=hashlib.sha256((ROOT/'work/navigation-episode-journal-preflight/protocol.json').read_bytes()).hexdigest()

def example(seed):return dict(schema='warirak.navigation-r2-episode-result.v1',source='simulation',software_unit_example=True,seed=seed,done=True,steps=4,collections=0,collisions=1,timeouts=0,reward=-30.,reward_conservation_error=0.,credited_steps=4,passive_prefix_steps=0,pending_credit_steps=0,all_physical_steps_accounted=True,assistance_not_early_termination=True,physical_motor_transport=False)

@contextlib.contextmanager
def fixture():
    with tempfile.TemporaryDirectory(prefix='navigation-journal-unit-',dir=ROOT/'work') as name:
        root=Path(name).resolve()
        assert root.parent==(ROOT/'work').resolve() and root.name.startswith('navigation-journal-unit-')
        yield root,NavigationDQN(73,PROTOCOL)

class TestNavigationCommitJournal(unittest.TestCase):
    def test_01_all_five_outcomes_survive_two_generation_checkpoint_retention(self):
        with fixture() as (root,m):
            s=JournaledEpisodeCommitStore(root/'store',PROTOCOL,11300,5);s.initialize(m)
            for i in range(5):s.commit(m,example(11300+i))
            self.assertEqual(len(list(s.root.glob('g*'))),2)
            self.assertEqual(len(list((s.root/'outcomes').glob('*.json'))),5)
            restored=JournaledEpisodeCommitStore(s.root,PROTOCOL,11300,5)
            self.assertEqual(restored.restore(m)['next_seed'],11305)
            self.assertEqual(restored._journal_count,5)

    def test_02_before_and_after_pointer_interruptions_archive_only_committed_head(self):
        for stage in ('before_pointer','after_pointer'):
            with self.subTest(stage=stage),fixture() as (root,m):
                s=JournaledEpisodeCommitStore(root/'store',PROTOCOL,11300,2);s.initialize(m)
                with self.assertRaises(RuntimeError):s.commit(m,example(11300),failpoint=stage)
                resumed=JournaledEpisodeCommitStore(s.root,PROTOCOL,11300,2)
                state=resumed.restore(m)
                self.assertEqual(state['next_seed'],11300+(stage=='after_pointer'))
                self.assertEqual(resumed._journal_count,int(stage=='after_pointer'))

    def test_03_tampered_or_missing_old_outcome_is_rejected_before_checkpoint_pruning(self):
        with fixture() as (root,m):
            s=JournaledEpisodeCommitStore(root/'store',PROTOCOL,11300,3);s.initialize(m)
            s.commit(m,example(11300));s.commit(m,example(11301))
            receipt=s.root/'outcomes/episode-00000000.json';data=json.loads(receipt.read_text())
            data['result']['collisions']=0;receipt.write_text(json.dumps(data))
            with self.assertRaises(ValueError):s.restore(m)
            self.assertIsNone(s.token)

    def test_04_budget_foreign_unjournaled_history_and_future_receipts_are_not_accepted(self):
        with fixture() as (root,m):
            s=JournaledEpisodeCommitStore(root/'store',PROTOCOL,11300,2);s.initialize(m)
            s.MAXIMUM_JOURNAL_BYTES=1
            with self.assertRaises(ValueError):s.commit(m,example(11300))
            self.assertEqual(s._head()[1]['cursor']['next_episode_index'],0)
        with fixture() as (root,m):
            old=EpisodeCommitStore(root/'store',PROTOCOL,11300,2);old.initialize(m);old.commit(m,example(11300))
            upgraded=JournaledEpisodeCommitStore(old.root,PROTOCOL,11300,2)
            with self.assertRaises(ValueError):upgraded.restore(m)
        with fixture() as (root,m):
            s=JournaledEpisodeCommitStore(root/'store',PROTOCOL,11300,2);s.initialize(m)
            (s.root/'outcomes/episode-00000000.json').write_text('{}')
            with self.assertRaises(ValueError):s.restore(m)

if __name__=='__main__':unittest.main(verbosity=2)
