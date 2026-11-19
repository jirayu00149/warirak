"""Bounded between-episode checkpoint/result commits; no plant or training runner."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import re
import uuid


def _sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def _read(path):return json.loads(path.read_text(encoding='utf-8'))
def _write(path,data):
    with path.open('x',encoding='utf-8') as file:
        json.dump(data,file,sort_keys=True,allow_nan=False)
        file.flush();os.fsync(file.fileno())
def _uint(v):return type(v) is int and 0<=v<=9007199254740991


class EpisodeCommitStore:
    """CURRENT pointer selects a complete generation. Orphans are never silently promoted."""
    def __init__(self,root,protocol_sha256,seed_start,budget):
        self.root=Path(root).resolve()
        if (type(protocol_sha256) is not str or re.fullmatch('[0-9a-f]{64}',protocol_sha256) is None or
            not _uint(seed_start) or not _uint(budget) or not 1<=budget<=100000 or seed_start+budget>2147483647):
            raise ValueError('Explicit bounded protocol seed/budget required')
        self.protocol=protocol_sha256;self.seed_start=seed_start;self.budget=budget
        self.root.mkdir(parents=True,exist_ok=True)
        self.token=None

    def _child(self,name):
        if type(name) is not str or re.fullmatch(r'(g[0-9]{8}-[0-9a-f]{8}|CURRENT(?:\.[0-9a-f]{8}\.pending)?\.json|commit\.lock)',name) is None:
            raise ValueError('Unexpected store member')
        path=self.root/name
        if path.is_symlink() or path.resolve().parent!=self.root:
            raise ValueError('Store path escaped dedicated root')
        return path

    def _head(self):
        pointer=_read(self._child('CURRENT.json'))
        if (set(pointer)!={'schema','protocol_sha256','seed_start','budget','head','retained','prune'} or
            pointer['schema']!='warirak.navigation-commit-pointer.v1' or pointer['protocol_sha256']!=self.protocol or
            pointer['seed_start']!=self.seed_start or pointer['budget']!=self.budget or
            not 1<=len(pointer['retained'])<=2 or pointer['head']!=pointer['retained'][0]):
            raise ValueError('Commit pointer identity mismatch')
        ref=pointer['head'];folder=self._child(ref['directory'])
        if _sha(folder/'manifest.json')!=ref['manifest_sha256']:
            raise ValueError('Committed manifest hash mismatch')
        manifest=_read(folder/'manifest.json')
        if manifest['protocol_sha256']!=self.protocol or manifest['seed_start']!=self.seed_start or manifest['budget']!=self.budget:
            raise ValueError('Generation identity mismatch')
        for file,field in [('checkpoint.pt','checkpoint_sha256'),('result.json','result_sha256')]:
            if (folder/file).is_symlink() or _sha(folder/file)!=manifest[field]:
                raise ValueError('Committed artifact hash mismatch')
        return pointer,manifest,folder

    def _prune(self,pointer):
        keep={r['directory'] for r in pointer['retained']}
        for ref in pointer['prune']:
            if ref['directory'] in keep:raise ValueError('Cannot prune retained checkpoint')
            folder=self._child(ref['directory'])
            if not folder.exists():continue
            if {p.name for p in folder.iterdir()}!={'manifest.json','checkpoint.pt','result.json'}:
                raise ValueError('Preserve generation with unexpected files')
            if _sha(folder/'manifest.json')!=ref['manifest_sha256']:
                raise ValueError('Preserve changed old manifest')
            m=_read(folder/'manifest.json')
            for file,field in [('checkpoint.pt','checkpoint_sha256'),('result.json','result_sha256')]:
                p=folder/file
                if p.is_symlink() or p.resolve().parent!=folder or _sha(p)!=m[field]:
                    raise ValueError('Preserve changed old artifact')
            # Targets were resolved, confined and verified above. No recursive deletion.
            for file in ('checkpoint.pt','result.json','manifest.json'):(folder/file).unlink()
            folder.rmdir()

    def initialize(self,learner):
        if any(self.root.iterdir()):raise ValueError('Initialize only an empty dedicated store')
        if learner.protocol_sha256!=self.protocol:raise ValueError('Learner protocol mismatch')
        cursor=dict(schema='warirak.navigation-episode-cursor.v1',phase='between_episodes',next_episode_index=0,environment_steps=0)
        return self._publish(learner,None,cursor,None,None)

    def restore(self,learner):
        if self._child('commit.lock').exists():
            raise ValueError('Inspect process and stale transaction lock before recovery')
        pointer,manifest,folder=self._head()
        learner.load(folder/'checkpoint.pt',expected_sha256=manifest['checkpoint_sha256'])
        if learner.cursor!=manifest['cursor']:raise ValueError('Checkpoint/manifest cursor mismatch')
        self._prune(pointer)
        self.token=pointer['head']['manifest_sha256']
        return dict(cursor=manifest['cursor'],next_seed=self.seed_start+manifest['cursor']['next_episode_index'],committed_result=_read(folder/'result.json'))

    def commit(self,learner,result,*,failpoint=None):
        pointer,manifest,_=self._head()
        if self.token!=pointer['head']['manifest_sha256'] or learner.cursor!=manifest['cursor']:
            raise ValueError('Restore committed cursor before another transaction')
        i=manifest['cursor']['next_episode_index']
        if (type(result) is not dict or result.get('schema')!='warirak.navigation-r2-episode-result.v1' or
            result.get('source')!='simulation' or result.get('physical_motor_transport') is not False or
            result.get('seed')!=self.seed_start+i or type(result.get('seed')) is not int or
            result.get('done') is not True or not _uint(result.get('steps')) or not 1<=result['steps']<=960 or
            i>=self.budget or any(type(result.get(k)) is not int or result[k] not in (0,1) for k in ('collections','collisions','timeouts')) or
            sum(result[k] for k in ('collections','collisions','timeouts'))!=1 or
            result.get('all_physical_steps_accounted') is not True or result.get('assistance_not_early_termination') is not True or
            result.get('pending_credit_steps')!=0 or not _uint(result.get('credited_steps')) or not _uint(result.get('passive_prefix_steps')) or result['credited_steps']+result['passive_prefix_steps']!=result['steps'] or
            type(result.get('reward')) not in (int,float) or not math.isfinite(result['reward']) or
            type(result.get('reward_conservation_error')) not in (int,float) or not math.isfinite(result['reward_conservation_error']) or abs(result['reward_conservation_error'])>1e-7):
            raise ValueError('Cannot commit skipped seed, incomplete or censored outcome')
        cursor=dict(schema='warirak.navigation-episode-cursor.v1',phase='between_episodes',next_episode_index=i+1,
                    environment_steps=manifest['cursor']['environment_steps']+result['steps'])
        return self._publish(learner,result,cursor,pointer,failpoint)

    def _publish(self,learner,result,cursor,old,failpoint):
        if failpoint not in (None,'checkpoint_written','generation_written','before_pointer','after_pointer'):
            raise ValueError('Unknown controlled interruption point')
        if learner.protocol_sha256!=self.protocol:raise ValueError('Learner protocol mismatch')
        if len(list(self.root.glob('g*')))>=8 or len(list(self.root.glob('CURRENT.*.pending.json')))>=4:
            raise ValueError('Inspect preserved orphan transaction budget before continuing')
        lock=self._child('commit.lock')
        with lock.open('x',encoding='utf-8') as file:
            json.dump(dict(pid=os.getpid(),protocol_sha256=self.protocol),file);file.flush();os.fsync(file.fileno())
        self.token=None
        try:
            name=f"g{cursor['next_episode_index']:08d}-{uuid.uuid4().hex[:8]}"
            folder=self._child(name);folder.mkdir()
            digest=learner.save(folder/'checkpoint.pt',cursor)
            if failpoint=='checkpoint_written':raise RuntimeError('controlled interruption:checkpoint_written')
            _write(folder/'result.json',result)
            manifest=dict(schema='warirak.navigation-generation.v1',protocol_sha256=self.protocol,
                seed_start=self.seed_start,budget=self.budget,cursor=cursor,checkpoint_sha256=digest,
                result_sha256=_sha(folder/'result.json'),parent_manifest_sha256=old['head']['manifest_sha256'] if old else None)
            _write(folder/'manifest.json',manifest)
            ref=dict(directory=name,manifest_sha256=_sha(folder/'manifest.json'))
            if failpoint=='generation_written':raise RuntimeError('controlled interruption:generation_written')
            retained=([ref]+(old['retained'] if old else []))[:2]
            pointer=dict(schema='warirak.navigation-commit-pointer.v1',protocol_sha256=self.protocol,
                seed_start=self.seed_start,budget=self.budget,head=ref,retained=retained,
                prune=[r for r in (old['retained'] if old else []) if r not in retained])
            pending=self._child('CURRENT.'+uuid.uuid4().hex[:8]+'.pending.json');_write(pending,pointer)
            if failpoint=='before_pointer':raise RuntimeError('controlled interruption:before_pointer')
            os.replace(pending,self._child('CURRENT.json'))
            if failpoint=='after_pointer':raise RuntimeError('controlled interruption:after_pointer')
            self._prune(pointer)
            learner.cursor=cursor;self.token=ref['manifest_sha256']
            return dict(cursor=cursor,manifest_sha256=self.token,next_seed=self.seed_start+cursor['next_episode_index'])
        finally:
            # This finally releases only the lock created by this transaction.
            lock.unlink()
