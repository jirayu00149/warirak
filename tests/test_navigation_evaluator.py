"""Read-only evaluator software guards. No R2 cases or held-out data."""
import copy,hashlib,importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
import torch
from warirak_ai.navigation_evaluator import ReadOnlySnapshot,evaluation_partition
ROOT=Path(__file__).resolve().parents[1]
_spec=importlib.util.spec_from_file_location('evaluation_unit_snapshot',ROOT/'work/create_evaluation_unit_snapshot.py')
_helper=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_helper);create=_helper.create
PROTOCOL=ROOT/'work/navigation-evaluation-preflight/protocol.json'
REQUESTS=json.loads((ROOT/'tests/fixtures/navigation-dqn-vectors.json').read_text(encoding='utf-8'))['requests']

class TestNavigationEvaluator(unittest.TestCase):
    def fixture(self,optimizer=False):
        temp=tempfile.TemporaryDirectory(prefix='navigation-evaluator-core-unit-',dir=ROOT/'work');self.addCleanup(temp.cleanup)
        root=Path(temp.name).resolve();assert root.parent==(ROOT/'work').resolve() and root.name.startswith('navigation-evaluator-core-unit-')
        info=create(PROTOCOL,root/'snapshot',optimizer);return root,info

    def test_01_greedy_prediction_preserves_full_nonempty_learner_and_original_files(self):
        folder,info=self.fixture(True);view=ReadOnlySnapshot(PROTOCOL,info['snapshot_path'],info['snapshot_sha256'],'software')
        before=(view.checkpoint.stat().st_mtime_ns,view.meta_file.stat().st_mtime_ns)
        for _ in range(5):
            for r in REQUESTS:
                p=view.predict(r,r['encoded_at_ms']);self.assertTrue(r['allowed_mask'][p['action']]);self.assertFalse(p['physical_motor_transport'])
        checked=view.verify();self.assertEqual(checked['before_state_sha256'],info['initial_state_sha256']);self.assertEqual(checked['before_state_sha256'],checked['after_state_sha256'])
        self.assertEqual(checked['choices'],0);self.assertEqual(checked['updates'],1)
        self.assertEqual(before,(view.checkpoint.stat().st_mtime_ns,view.meta_file.stat().st_mtime_ns))

    def test_02_changed_manifest_or_unplanned_episode_rejected(self):
        _,info=self.fixture();folder=Path(info['snapshot_path'])
        with self.assertRaises(ValueError):ReadOnlySnapshot(PROTOCOL,folder,'0'*64,'software')
        m=json.loads((folder/'snapshot.json').read_text());m['episode']=2;(folder/'snapshot.json').write_text(json.dumps(m))
        checksum=hashlib.sha256((folder/'snapshot.json').read_bytes()).hexdigest()
        with self.assertRaises(ValueError):ReadOnlySnapshot(PROTOCOL,folder,checksum,'software')

    def test_03_source_file_tampering_detected_after_predictions(self):
        _,info=self.fixture();view=ReadOnlySnapshot(PROTOCOL,info['snapshot_path'],info['snapshot_sha256'],'software')
        with view.checkpoint.open('ab') as file:file.write(b'unit-tamper')
        with self.assertRaises(ValueError):view.verify()

    def test_04_hidden_in_memory_weight_change_cannot_pass_read_only_receipt(self):
        _,info=self.fixture();view=ReadOnlySnapshot(PROTOCOL,info['snapshot_path'],info['snapshot_sha256'],'software')
        with torch.no_grad():view.model.online.layers[0].weight[0,0]+=.1
        with self.assertRaises(ValueError):view.verify(False)

    def test_05_test_partition_is_closed_by_default_without_constructing_any_world(self):
        p=json.loads(PROTOCOL.read_text(encoding='utf-8'));p['execution_scope']='research_training'
        with self.assertRaisesRegex(ValueError,'Test is closed'):evaluation_partition(p,'a'*64,'test','b'*64)
        with self.assertRaises(ValueError):evaluation_partition(p,'a'*64,'software','b'*64)

    def test_06_review_cannot_promote_a_rejected_validation_selection(self):
        root,_=self.fixture();p=json.loads(PROTOCOL.read_text(encoding='utf-8'));p['execution_scope']='research_training'
        selection=root/'selection.json';selection.write_text(json.dumps(dict(schema='warirak.navigation-snapshot-selection.v1',protocol_sha256='a'*64,partition='validation',test_opened=False,status='retained_baseline',selected=None)))
        review=root/'review.json';review.write_text(json.dumps(dict(schema='warirak.navigation-test-authorization.v1',protocol_sha256='a'*64,snapshot_sha256='b'*64,engineering_review_complete=True,open_test=True,test_used_for_selection=False,selection_path=str(selection),selection_sha256=hashlib.sha256(selection.read_bytes()).hexdigest())))
        with self.assertRaises(ValueError):evaluation_partition(p,'a'*64,'test','b'*64,review)

    def test_07_rpc_does_not_expose_learn_or_commit(self):
        _,info=self.fixture()
        message=dict(schema='warirak.navigation-evaluation-rpc.v1',id=1,method='learn',params={})
        import os
        r=subprocess.run([sys.executable,'-X','utf8','-m','warirak_ai.navigation_evaluator','--protocol',str(PROTOCOL),'--snapshot',info['snapshot_path'],'--expected-snapshot-sha256',info['snapshot_sha256'],'--partition','software'],input=json.dumps(message)+'\n',text=True,capture_output=True,encoding='utf-8',env=dict(os.environ,PYTHONPATH=str(ROOT/'ai')),timeout=30)
        self.assertEqual(r.returncode,2);self.assertFalse(json.loads(r.stdout)['ok'])
        self.assertEqual(hashlib.sha256((Path(info['snapshot_path'])/'checkpoint.pt').read_bytes()).hexdigest(),info['checkpoint_sha256'])

if __name__=='__main__':unittest.main(verbosity=2)
