"""Read-only snapshot prediction. No training, replay append, commit or hardware RPC."""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
import sys
from .navigation_runtime import load_runtime_protocol,state_fingerprint,sha
from .navigation_duration_dqn import DurationNavigationDQN,MODEL_SCHEMA
from .navigation_wire import decode_json,validate_request

RPC='warirak.navigation-evaluation-rpc.v1'
ROOT=Path(__file__).resolve().parents[2]
_REPLY_KEYS=['source','plant_environment','encoder_schema','layout_sha256','session_id','request_id','stream_epoch','record_sequence','observation_at_ms','valid_until_ms','vector_sha256','control_enabled','physical_motor_transport']


def evaluation_partition(protocol,protocol_sha,partition,snapshot_sha,authorization=None):
    if partition=='software':
        if protocol['execution_scope']!='software_preflight':raise ValueError('Software cases require software scope')
        return protocol['software_evaluation']
    if protocol['execution_scope']!='research_training' or partition not in ('validation','test'):
        raise ValueError('Frozen research validation or separately reviewed test required')
    if protocol['selection']['test_used_for_selection'] is not False:raise ValueError('Validation-only selection required')
    if partition=='test':
        if authorization is None:raise ValueError('Test is closed until explicit engineering review')
        review=decode_json(Path(authorization).read_bytes())
        if (review.get('schema')!='warirak.navigation-test-authorization.v1' or review.get('protocol_sha256')!=protocol_sha or
            review.get('snapshot_sha256')!=snapshot_sha or review.get('engineering_review_complete') is not True or
            review.get('open_test') is not True or review.get('test_used_for_selection') is not False):raise ValueError('Invalid reviewed test authorization')
        selection_path=Path(review['selection_path']).resolve()
        if not selection_path.is_relative_to(ROOT) or sha(selection_path)!=review['selection_sha256']:raise ValueError('Frozen selection hash mismatch')
        selected=decode_json(selection_path.read_bytes())
        if (selected.get('schema')!='warirak.navigation-snapshot-selection.v1' or selected.get('protocol_sha256')!=protocol_sha or
            selected.get('partition')!='validation' or selected.get('test_opened') is not False or
            selected.get('status')!='candidate_ready_for_review' or selected.get('selected',{}).get('snapshot_sha256')!=snapshot_sha):
            raise ValueError('Test cannot select or replace the validation choice')
    return protocol[partition]


