"""Additive outcome journal: old checkpoint pruning must not delete episode evidence."""
import hashlib
import json
import os
import re
import uuid
from .navigation_commit import EpisodeCommitStore,_read,_write,_sha


def _bytes(value):return json.dumps(value,sort_keys=True,allow_nan=False).encode('utf-8')


class JournaledEpisodeCommitStore(EpisodeCommitStore):
    MAXIMUM_JOURNAL_BYTES=64*1048576
    def _journal(self):
        path=self.root/'outcomes'
        if path.is_symlink() or path.resolve().parent!=self.root:
            raise ValueError('Outcome journal escaped owned root')
        return path

    def _marker(self,pointer,manifest):
        file=self.root/'JOURNAL.json'
        if file.is_symlink():raise ValueError('Invalid journal marker path')
        expected=dict(schema='warirak.navigation-outcome-journal.v1',protocol_sha256=self.protocol,
                      seed_start=self.seed_start,budget=self.budget)
        if not file.exists():
            if manifest['cursor']['next_episode_index']!=0:
                raise ValueError('Cannot claim missing historical outcomes from an unjournaled run')
            self._journal().mkdir(exist_ok=True)
            _write(file,dict(expected,initial_manifest_sha256=pointer['head']['manifest_sha256']))
        marker=_read(file)
        if set(marker)!=set(expected)|{'initial_manifest_sha256'} or any(marker[k]!=v for k,v in expected.items()):
            raise ValueError('Journal identity mismatch')
        return marker

    def _validate_receipt(self,receipt,index,parent):
        keys={'schema','protocol_sha256','episode_index','seed','manifest_sha256','manifest','result'}
        if (type(receipt) is not dict or set(receipt)!=keys or receipt['schema']!='warirak.navigation-outcome-receipt.v1' or
            receipt['protocol_sha256']!=self.protocol or receipt['episode_index']!=index or receipt['seed']!=self.seed_start+index):
            raise ValueError('Outcome receipt sequence/identity mismatch')
        m=receipt['manifest']
        if (hashlib.sha256(_bytes(m)).hexdigest()!=receipt['manifest_sha256'] or
            m['parent_manifest_sha256']!=parent or m['cursor']['next_episode_index']!=index+1 or
            m['protocol_sha256']!=self.protocol or m['seed_start']!=self.seed_start or m['budget']!=self.budget or
            hashlib.sha256(_bytes(receipt['result'])).hexdigest()!=m['result_sha256'] or
            receipt['result']['seed']!=receipt['seed']):
            raise ValueError('Outcome result/manifest chain mismatch')
        return receipt['manifest_sha256']

    def _archive_head(self,pointer,manifest,folder):
        count=manifest['cursor']['next_episode_index']
        if self._journal_count==count:
            if self._journal_tail!=pointer['head']['manifest_sha256']:raise ValueError('Outcome journal/head mismatch')
            return
        if self._journal_count!=count-1:raise ValueError('Older outcome receipts missing; do not skip evidence')
        result=_read(folder/'result.json')
        if len(_bytes(result))>8192:raise ValueError('Bounded episode result required')
        receipt=dict(schema='warirak.navigation-outcome-receipt.v1',protocol_sha256=self.protocol,
            episode_index=count-1,seed=self.seed_start+count-1,manifest_sha256=pointer['head']['manifest_sha256'],manifest=manifest,result=result)
        tail=self._validate_receipt(receipt,count-1,self._journal_tail)
        data=_bytes(receipt)
        if self._journal_bytes+len(data)>self.MAXIMUM_JOURNAL_BYTES:raise ValueError('Outcome journal budget exceeded')
        target=self._journal()/f'episode-{count-1:08d}.json'
        pending=target.with_name(target.name+'.'+uuid.uuid4().hex[:8]+'.pending')
        if target.exists():raise ValueError('Unexpected existing outcome receipt')
        _write(pending,receipt);os.replace(pending,target)
        self._journal_count=count;self._journal_bytes+=len(data);self._journal_tail=tail

    def _scan(self,pointer,manifest,folder):
        marker=self._marker(pointer,manifest)
        journal=self._journal()
        files=[];pending=0;pending_bytes=0
        for path in journal.iterdir():
            if path.is_symlink() or not path.is_file():raise ValueError('Unexpected outcome journal member')
            if re.fullmatch(r'episode-[0-9]{8}\.json',path.name):files.append(path)
            elif re.fullmatch(r'episode-[0-9]{8}\.json\.[0-9a-f]{8}\.pending',path.name):
                if path.stat().st_size>16384:raise ValueError('Oversized pending outcome receipt')
                pending+=1;pending_bytes+=path.stat().st_size
            else:raise ValueError('Unexpected outcome journal filename')
        if pending>4:raise ValueError('Inspect preserved pending outcome budget')
        files.sort();self._journal_count=0;self._journal_bytes=pending_bytes;self._journal_tail=marker['initial_manifest_sha256']
        if len(files)>manifest['cursor']['next_episode_index']:raise ValueError('Outcome journal is ahead of committed checkpoint; no silent rollback')
        for i,file in enumerate(files):
            if file.name!=f'episode-{i:08d}.json' or file.stat().st_size>16384:raise ValueError('Missing or oversized outcome receipt')
            self._journal_tail=self._validate_receipt(_read(file),i,self._journal_tail)
            self._journal_count+=1;self._journal_bytes+=file.stat().st_size
        if self._journal_bytes>self.MAXIMUM_JOURNAL_BYTES:raise ValueError('Outcome journal budget exceeded')
        self._archive_head(pointer,manifest,folder)

    def initialize(self,learner):
        result=super().initialize(learner)
        self._scan(*self._head())
        return result

    def restore(self,learner):
        self.token=None
        if self._child('commit.lock').exists():raise ValueError('Inspect transaction owner/process before recovery')
        # Verify/archive committed outcomes before the base store can prune any generation.
        self._scan(*self._head())
        try:return super().restore(learner)
        except BaseException:
            self.token=None
            raise

    def commit(self,learner,result,*,failpoint=None):
        pointer,manifest,folder=self._head()
        if not hasattr(self,'_journal_count') or self._journal_count!=manifest['cursor']['next_episode_index'] or self._journal_tail!=pointer['head']['manifest_sha256']:
            raise ValueError('Restore complete outcome journal before another transaction')
        if len(_bytes(result))>8192 or self._journal_bytes+16384>self.MAXIMUM_JOURNAL_BYTES:
            raise ValueError('Outcome receipt budget must fit before checkpoint commit')
        result=super().commit(learner,result,failpoint=failpoint)
        self._archive_head(*self._head())
        return result
