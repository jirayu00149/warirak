"""Synchronize measured local training metadata to D1 using the existing Wrangler login."""
from pathlib import Path
import argparse,datetime,hashlib,json,os,subprocess,time

PROJECT=Path(__file__).resolve().parents[1]
LEGACY=Path('C:/Users/Administrator/Documents/Codex/2026-10-22/solid-mini-prototype-scale-model-350')
NODE=Path('C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sql(v):return 'NULL'if v is None else str(v)if isinstance(v,(int,float))else"'"+str(v).replace("'","''")+"'"
def encode(v):return json.dumps(v,ensure_ascii=False,separators=(',',':'))
def dataset_statement(name,data,status='ready'):
 now=int(time.time()*1000);manifest=read(data/'manifest.json')if(data/'manifest.json').exists()else None
 counts={s:sum(r['split']==s for r in manifest['images'])if manifest else 0 for s in ['train','val','test']}
 values=['owner',name,name,status,sum(counts.values()),counts['train'],counts['val'],counts['test'],hashlib.sha256((data/'manifest.json').read_bytes()).hexdigest()if manifest else None,encode(manifest.get('provenance',{}))if manifest else'{}',now,now]
 return 'INSERT INTO ai_datasets VALUES('+','.join(map(sql,values))+') ON CONFLICT(owner_id,id) DO UPDATE SET status=excluded.status,image_count=excluded.image_count,train_count=excluded.train_count,val_count=excluded.val_count,test_count=excluded.test_count,manifest_sha256=excluded.manifest_sha256,provenance_json=excluded.provenance_json,updated_at_ms=excluded.updated_at_ms;'
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path);p.add_argument('--seed',action='store_true');p.add_argument('--write-only',action='store_true');a=p.parse_args();now=int(time.time()*1000);statements=[]
 if a.seed:
  data=LEGACY/'warirak-cloudflare/ai/data/public-v2';report=read(PROJECT/'frontend/assets/models/evaluation-public-v2.json');release=read(PROJECT/'frontend/assets/models/release.json')
  statements.append(dataset_statement('public-v2',data))
  v=['owner','public-yolo26n-v2','public-v2','completed',60,60,encode(report['model_selection']['selected']),encode({'model':'YOLO26n','field_validated':False}),int(datetime.datetime.fromisoformat(report['created_at']).timestamp()*1000),now,now]
  statements.append('INSERT INTO ai_training_runs VALUES('+','.join(map(sql,v))+') ON CONFLICT(owner_id,id) DO NOTHING;')
  v=['owner',release['version'],'public-yolo26n-v2',report['weights_sha256'],report['imgsz'],encode(release),encode(report),1,int(datetime.datetime.fromisoformat(report['created_at']).timestamp()*1000)]
  statements.append('INSERT INTO ai_model_releases VALUES('+','.join(map(sql,v))+') ON CONFLICT(owner_id,id) DO NOTHING;')
 if a.run:
  state=read(a.run/'status.json');data=Path(state['data']);phase=state['phase'];dataset_status='ready'if(data/'validation.json').exists()else'preparing'
  dataset_id=state.get('dataset_id',data.name);run_id=state.get('run_id',a.run.name)
  if not all(isinstance(value,str) and value and len(value)<=100 and all(c.isalnum() or c in '-_.' for c in value) for value in [dataset_id,run_id]):raise ValueError('Invalid registry run or dataset identifier')
  statements.append(dataset_statement(dataset_id,data,dataset_status));mapped={'waiting_for_data':'preparing','baseline_validation':'validating','training':'training','validation_selection':'validating','historical_test':'validating','ncnn_export':'exporting','ncnn_check':'exporting','artifacts_ready':'completed','retained_baseline':'retained_baseline','needs_repair':'failed'}
  status=mapped.get(phase,'preparing');epoch=int(state.get('epoch',0));total=int(state.get('total_epochs',35));details={'phase':phase,'model':'YOLO26n','gpu':'NVIDIA RTX 2050','field_validated':False,'selection_split':'val','test_is_historical':True,'pending_review':phase=='artifacts_ready' and not state.get('delivery_complete',False),'published_release':state.get('published_release')}
  if(a.run/'selection.json').exists():
   selection=read(a.run/'selection.json');details['validation_comparison']={k:selection[k]for k in ['baseline_map50_95','candidate_map50_95','baseline_classes','candidate_classes','promote']}
   report_name='training-public-'+run_id.removeprefix('public-yolo26n-')+'-report.json'
   if run_id=='public-yolo26n-v3':report_name='training-public-v3-report.json'
   if(PROJECT/'frontend/assets/models'/report_name).exists():details['outcome_report']='/assets/models/'+report_name
  finished=int(datetime.datetime.fromisoformat(state['updated_at']).timestamp()*1000)if status in ['completed','retained_baseline','failed']else None
  details.update(recipe=state.get('recipe'),test_previously_exposed=True)
  v=['owner',run_id,dataset_id,status,epoch,total,encode(state.get('metrics',{})),encode(details),state.get('started_at_ms',now),now,finished]
  statements.append('INSERT INTO ai_training_runs VALUES('+','.join(map(sql,v))+') ON CONFLICT(owner_id,id) DO UPDATE SET status=excluded.status,epoch=excluded.epoch,total_epochs=excluded.total_epochs,validation_json=excluded.validation_json,details_json=excluded.details_json,updated_at_ms=excluded.updated_at_ms,finished_at_ms=excluded.finished_at_ms;')
 if not statements:raise ValueError('Specify --seed or --run')
 output=PROJECT/'work'/('ai-registry-sync-'+str(os.getpid())+'.sql');output.parent.mkdir(exist_ok=True);output.write_text('\n'.join(statements),encoding='utf-8')
 if not a.write_only:
  subprocess.run([str(NODE),str(PROJECT/'node_modules/wrangler/bin/wrangler.js'),'d1','execute','DB','--remote','--config','wrangler.jsonc','--file',str(output),'--json'],cwd=PROJECT,check=True,stdout=subprocess.DEVNULL,timeout=90)
 print(encode({'synced':not a.write_only,'statements':len(statements),'sql_file':str(output)}))
if __name__=='__main__':main()
