"""Prepare a reproducible two-class public-data baseline, with grouped leakage checks."""
from __future__ import annotations
import argparse,collections,concurrent.futures,datetime,hashlib,io,json,math,random,re,time,urllib.parse,urllib.request
from pathlib import Path
from PIL import Image,ImageOps
import numpy as np
import imagehash,yaml
from .dataset import validate,digest,yolo_values

MAPPING={4:0,5:0,7:1,8:1}
CLASSES=['plastic_bottle','bottle_cap']
REPOS={'taco':'pictograph/taco','water':'OliviaWuYJ/sc-floatwaste'}
def get(url):
 for attempt in range(4):
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Warirak-research/1.0'}),timeout=45) as r:
    value=r.read(40_000_001)
    if len(value)>40_000_000:raise ValueError('Source image exceeds 40 MB')
    return value
  except Exception:
   if attempt==3:raise
   time.sleep(1+attempt)
def js(url):return json.loads(get(url))
def sha(value):return hashlib.sha256(value).hexdigest()
def rank(value):return sha(('warirak-public-v1:'+str(value)).encode())
def water_group(image):
 name=Path(image['file_name']).stem
 if '.vlcsnap-' in name:name=name.split('.vlcsnap-')[0]
 elif '_frame_' in name:name=name.split('_frame_')[0]
 elif re.search(r'[-_]TIMEL\d+',name,re.I):name=re.split(r'(?i)(TIMEL\d+)',name)[0]+re.search(r'(?i)TIMEL\d+',name).group()
 else:name=re.sub(r'[-_]\d+[-_]\d+$','',name)
 return 'water:'+str(image.get('region'))+':'+name
