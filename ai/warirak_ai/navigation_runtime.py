"""Versioned local simulation learning RPC. No network or physical actuator transport."""
from __future__ import annotations
import argparse,copy,hashlib,json,math,os,shutil,uuid
from pathlib import Path
import struct,sys
import torch
from .navigation_duration_dqn import DurationNavigationDQN,MODEL_SCHEMA,validate_duration_credit
from .navigation_commit_journal import JournaledEpisodeCommitStore
from .navigation_wire import decode_json,validate_request

ROOT=Path(__file__).resolve().parents[2]
_FIELDS=json.loads((ROOT/'ai/navigation-history-layout.json').read_bytes())['field_order']
_ASSIST_INDICES=[156+_FIELDS.index('mission.'+mode) for mode in ('FAULT_STOP','HOLD_UNAVAILABLE','RECOVERY_REQUIRED','ACTUATION_UNAVAILABLE','PROGRESS_UNCERTAIN')]
RPC='warirak.navigation-learning-rpc.v1'
_ACTIONS=['STOP','FORWARD','TURN_LEFT','TURN_RIGHT','PIVOT_LEFT','PIVOT_RIGHT','HOLD']
_REPLY_KEYS=['source','plant_environment','encoder_schema','layout_sha256','session_id','request_id','stream_epoch','record_sequence','observation_at_ms','valid_until_ms','vector_sha256','control_enabled','physical_motor_transport']
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def uint(v):return type(v) is int and 0<=v<=9007199254740991
def finite(v):return type(v) in (int,float) and math.isfinite(v)
def canonical(v):return json.dumps(v,sort_keys=True,allow_nan=False)


def load_runtime_protocol(path):
    path=Path(path).resolve();p=decode_json(path.read_bytes());c=p['runtime_config']
    scope=p.get('execution_scope')
    if scope not in ('software_preflight','research_training') or c.get('schema')!='warirak.navigation-runtime-config.v1':raise ValueError('Explicit simulation runtime scope/config required')
    required={'ai/warirak_ai/navigation_runtime.py','ai/navigation_learning_runtime.mjs','ai/navigation_episode_bridge.mjs','ai/warirak_ai/navigation_duration_dqn.py','ai/warirak_ai/navigation_commit_journal.py'}
    if not required.issubset(p['source_sha256']):raise ValueError('Complete runtime source manifest required')
    for f,digest in p['source_sha256'].items():
        target=(ROOT/f).resolve()
        if not target.is_relative_to(ROOT) or sha(target)!=digest:raise ValueError('Frozen runtime source mismatch:'+f)
    if (not uint(c.get('scene_seed')) or not uint(c.get('episodes')) or not 1<=c['episodes']<=100000 or c['scene_seed']+c['episodes']>2147483647 or
        not uint(c.get('model_seed')) or c['model_seed']>2147483647 or not uint(c.get('update_every_credits')) or not 1<=c['update_every_credits']<=64 or
        not uint(c.get('epsilon_decay_choices')) or c['epsilon_decay_choices']<1 or
        not all(finite(c.get(k)) for k in ('epsilon_start','epsilon_floor')) or not 0<=c['epsilon_floor']<=c['epsilon_start']<=1 or
        not isinstance(c.get('profiles'),list) or not c['profiles'] or len(c['profiles'])>16 or any(x not in ('nominal','stress') for x in c['profiles']) or
        c.get('physical_motor_transport') is not False or c.get('max_steps')!=960 or not uint(c.get('minimum_free_disk_mib')) or c['minimum_free_disk_mib']<512 or
        type(c.get('snapshot_episodes')) is not list or len(c['snapshot_episodes'])>4 or c['snapshot_episodes']!=sorted(set(c['snapshot_episodes'])) or any(not uint(i) or not 1<=i<=c['episodes'] for i in c['snapshot_episodes'])):raise ValueError('Invalid bounded runtime recipe')
    if scope=='research_training':
        if (p.get('schema')!='warirak.navigation-training-protocol.v1' or p.get('training_authorized') is not True or
            c.get('fixture_policy')!='generated_unmodified' or any(k.startswith('software_') for k in c) or not all(k in p for k in ('training','validation','test','selection','preflight_evidence'))):raise ValueError('Complete research protocol and gates required before training')
        if p['training']!={'seed':c['scene_seed'],'episodes':c['episodes']} or p['selection'].get('test_used_for_selection') is not False:raise ValueError('Declared training range/validation-only selection required')
        ranges=[(c['scene_seed'],c['episodes'])]+[(p[g][profile+'_seed'],p[g]['episodes_per_profile']) for g in ('validation','test') for profile in ('nominal','stress')]
        if any(not uint(s) or not uint(n) or n<1 or s+n>2147483647 for s,n in ranges) or any(s<=t+m-1 and s+n-1>=t for i,(s,n) in enumerate(ranges) for t,m in ranges[i+1:]):raise ValueError('Overlapping training/validation/test ranges')
        evidence=p['preflight_evidence'];f=(ROOT/evidence['path']).resolve()
        if not f.is_relative_to(ROOT) or sha(f)!=evidence['sha256']:raise ValueError('Runtime preflight evidence mismatch')
        audit=json.loads(f.read_text(encoding='utf-8'))
        if not audit.get('review_complete') or not audit.get('delivery_complete') or not audit.get('training_runtime_integration_complete'):raise ValueError('Reviewed runtime preflight required')
    elif c.get('fixture_policy')!='analytic_bank_four_steps':raise ValueError('Declared bounded software fixture required')
    return p,c,sha(path)


