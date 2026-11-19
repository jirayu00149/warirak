"""Finish local training artifacts independently of the chat's API quota. Does not deploy."""
import argparse,datetime,json,os,subprocess,sys,time
from pathlib import Path
import psutil

def read(path):
 try:return json.loads(path.read_text(encoding='utf-8'))
 except(FileNotFoundError,json.JSONDecodeError):return{}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--trainer-pid',type=int,required=True);a=p.parse_args()
 ai=Path(__file__).resolve().parents[1];root=ai/'runs/public-yolo26n-v2';root.mkdir(parents=True,exist_ok=True);lock=root/'postprocess-lock.json'
 previous=read(lock)
 if previous.get('pid')and psutil.pid_exists(previous['pid']):raise RuntimeError('A postprocessing coordinator is already running')
 lock.write_text(json.dumps({'pid':os.getpid(),'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}))
 def state(phase,**fields):
  value=dict(phase=phase,updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),pid=os.getpid(),**fields);(root/'pipeline-status.json').write_text(json.dumps(value,indent=2));print(json.dumps(value),flush=True)
 def step(label,args):
  state(label)
  with(root/(label+'.log')).open('a',encoding='utf-8')as log:subprocess.run([sys.executable,'-u',*args],cwd=ai,stdout=log,stderr=subprocess.STDOUT,check=True)
 try:
  state('waiting_for_refinement',trainer_pid=a.trainer_pid)
  while read(root/'status.json').get('phase')!='complete':
   if not psutil.pid_exists(a.trainer_pid):
    time.sleep(3)
    if read(root/'status.json').get('phase')!='complete':raise RuntimeError('Trainer exited before completion; inspect its log and checkpoint')
   time.sleep(20)
  if read(root/'finalization-status.json').get('phase')!='complete':step('finalize_detector',['-m','warirak_ai.finalize_detector'])
  evaluation=read(root/'evaluation.json');weights=root/'warirak-yolo26n-public-v2.pt';ncnn=root/'warirak-yolo26n-public-v2_ncnn_model'
  if not read(root/'export-ready.json').get('complete'):
   step('export_ncnn',['-m','warirak_ai.export','--weights',str(weights),'--imgsz',str(evaluation['imgsz'])]);assert list(ncnn.glob('*.param'))and list(ncnn.glob('*.bin'))
   (root/'export-ready.json').write_text(json.dumps({'complete':True,'imgsz':evaluation['imgsz']}))
  if read(root/'export-evaluation.json').get('export_consistent')is not True:step('evaluate_export',['-m','warirak_ai.evaluate_export'])
  step('package_models',[str(ai.parent/'tools/package_trained.py')]);state('artifacts_ready',needs_review_and_cloudflare_deployment=True)
 except Exception as error:
  state('needs_repair',error=type(error).__name__+': '+str(error));raise
 finally:
  if read(lock).get('pid')==os.getpid():lock.unlink(missing_ok=True)
if __name__=='__main__':main()