class ReadOnlySnapshot:
    def __init__(self,protocol_path,snapshot_path,expected_snapshot_sha256,partition,authorization=None):
        self.protocol,self.config,self.protocol_sha256=load_runtime_protocol(protocol_path)
        self.folder=Path(snapshot_path).resolve();self.meta_file=self.folder/'snapshot.json';self.checkpoint=self.folder/'checkpoint.pt'
        if not self.folder.is_relative_to(ROOT) or self.meta_file.is_symlink() or self.checkpoint.is_symlink():raise ValueError('Owned immutable local snapshot required')
        if sha(self.meta_file)!=expected_snapshot_sha256:raise ValueError('Snapshot manifest hash mismatch')
        self.snapshot_sha256=expected_snapshot_sha256
        self.partition=partition;self.range=evaluation_partition(self.protocol,self.protocol_sha256,partition,expected_snapshot_sha256,authorization)
        m=decode_json(self.meta_file.read_bytes());self.metadata=m
        if (m.get('schema')!='warirak.navigation-model-snapshot.v1' or m.get('protocol_sha256')!=self.protocol_sha256 or
            type(m.get('episode')) is not int or m['episode'] not in self.config['snapshot_episodes'] or
            m.get('model_schema')!=MODEL_SCHEMA or m.get('production_ready') is not False or
            type(m.get('actual_training')) is not bool or m['actual_training']!=(self.protocol['execution_scope']=='research_training')):
            raise ValueError('Snapshot protocol/model/planned episode identity mismatch')
        if self.protocol['execution_scope']=='research_training':
            run=self.folder.parent.parent;identity=decode_json((run/'run-identity.json').read_bytes());status=decode_json((run/'status.json').read_bytes())
            if identity.get('protocol_sha256')!=self.protocol_sha256 or status.get('phase')!='training_complete_needs_validation_review':
                raise ValueError('Wait for the healthy training job to finish before evaluation')
        self.model=DurationNavigationDQN(self.config['model_seed'],self.protocol_sha256)
        self.model.load(self.checkpoint,expected_sha256=m['checkpoint_sha256'])
        if self.model.cursor!=m['cursor'] or self.model.cursor['next_episode_index']!=m['episode']:raise ValueError('Snapshot cursor mismatch')
        self.model.online.eval();self.model.target.eval()
        self.before=state_fingerprint(self.model.checkpoint(self.model.cursor));self.predictions=0

    def predict(self,request,now_ms):
        validate_request(request,now_ms=now_ms)
        values=self.model.q_values(request,now_ms=now_ms)
        allowed=[i for i,ok in enumerate(request['allowed_mask']) if ok]
        action=max(allowed,key=lambda i:values[i])
        self.predictions+=1
        result={k:request[k] for k in _REPLY_KEYS}
        result.update(schema='warirak.navigation-inference-reply.v1',model_schema=MODEL_SCHEMA,action=action)
        return result

    def verify(self,recheck_files=True):
        after=state_fingerprint(self.model.checkpoint(self.model.cursor))
        if after!=self.before or recheck_files and (sha(self.meta_file)!=self.snapshot_sha256 or sha(self.checkpoint)!=self.metadata['checkpoint_sha256']):
            raise ValueError('Read-only evaluation changed learner or immutable snapshot')
        return dict(read_only_verified=True,before_state_sha256=self.before,after_state_sha256=after,
            snapshot_sha256=self.snapshot_sha256,checkpoint_sha256=self.metadata['checkpoint_sha256'],
            snapshot_episode=self.metadata['episode'],predictions=self.predictions,source_files_rechecked=recheck_files,choices=self.model.choices,
            updates=self.model.updates,partition=self.partition,actual_training=self.metadata['actual_training'],physical_motor_transport=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol',required=True);parser.add_argument('--snapshot',required=True)
    parser.add_argument('--expected-snapshot-sha256',required=True);parser.add_argument('--partition',choices=('software','validation','test'),required=True)
    parser.add_argument('--authorization');a=parser.parse_args()
    view=ReadOnlySnapshot(a.protocol,a.snapshot,a.expected_snapshot_sha256,a.partition,a.authorization)
    n=view.range['episodes_per_profile'];maximum=n*2*(960+1)+16
    for expected_id in range(1,maximum+1):
        line=sys.stdin.buffer.readline(65537)
        if not line:return
        try:
            msg=decode_json(line)
            if type(msg) is not dict or set(msg)!={'schema','id','method','params'} or msg['schema']!=RPC or type(msg['id']) is not int or msg['id']!=expected_id or type(msg['params']) is not dict:raise ValueError('Ordered bounded evaluation RPC required')
            method,params=msg['method'],msg['params']
            if method=='predict' and set(params)=={'request','now_ms'}:value=dict(reply=view.predict(params['request'],params['now_ms']))
            elif method in ('verify','verify_case','shutdown') and not params:value=view.verify(recheck_files=method!='verify_case')
            else:raise ValueError('Read-only RPC exposes no learning/commit method')
            print(json.dumps(dict(schema=RPC,id=expected_id,ok=True,result=value),allow_nan=False),flush=True)
            if method=='shutdown':return
        except (ValueError,TypeError,KeyError,RuntimeError) as error:
            print(json.dumps(dict(schema=RPC,id=expected_id,ok=False,error=str(error)[:1500]),allow_nan=False),flush=True)
            raise SystemExit(2)
    raise RuntimeError('Frozen evaluation message budget exceeded')

if __name__=='__main__':main()
