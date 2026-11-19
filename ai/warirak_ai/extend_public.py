"""Add novel reviewed bottle scenes to TRAIN ONLY, preserving both held-out cohorts."""
import argparse,collections,concurrent.futures,hashlib,io,json,math,os,re,subprocess
from pathlib import Path
import imagehash,numpy as np,yaml
from PIL import Image
from .public_dataset import get,rank
from .dataset import validate,digest,valid_box,yolo_values

REPO='roboticslaburjc/ExtendedTACO-reviewed'
def run(base,output,repository,workers=3):
 base=base.resolve();output=output.resolve();repository=repository.resolve();output.mkdir(parents=True,exist_ok=True)
 original=json.loads((base/'manifest.json').read_text(encoding='utf-8'));revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repository,text=True).strip();known={r['id']for r in original['images']}
 references=[]
 for r in original['images']:
  with Image.open(base/r['file'])as im:references.append(dict(id=r['id'],split=r['split'],hash=int(str(imagehash.phash(im)),16),aspect=im.width/im.height,thumb=np.asarray(im.convert('RGB').resize((16,16))).astype(float)/255))
 candidates=[]
 # This source stores polygons in labels/ and detection rectangles in darknet-labels/.
 for file in sorted((repository/'darknet-labels').glob('*.txt'),key=lambda p:rank(p.stem)):
  rows=[row.split()for row in file.read_text().splitlines()if row.strip()]
  if any(len(row)!=5 for row in rows):raise ValueError('Expected detection boxes, not segmentation polygons')
  if any(row[0]=='3'for row in rows)and 'ext-'+file.stem not in known:candidates.append((file.stem,rows))
 stage=output/'staging';stage.mkdir(exist_ok=True)
 print(json.dumps({'phase':'extra-cap-download','candidates':len(candidates),'revision':revision}),flush=True)
 def fetch(item):
  name,rows=item;sidecar=stage/(name+'.json');destination=stage/(name+'.jpg')
  if sidecar.exists()and destination.exists():return json.loads(sidecar.read_text())
  try:
   pointer=subprocess.check_output(['git','show','HEAD:images/'+name+'.jpg'],cwd=repository).decode()
   expected=re.search(r'oid sha256:([a-f0-9]{64})',pointer)
   if not expected:raise ValueError('Source image is not a verified LFS image')
   url=f'https://huggingface.co/datasets/{REPO}/resolve/{revision}/images/{name}.jpg';raw=get(url)
   if hashlib.sha256(raw).hexdigest()!=expected[1]:raise ValueError('Source image checksum mismatch')
   with Image.open(io.BytesIO(raw))as source:
    if source.width*source.height>60_000_000:raise ValueError('Source image exceeds pixel limit')
    image=source.convert('RGB');image.thumbnail((1280,1280),Image.Resampling.LANCZOS);phash=int(str(imagehash.phash(image)),16);thumb=np.asarray(image.resize((16,16))).astype(float)/255;aspect=image.width/image.height
    for ref in references:
     distance=(phash^ref['hash']).bit_count()
     if abs(aspect-ref['aspect'])>.08:continue
     tolerance=18 if ref['split']!='train'else 8
     if distance<=tolerance and np.mean((thumb-ref['thumb'])**2)<(.035 if ref['split']!='train'else .018):return dict(excluded=name,reason='known_image_or_held_out_scene_similarity',matched_id=ref['id'],matched_split=ref['split'])
    boxes=[]
    for row in rows:
     if row[0]not in{'3','4'}:continue
     _,cx,cy,w,h=map(float,row);x=max(0,cx-w/2);y=max(0,cy-h/2);right=min(1,cx+w/2);bottom=min(1,cy+h/2)
     box=dict(class_id=0 if row[0]=='3'else 1,x=x,y=y,w=right-x,h=bottom-y)
     if not valid_box(box):raise ValueError('Source has invalid normalized labels')
     boxes.append(box)
    image.save(destination,quality=93,optimize=True)
    value=dict(id='ext-'+name,file='images/train/ext-'+name+'.jpg',source='extended_taco_reviewed',source_file='images/'+name+'.jpg',source_sha256=expected[1],width=image.width,height=image.height,sha256=digest(destination),perceptual_hash=f'{phash:016x}',split='train',session_id='extended-scene:'+name,reviewed=True,review_basis='RoboticsLab URJC reviewed annotations; geometry and source hash verified; overlaps with known train/held-out images excluded',negative=False,boxes=boxes,image_license='Source default CC BY 4.0; individual source licences take precedence')
    sidecar.write_text(json.dumps(value),encoding='utf-8');return value
  except Exception as e:
   value=dict(failed=name,error=type(e).__name__+': '+str(e))
   with(stage/'failures.jsonl').open('a',encoding='utf-8')as f:f.write(json.dumps(value)+'\n')
   return value
 results=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=workers)as pool:
  for i,item in enumerate(pool.map(fetch,candidates),1):
   results.append(item)
   if i%25==0 or i==len(candidates):print(json.dumps({'phase':'extra-cap-download','completed':i,'total':len(candidates),'kept':sum('file'in r for r in results),'excluded':sum('excluded'in r for r in results),'failed':sum('failed'in r for r in results)}),flush=True)
 (output/'augmentation-audit.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
 additions=[r for r in results if'file'in r];seen={r['sha256']for r in original['images']};kept=[]
 for r in additions:
  if r['sha256']in seen:continue
  seen.add(r['sha256']);kept.append(r)
 if len(kept)<40:raise ValueError('Too few novel reviewed bottle examples remain')
 manifest=json.loads(json.dumps(original));manifest['images']+=kept
 manifest['group_splits'].update({r['session_id']:'train'for r in kept})
 manifest['provenance']['sources']['extended_taco_reviewed']={'repository':'https://huggingface.co/datasets/'+REPO,'revision':revision,'licence':'Annotations CC BY 4.0; images follow individual licences, CC BY 4.0 when unspecified'}
 manifest['provenance'].setdefault('augmentation_history',[]).append(manifest['provenance'].get('train_only_augmentation',{}))
 manifest['provenance']['train_only_augmentation']={'target':'plastic_bottle','new_images':len(kept),'validation_and_test_unchanged':True,'held_out_scene_filter':'pHash <=18 and thumbnail MSE <0.035 with similar aspect ratio','known_training_duplicate_filter':'pHash <=8 and thumbnail MSE <0.018 with similar aspect ratio','limitation':'Additional source lacks capture-session metadata; similarity checks reduce but cannot prove absence of all related scenes'}
 for r in manifest['images']:
  target=output/r['file'];target.parent.mkdir(parents=True,exist_ok=True);source=(stage/(r['id'].removeprefix('ext-')+'.jpg'))if r in kept else base/r['file']
  if not target.exists():
   try:os.link(source,target)
   except OSError:target.write_bytes(source.read_bytes())
  label=output/'labels'/r['split']/(Path(r['file']).stem+'.txt');label.parent.mkdir(parents=True,exist_ok=True)
  label.write_text(''.join(str(int(v[0]))+' '+' '.join(f'{x:.6f}'for x in v[1:])+'\n'for v in map(yolo_values,r['boxes'])),encoding='utf-8')
 (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8');(output/'data.yaml').write_text((base/'data.yaml').read_text(),encoding='utf-8')
 report=validate(output);report['additional_reviewed_bottle_images']=len(kept);report['base_manifest_sha256']=digest(base/'manifest.json');(output/'validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
 if not report['valid']:raise ValueError('Augmented dataset failed validation')
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--repository',type=Path,required=True);p.add_argument('--workers',type=int,default=3);a=p.parse_args();run(a.base,a.out,a.repository,a.workers)
if __name__=='__main__':main()