def state_fingerprint(value):
    h=hashlib.sha256()
    def add(v):
        h.update(type(v).__name__.encode()+b':')
        if isinstance(v,torch.Tensor):h.update(str(v.dtype).encode()+str(tuple(v.shape)).encode()+v.detach().contiguous().numpy().tobytes())
        elif isinstance(v,dict):
            for key in sorted(v,key=lambda k:(type(k).__name__,repr(k))):add(key);add(v[key])
        elif isinstance(v,(tuple,list)):
            for item in v:add(item)
        elif type(v) is float:h.update(struct.pack('<d',v))
        else:h.update(canonical(v).encode('utf-8'))
        h.update(b';')
    add(value);return h.hexdigest()


class LearningRuntime:
    def __init__(self,protocol_path,store,operation):
        self.protocol,self.config,self.protocol_sha256=load_runtime_protocol(protocol_path)
        c=self.config;self.model=DurationNavigationDQN(c['model_seed'],self.protocol_sha256)
        self.store=JournaledEpisodeCommitStore(store,self.protocol_sha256,c['scene_seed'],c['episodes'])
        if shutil.disk_usage(self.store.root.parent).free<c['minimum_free_disk_mib']*1048576:raise ValueError('Free disk below frozen runtime reserve')
        if operation=='initialize':self.store.initialize(self.model)
        elif operation=='resume':self.store.restore(self.model)
        else:raise ValueError('Explicit initialize/resume operation required')
        self.episode=None;self.expected=None;self.pending_choice=None;self.credit=None
        self._snapshots()

    def _snapshots(self):
        current=self.model.cursor['next_episode_index'];base=self.store.root.parent/'snapshots'
        if base.is_symlink() or base.resolve().parent!=self.store.root.parent:raise ValueError('Owned snapshot path required')
        base.mkdir(exist_ok=True)
        if len(list(base.glob('*.pending')))>4:raise ValueError('Inspect preserved snapshot pending budget')
        for index in self.config['snapshot_episodes']:
            if index>current:continue
            target=base/f'episode-{index:06d}'
            if target.is_symlink():raise ValueError('Invalid snapshot target')
            if target.exists():
                m=json.loads((target/'snapshot.json').read_text(encoding='utf-8'))
                if m['protocol_sha256']!=self.protocol_sha256 or m['episode']!=index or sha(target/'checkpoint.pt')!=m['checkpoint_sha256']:raise ValueError('Frozen snapshot changed')
                continue
            if index!=current:raise ValueError('Earlier required snapshot missing; do not reconstruct or skip')
            if shutil.disk_usage(base).free<self.config['minimum_free_disk_mib']*1048576:raise ValueError('Snapshot disk reserve exceeded')
            _,manifest,folder=self.store._head()
            pending=base/(target.name+'.'+uuid.uuid4().hex[:8]+'.pending');pending.mkdir()
            shutil.copyfile(folder/'checkpoint.pt',pending/'checkpoint.pt')
            if sha(pending/'checkpoint.pt')!=manifest['checkpoint_sha256']:raise ValueError('Snapshot copy hash mismatch')
            with (pending/'snapshot.json').open('x',encoding='utf-8') as file:
                json.dump(dict(schema='warirak.navigation-model-snapshot.v1',protocol_sha256=self.protocol_sha256,episode=index,
                    checkpoint_sha256=manifest['checkpoint_sha256'],model_schema=MODEL_SCHEMA,cursor=self.model.cursor,
                    actual_training=self.protocol['execution_scope']=='research_training',production_ready=False),file,sort_keys=True)
                file.flush();os.fsync(file.fileno())
            if pending.resolve().parent!=base.resolve() or target.resolve().parent!=base.resolve():raise ValueError('Snapshot move escaped owned root')
            os.rename(pending,target)

    def status(self):
        i=self.model.cursor['next_episode_index']
        return dict(protocol_sha256=self.protocol_sha256,scope=self.protocol['execution_scope'],model_schema=MODEL_SCHEMA,
            phase='episode_active' if self.episode and not self.episode['terminal'] else 'episode_pending_commit' if self.episode else 'budget_complete' if i==self.config['episodes'] else 'between_episodes',
            cursor=copy.deepcopy(self.model.cursor),next_seed=self.config['scene_seed']+i if i<self.config['episodes'] else None,
            choices=self.model.choices,replay_records=self.model.replay.total_added,updates=self.model.updates,
            actual_training=self.protocol['execution_scope']=='research_training',physical_motor_transport=False)

    def begin(self,params):
        if set(params)!={'seed','profile','fixture_used','first_request'} or self.episode:raise ValueError('New exact episode envelope required')
        i=self.model.cursor['next_episode_index'];c=self.config
        if i>=c['episodes'] or params['seed']!=c['scene_seed']+i or type(params['seed']) is not int or params['profile']!=c['profiles'][i%len(c['profiles'])] or type(params['fixture_used']) is not bool or params['fixture_used']!=(c['fixture_policy']!='generated_unmodified'):raise ValueError('Skipped seed/profile or forbidden fixture')
        request=validate_request(params['first_request'],now_ms=params['first_request']['encoded_at_ms'])
        identity=f"duration-{self.protocol_sha256[:12]}-{i:06d}"
        if request['session_id']!='dn-'+self.protocol_sha256[:12]+f'-{i:06d}' or request['record_sequence']!=1:raise ValueError('New episode session/record required')
        self.episode=dict(id=identity,seed=params['seed'],profile=params['profile'],fixture_used=params['fixture_used'],steps=0,reward=0.,terminal=False,reason='none',nulls=0,prefix_steps=0,prefix_reward=0.,credited_steps=0,credited_reward=0.,seen_assistance=False)
        self.expected=copy.deepcopy(request);self.pending_choice=None;self.credit=None
        return dict(episode_id=identity,phase='episode_active')

    def act(self,params):
        if set(params)!={'request','now_ms'} or not self.episode or self.episode['terminal'] or self.pending_choice is not None:raise ValueError('One actor proposal per pending original step')
        r=validate_request(params['request'],now_ms=params['now_ms'])
        if r!=self.expected or params['now_ms']!=r['encoded_at_ms']:raise ValueError('Actor request changed or retimed from synchronous simulation stream')
        c=self.config;epsilon=c['epsilon_floor']+(c['epsilon_start']-c['epsilon_floor'])*max(0.,1-self.model.choices/c['epsilon_decay_choices'])
        action=self.model.choose(r,epsilon,now_ms=params['now_ms']);self.pending_choice=action
        reply={k:r[k] for k in _REPLY_KEYS};reply.update(schema='warirak.navigation-inference-reply.v1',model_schema=MODEL_SCHEMA,action=action)
        return dict(reply=reply,epsilon=epsilon,choices=self.model.choices,scope=self.protocol['execution_scope'],production_ready=False)

    def _finish_credit(self,next_request,terminal,reason):
        p=self.credit
        if p is None:return None
        return dict(schema='warirak.navigation-duration-credit.v1',source='simulation',plant_environment='warirak-pool-mission-v4r2-dev',episode_id=self.episode['id'],state_request=p['state'],action=p['action'],reward=p['reward'],undiscounted_reward=p['raw'],duration_steps=p['duration'],continuation_discount=.985**p['duration'],next_request=next_request,terminal=terminal,terminal_reason=reason,physical_motor_transport=False)

    def _consume_credit(self,credit):
        validate_duration_credit(credit);self.model.replay.append(credit)
        return self.model.learn() if self.model.replay.total_added%self.config['update_every_credits']==0 else None

    def step(self,ledger):
        e=self.episode
        if not e or e['terminal'] or ledger.get('schema')!='warirak.navigation-r2-step-ledger.v1' or ledger.get('source')!='simulation' or ledger.get('physical_motor_transport') is not False:raise ValueError('Active original R2 step ledger required')
        s,n=validate_request(ledger['state_request']),validate_request(ledger['next_request'])
        if s!=self.expected or n['session_id']!=s['session_id'] or n['observation_at_ms']-s['observation_at_ms']!=100 or n['record_sequence']!=s['record_sequence']+1 or n['stream_epoch']<s['stream_epoch']:raise ValueError('Skipped/retimed original physical step')
        a=ledger['requested_action'];request=ledger['original_request']
        if a is not None:
            if type(a) is not int or a!=self.pending_choice or not s['allowed_mask'][a]:raise ValueError('Actual request differs from actor proposal/mask')
            expected=dict(schema='warirak.mission-sim-request.v2',environment='warirak-pool-mission-v4r2-dev',source='simulation',sequence=e['steps'],issued_at_ms=s['observation_at_ms'],valid_until_ms=s['observation_at_ms']+400,action=_ACTIONS[a],control_enabled=False)
            if canonical(request)!=canonical(expected):raise ValueError('Original request clock/TTL/identity mismatch')
        elif request is not None:raise ValueError('Null request must not become STOP')
        if type(ledger['terminal']) is not bool or ledger['terminal_reason'] not in ('none','collection','collision','time_limit') or ledger['terminal']!=(ledger['terminal_reason']!='none'):raise ValueError('Invalid natural terminal')
        if ledger['terminal_reason']=='time_limit' and e['steps']+1!=960 or e['steps']>=960:raise ValueError('Reduced/overrun episode horizon')
        terms=ledger['reward_terms'];reward=ledger['reward']
        assist=any(n['vector'][i]==1 for i in _ASSIST_INDICES)
        if set(terms)!={'distance_progress','step','collection','collision','first_assistance'} or not all(finite(v) for v in terms.values()) or not finite(reward) or abs(reward)>64 or not math.isclose(sum(terms.values()),reward,abs_tol=1e-9) or terms['step']!=-.015 or terms['collection']!=(40 if ledger['terminal_reason']=='collection' else 0) or terms['collision']!=(-30 if ledger['terminal_reason']=='collision' else 0) or terms['first_assistance']!=(-10 if assist and not e['seen_assistance'] else 0):raise ValueError('Changed R2 reward terms')
        e['seen_assistance']|=assist
        expected_credits=[]
        if a is not None:
            c=self._finish_credit(s,False,'none')
            if c:expected_credits.append(c)
            self.credit=dict(state=copy.deepcopy(s),action=a,reward=0.,raw=0.,duration=0)
        e['steps']+=1;e['reward']+=reward;e['nulls']+=int(a is None)
        if self.credit:
            p=self.credit;p['reward']+=(.985**p['duration'])*reward;p['raw']+=reward;p['duration']+=1
        else:e['prefix_steps']+=1;e['prefix_reward']+=reward
        if ledger['terminal']:
            c=self._finish_credit(n,True,ledger['terminal_reason'])
            if c:expected_credits.append(c)
            self.credit=None
        actual=ledger['completed_credits']
        if type(actual) is not list or len(actual)!=len(expected_credits):raise ValueError('Missing physical reward credit')
        losses=[]
        for provided,expected in zip(actual,expected_credits):
            validate_duration_credit(provided)
            for key in expected:
                if key in ('reward','undiscounted_reward','continuation_discount'):
                    if not math.isclose(provided[key],expected[key],rel_tol=1e-12,abs_tol=1e-9):raise ValueError('Lost/altered wait reward')
                elif provided[key]!=expected[key]:raise ValueError('Credit original identity mismatch:'+key)
            e['credited_steps']+=provided['duration_steps'];e['credited_reward']+=provided['undiscounted_reward']
            loss=self._consume_credit(provided)
            if loss:losses.append(loss['loss'])
        self.expected=copy.deepcopy(n);self.pending_choice=None;e['terminal']=ledger['terminal'];e['reason']=ledger['terminal_reason']
        return dict(accepted_credits=len(actual),updates=self.model.updates,replay_records=self.model.replay.total_added,losses=losses,episode_steps=e['steps'])

    def commit(self,result):
        e=self.episode
        if not e or not e['terminal'] or self.credit is not None:raise ValueError('Commit only a naturally complete episode')
        for key,value in [('episode_id',e['id']),('seed',e['seed']),('profile',e['profile']),('fixture_used',e['fixture_used']),('steps',e['steps']),('terminal_reason',e['reason']),('null_request_steps',e['nulls']),('passive_prefix_steps',e['prefix_steps']),('credited_steps',e['credited_steps']),('collections',int(e['reason']=='collection')),('collisions',int(e['reason']=='collision')),('timeouts',int(e['reason']=='time_limit'))]:
            if result.get(key)!=value:raise ValueError('Episode result differs from accepted steps:'+key)
        for key,value in [('reward',e['reward']),('passive_prefix_reward',e['prefix_reward']),('credited_raw_reward',e['credited_reward'])]:
            if not finite(result.get(key)) or not math.isclose(result[key],value,rel_tol=1e-12,abs_tol=1e-7):raise ValueError('Episode reward conservation mismatch')
        if shutil.disk_usage(self.store.root.parent).free<self.config['minimum_free_disk_mib']*1048576:raise ValueError('Commit disk reserve exceeded')
        committed=self.store.commit(self.model,result);self._snapshots();self.episode=None;self.expected=None
        return dict(committed=committed,status=self.status())

    def fingerprint(self):
        if self.episode:raise ValueError('Fingerprint only at committed between-episode boundary')
        return dict(state_sha256=state_fingerprint(self.model.checkpoint(self.model.cursor)),status=self.status())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol',required=True);parser.add_argument('--store',required=True)
    parser.add_argument('--operation',choices=('initialize','resume'),required=True)
    args=parser.parse_args();store=Path(args.store).resolve();lock=store.with_name(store.name+'.runtime.lock')
    if lock.is_symlink() or lock.parent!=store.parent:raise ValueError('Owned runtime lock path required')
    lock.parent.mkdir(parents=True,exist_ok=True)
    import psutil
    with lock.open('x',encoding='utf-8') as file:
        json.dump(dict(pid=os.getpid(),created=psutil.Process().create_time(),protocol_sha256=sha(Path(args.protocol))),file);file.flush();os.fsync(file.fileno())
    try:
        runtime=LearningRuntime(args.protocol,store,args.operation)
        maximum=runtime.config['episodes']*(2*960+4)+32
        for expected_id in range(1,maximum+1):
            line=sys.stdin.buffer.readline(65537)
            if not line:return
            try:
                msg=decode_json(line)
                if type(msg) is not dict or set(msg)!={'schema','id','method','params'} or msg['schema']!=RPC or type(msg['id']) is not int or msg['id']!=expected_id or type(msg['params']) is not dict:raise ValueError('Ordered bounded simulation RPC required')
                method,params=msg['method'],msg['params']
                if method=='status' and not params:value=runtime.status()
                elif method=='begin':value=runtime.begin(params)
                elif method=='act':value=runtime.act(params)
                elif method=='step':value=runtime.step(params)
                elif method=='commit':value=runtime.commit(params)
                elif method=='fingerprint' and not params:value=runtime.fingerprint()
                elif method=='shutdown' and set(params)=={'abort_uncommitted'} and type(params['abort_uncommitted']) is bool:
                    if runtime.episode and not params['abort_uncommitted']:raise ValueError('Explicit uncommitted abort required')
                    value=dict(status=runtime.status(),uncommitted_aborted=runtime.episode is not None)
                else:raise ValueError('Unknown runtime RPC method/shape')
                print(json.dumps(dict(schema=RPC,id=expected_id,ok=True,result=value),allow_nan=False),flush=True)
                if method=='shutdown':return
            except (ValueError,TypeError,KeyError,RuntimeError) as error:
                print(json.dumps(dict(schema=RPC,id=expected_id,ok=False,error=str(error)[:1500]),allow_nan=False),flush=True)
                raise SystemExit(2)
        raise RuntimeError('Frozen runtime message budget exceeded')
    finally:lock.unlink()

if __name__=='__main__':main()