def build(output,metadata,workers=6):
 output=output.resolve();metadata=metadata.resolve();output.mkdir(parents=True,exist_ok=True)
 stage=output/'staging';stage.mkdir(exist_ok=True)
 lock=output/'source-revisions.json'
 source_info=json.loads(lock.read_text())if lock.exists()else{}
 for key,repo in REPOS.items():
  if key in source_info:continue
  info=js('https://huggingface.co/api/datasets/'+repo)
  source_info[key]={'repository':'https://huggingface.co/datasets/'+repo,'revision':info['sha'],'license':'CC BY 4.0; see source image licence where specified'}
 lock.write_text(json.dumps(source_info,indent=2),encoding='utf-8')
 def hf(key,file):return f'https://huggingface.co/datasets/{REPOS[key]}/resolve/{source_info[key]["revision"]}/'+urllib.parse.quote(file,safe='/')
 metadata.mkdir(parents=True,exist_ok=True)
 for name,url in [('taco_annotations.json','https://raw.githubusercontent.com/pedropro/TACO/master/data/annotations.json'),('taco_mirror_metadata.jsonl',hf('taco','train/metadata.jsonl'))]:
  if not(metadata/name).exists():(metadata/name).write_bytes(get(url))
 taco=json.loads((metadata/'taco_annotations.json').read_text(encoding='utf-8'))
 mirror={r['file_name']:r for r in map(json.loads,(metadata/'taco_mirror_metadata.jsonl').read_text(encoding='utf-8').splitlines())}
 grouped=collections.defaultdict(list)
 for a in taco['annotations']:grouped[a['image_id']].append(a)
 positives=[i for i in taco['images'] if any(a['category_id']in MAPPING for a in grouped[i['id']])]
 negatives=sorted([i for i in taco['images'] if i not in positives],key=lambda i:rank(i['file_name']))[:180]
 records=[];annotation_conflicts=[]
 for i in positives+negatives:
  original=i['file_name'];file=original.replace('/','_')
  if file not in mirror:raise ValueError('Mirror image is absent from its annotation manifest')
  official_names={c['id']:c['name']for c in taco['categories']}
  official=sorted((official_names[a['category_id']],a['bbox'])for a in grouped[i['id']]if a['category_id']in MAPPING)
  mirrored=sorted((name,box)for name,box in zip(mirror[file]['objects']['category_names'],mirror[file]['objects']['bbox'])if name in{official_names[k]for k in MAPPING})
  if len(official)!=len(mirrored)or any(a[0]!=b[0]or any(abs(x-y)>2 for x,y in zip(a[1],b[1]))for a,b in zip(official,mirrored)):
   annotation_conflicts.append({'file':original,'reason':'Mirror bounding boxes differ from official annotations by more than rounding tolerance'});continue
  boxes=[]
  for a in grouped[i['id']]:
   if a['category_id']not in MAPPING:continue
   x,y,w,h=a['bbox'];x=max(0,x);y=max(0,y);w=min(w,i['width']-x);h=min(h,i['height']-y)
   if min(w,h)<=0:continue
   boxes.append(dict(class_id=MAPPING[a['category_id']],x=x/i['width'],y=y/i['height'],w=w/i['width'],h=h/i['height']))
  records.append(dict(id='taco-'+str(i['id']),source='taco',source_file=original,source_image_id=i['id'],url=hf('taco','train/'+file),width=i['width'],height=i['height'],session_id='taco:'+original.split('/')[0],boxes=boxes,review_basis='Official TACO author-reviewed annotations; automated geometry and source-manifest checks',original_url=i.get('flickr_url'),image_license=i.get('license')or'CC BY 4.0 (source default)'))
 water=[];water_anns=collections.defaultdict(list)
 for split in ['train','val']:
  data=js(hf('water','annotations/instances_'+split+'.json'))
  (output/('source-water-'+split+'.json')).write_text(json.dumps(data),encoding='utf-8')
  for image in data['images']:
   item=dict(image);item['original_split']=split;item['unique_id']=split+'-'+str(image['id']);water.append(item)
  for a in data['annotations']:water_anns[split+'-'+str(a['image_id'])].append(a)
 water_positive=[];water_negative=[]
 for i in sorted(water,key=lambda i:rank(i['file_name'])):
  annotations=water_anns[i['unique_id']];categories={a['category_id']for a in annotations}
  # DH_lid includes container lids: never relabel this ambiguous category as bottle_cap.
  if 16 in categories:continue
  if categories&{12,13}:water_positive.append(i)
  elif not annotations:water_negative.append(i)
 group_count=collections.Counter();selected=[]
 for i in sorted(water_positive,key=lambda i:(i.get('region')=='Hobart',rank(i['file_name']))):
  g=water_group(i)
  if group_count[g]>=16:continue
  if i.get('region')=='Hobart'and sum(x.get('region')=='Hobart'for x in selected)>=100:continue
  selected.append(i);group_count[g]+=1
 selected+=water_negative
 for i in selected:
  boxes=[]
  for a in water_anns[i['unique_id']]:
   if a['category_id']not in{12,13}:continue
   x,y,w,h=a['bbox'];x=max(0,x);y=max(0,y);w=min(w,i['width']-x);h=min(h,i['height']-y)
   if min(w,h)<=0:continue
   boxes.append(dict(class_id=0,x=x/i['width'],y=y/i['height'],w=w/i['width'],h=h/i['height']))
  records.append(dict(id='water-'+i['unique_id'],source='water',source_file=i['file_name'],source_image_id=i['id'],original_split=i['original_split'],url=hf('water',i['file_name']),width=i['width'],height=i['height'],session_id=water_group(i),boxes=boxes,review_basis='SC-FloatWaste source annotations; ambiguous lid-containing frames excluded',image_license='CC BY 4.0'))
 (output/'excluded_annotation_conflicts.json').write_text(json.dumps(annotation_conflicts,indent=2),encoding='utf-8')
 print(json.dumps({'phase':'download','selected':len(records),'sources':dict(collections.Counter(r['source']for r in records)),'excluded_annotation_conflicts':len(annotation_conflicts)}),flush=True)
 def download(r):
  target=stage/(r['id']+'.jpg');sidecar=stage/(r['id']+'.json')
  try:
   if target.exists()and sidecar.exists():return json.loads(sidecar.read_text())
   raw=get(r['url'])
   with Image.open(io.BytesIO(raw))as original:
    if original.width*original.height>60_000_000:raise ValueError('Image is too large')
    im=original.convert('RGB')
    if im.size!=(r['width'],r['height']):
     rotated=ImageOps.exif_transpose(original).convert('RGB')
     if rotated.size!=(r['width'],r['height']):raise ValueError('Source dimensions disagree with annotations')
     im=rotated
    im.thumbnail((1280,1280),Image.Resampling.LANCZOS)
    phash=str(imagehash.phash(im));tiny=np.asarray(im.resize((16,16))).astype(float)/255
    im.save(target,quality=93,optimize=True)
    result=dict(r,width=im.width,height=im.height,source_sha256=sha(raw),sha256=digest(target),perceptual_hash=phash,thumbnail=tiny.round(3).tolist())
    sidecar.write_text(json.dumps(result),encoding='utf-8');return result
  except Exception as e:return{'failed_id':r['id'],'error':type(e).__name__+': '+str(e)}
 downloaded=[];failed=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=workers)as pool:
  for n,r in enumerate(pool.map(download,records),1):
   (failed if'failed_id'in r else downloaded).append(r)
   if n%25==0 or n==len(records):print(json.dumps({'phase':'download','completed':n,'total':len(records),'failed':len(failed)}),flush=True)
 (output/'download_failures.json').write_text(json.dumps(failed,indent=2),encoding='utf-8')
 if len(failed)>len(records)*.05:raise ValueError('Too many source downloads failed; inspect download_failures.json')
 # Unite batches/capture sequences when exact or perceptually near-identical frames cross groups.
 parent={r['session_id']:r['session_id']for r in downloaded}
 def find(x):
  while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
  return x
 def union(a,b):
  a,b=find(a),find(b)
  if a!=b:parent[max(a,b)]=min(a,b)
 seen={};kept=[];duplicates=[];near_pairs=0
 for r in downloaded:
  if r['sha256']in seen:
   previous=seen[r['sha256']];union(r['session_id'],previous['session_id']);duplicates.append({'dropped':r['id'],'kept':previous['id']});continue
  for other in kept:
   if (int(r['perceptual_hash'],16)^int(other['perceptual_hash'],16)).bit_count()>4:continue
   if abs(r['width']/r['height']-other['width']/other['height'])>.03:continue
   difference=np.mean((np.asarray(r['thumbnail'])-np.asarray(other['thumbnail']))**2)
   if difference<.008:union(r['session_id'],other['session_id']);near_pairs+=1
  seen[r['sha256']]=r;kept.append(r)
 for r in kept:r['session_id']=find(r['session_id'])
 stats=collections.defaultdict(lambda:np.zeros(3))
 for r in kept:
  stats[r['session_id']][0]+=1
  for b in r['boxes']:stats[r['session_id']][1+b['class_id']]+=1
 groups=sorted(stats);totals=sum(stats.values());best=None
 for seed in range(5000):
  shuffled=groups.copy();random.Random(seed).shuffle(shuffled);sums={s:np.zeros(3)for s in ['train','val','test']};assignment={}
  for g in shuffled:
   deficits={s:float(np.mean((sums[s]+stats[g])/np.maximum(totals*f,1)))for s,f in [('train',.7),('val',.15),('test',.15)]}
   choice=min(deficits,key=deficits.get);assignment[g]=choice;sums[choice]+=stats[g]
  if any(sums[s][2]<25 or sums[s][1]<25 for s in ['val','test']):continue
  score=sum(float(np.sum(((sums[s]-totals*f)/np.maximum(totals*f,1))**2))for s,f in [('train',.7),('val',.15),('test',.15)])
  if best is None or score<best[0]:best=(score,assignment,sums,seed)
 if best is None:raise ValueError('Cannot produce independent groups with class coverage')
 _,assignment,sums,split_seed=best
 final=[]
 for r in kept:
  split=assignment[r['session_id']];relative='images/'+split+'/'+r['id']+'.jpg';destination=output/relative;destination.parent.mkdir(parents=True,exist_ok=True)
  source=stage/(r['id']+'.jpg')
  if not destination.exists():destination.write_bytes(source.read_bytes())
  label=output/'labels'/split/(r['id']+'.txt');label.parent.mkdir(parents=True,exist_ok=True)
  label.write_text(''.join(str(int(v[0]))+' '+' '.join(f'{x:.6f}'for x in v[1:])+'\n'for v in map(yolo_values,r['boxes'])),encoding='utf-8')
  final.append({k:v for k,v in r.items()if k not in{'thumbnail','url'}}|dict(file=relative,split=split,reviewed=True,negative=not bool(r['boxes'])))
 manifest=dict(schema='warirak.dataset.v1',classes=CLASSES,seed=split_seed,group_splits=assignment,images=final,provenance={'sources':source_info,'official_taco_annotation_sha256':digest(metadata/'taco_annotations.json'),'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'transforms':['source dimension verification','long edge capped at 1280 preserving aspect ratio','EXIF stripped in annotation coordinate system','JPEG quality 93'],'label_mapping':{'TACO':{'plastic_bottle':[4,5],'bottle_cap':[7,8]},'SC-FloatWaste':{'plastic_bottle':[12,13],'excluded_ambiguous_lid':16}},'limitations':['Public datasets are not a calibrated boat-camera field dataset','Water-domain caps are not independently labelled in SC-FloatWaste; ambiguous lid-containing frames excluded','Capture groups inferred from source batches and sequence names; near duplicates grouped conservatively']})
 (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
 (output/'data.yaml').write_text(yaml.safe_dump(dict(path='.',train='images/train',val='images/val',test='images/test',names=dict(enumerate(CLASSES)))),encoding='utf-8')
 report=validate(output);report.update(duplicates_removed=duplicates,near_duplicate_pairs_grouped=near_pairs,download_failures=len(failed),source_counts=dict(collections.Counter(r['source']for r in final)))
 (output/'validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
 if not report['valid']:raise ValueError('Prepared public dataset did not pass validation')
 return report
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--metadata',type=Path,default=Path('data/source-metadata'));p.add_argument('--workers',type=int,default=6);a=p.parse_args();build(a.out,a.metadata,a.workers)
if __name__=='__main__':main()
