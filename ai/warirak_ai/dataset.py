"""Validate grouped YOLO datasets or prepare one from a Studio project ZIP."""
from __future__ import annotations
import argparse, hashlib, json, math, re, sys, zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from PIL import Image, ImageOps
import yaml
from . import CLASSES

SPLITS = ("train", "val", "test")
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def safe_path(root: Path, name: str) -> Path:
    if not isinstance(name,str) or "\\" in name:
        raise ValueError("Image paths must be relative POSIX paths")
    p=PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise ValueError(f"Unsafe path: {name}")
    target=(root/Path(*p.parts)).resolve()
    if not target.is_relative_to(root.resolve()): raise ValueError("Path escapes dataset root")
    return target

def valid_box(b: dict) -> bool:
    try:
        k=b["class_id"];raw=[b[x]for x in("x","y","w","h")]
        if any(type(x)not in(int,float)for x in raw):return False
        v=list(map(float,raw))
        return type(k)is int and k in range(2) and all(math.isfinite(x)for x in v) and v[0]>=0 and v[1]>=0 and v[2]>0 and v[3]>0 and v[0]+v[2]<=1.000001 and v[1]+v[3]<=1.000001
    except (KeyError,TypeError,ValueError): return False

def yolo_values(b: dict) -> list[float]:
    if not valid_box(b): raise ValueError("Invalid normalized bounding box")
    return [b["class_id"],b["x"]+b["w"]/2,b["y"]+b["h"]/2,b["w"],b["h"]]

def grouped_split(images: list[dict], seed: int=42) -> dict[str,str]:
    groups=sorted({r["session_id"].strip()for r in images},key=lambda s:hashlib.sha256(f"{seed}:{s}".encode()).hexdigest())
    if len(groups)<3: raise ValueError("At least three independent capture groups are required")
    nval=max(1,math.floor(len(groups)*.15+.5));ntest=nval
    return {g:("test"if i<ntest else"val"if i<ntest+nval else"train")for i,g in enumerate(groups)}

def image_dimensions(path: Path) -> tuple[int,int]:
    with Image.open(path) as im:
        if im.width*im.height>25_000_000: raise ValueError("Image exceeds 25 megapixels")
        im.verify()
    with Image.open(path) as im: return ImageOps.exif_transpose(im).size

def validate(root: Path) -> dict:
    root=root.resolve();errors=[];warnings=[];counts={s:0 for s in SPLITS};classes={s:[0,0]for s in SPLITS};negatives=0;tiny=0
    try:
        manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8-sig"))
        if not isinstance(manifest,dict)or manifest.get("schema")!="warirak.dataset.v1"or manifest.get("classes")!=CLASSES: raise ValueError("Wrong dataset schema or classes")
        images=manifest["images"]
        if not isinstance(images,list)or not images or not all(isinstance(r,dict)for r in images): raise ValueError("Dataset has no valid image records")
        config=yaml.safe_load((root/"data.yaml").read_text(encoding="utf-8-sig"))
        if not isinstance(config,dict): raise ValueError("data.yaml must contain an object")
        names=config.get("names")
        if isinstance(names,dict): names=[names.get(i,names.get(str(i)))for i in range(2)]
        if names!=CLASSES: raise ValueError("data.yaml classes must be plastic_bottle, bottle_cap in that order")
    except (OSError,ValueError,KeyError,TypeError,yaml.YAMLError) as e:
        return {"valid":False,"errors":[str(e)],"warnings":[],"images":0,"counts":counts,"instances":classes}
    hashes={};group_splits={};listed=set();label_stems=set();groups=set()
    for record in images:
        try:
            name=record["file"];split=record["split"];group=record["session_id"].strip()
            if split not in SPLITS or not group: raise ValueError("Invalid split or empty capture group")
            path=safe_path(root,name)
            if PurePosixPath(name).parts[:2]!=("images",split)or path.suffix.lower()not in EXTENSIONS: raise ValueError("Image not in its declared split")
            if name in listed: raise ValueError("Duplicate manifest entry")
            listed.add(name);stem=(split,path.stem)
            if stem in label_stems: raise ValueError("Image stems collide with the same label file")
            label_stems.add(stem);groups.add(group)
            if group in group_splits and group_splits[group]!=split: raise ValueError("Capture-session leakage between splits")
            group_splits[group]=split
            if manifest.get("group_splits",{}).get(group)!=split: raise ValueError("Group manifest disagrees with image split")
            sha=digest(path)
            if sha!=record["sha256"]: raise ValueError("Image SHA-256 mismatch")
            if sha in hashes: raise ValueError(f"Duplicate image content also found at {hashes[sha]}")
            hashes[sha]=name
            width,height=image_dimensions(path)
            if (width,height)!=(record["width"],record["height"]): raise ValueError("Image dimensions do not match annotations (including EXIF orientation)")
            if record.get("reviewed")is not True: raise ValueError("Image has not been reviewed")
            boxes=record["boxes"]
            if not isinstance(boxes,list)or any(not valid_box(b)for b in boxes): raise ValueError("Invalid boxes")
            if type(record.get("negative"))is not bool or record["negative"]!=(not bool(boxes)): raise ValueError("Negative-image flag disagrees with boxes")
            label=root/"labels"/split/(path.stem+".txt")
            lines=[line.split()for line in label.read_text(encoding="utf-8-sig").splitlines()if line.strip()]
            if len(lines)!=len(boxes): raise ValueError("Label count does not match reviewed annotations")
            for line,b in zip(lines,boxes):
                if len(line)!=5: raise ValueError("Each YOLO label must have five fields")
                actual=list(map(float,line));expected=yolo_values(b)
                if any(not math.isfinite(a)or abs(a-e)>2e-6 for a,e in zip(actual,expected)): raise ValueError("YOLO labels do not match the normalized annotation")
                classes[split][b["class_id"]]+=1
                if min(b["w"]*width,b["h"]*height)<8: tiny+=1
            negatives+=not bool(boxes);counts[split]+=1
        except (OSError,ValueError,KeyError,TypeError) as e: errors.append(f"{record.get('file','unknown')}: {e}")
    if len(groups)<3: errors.append("At least three independent capture groups are required")
    for split in SPLITS:
        if not counts[split]: errors.append(f"No usable images in {split}")
        for k,name in enumerate(CLASSES):
            if not classes[split][k]: errors.append(f"{split} has no {name} examples")
        for path in (root/"images"/split).glob("*"):
            if path.is_file()and path.suffix.lower()in EXTENSIONS and path.relative_to(root).as_posix()not in listed: errors.append(f"Unlisted image: {path.name}")
        for path in (root/"labels"/split).glob("*.txt"):
            if (split,path.stem)not in label_stems: errors.append(f"Orphan label: {path.name}")
    if len(images)<1000: warnings.append("Small research dataset: collect more independent sessions before claiming field accuracy")
    if negatives/max(1,len(images))<.15: warnings.append("Few negative images; include empty water, waves, reflections and leaves")
    if tiny: warnings.append(f"{tiny} boxes are smaller than eight pixels on at least one side")
    return {"valid":not errors,"errors":errors,"warnings":warnings,"images":sum(counts.values()),"groups":len(groups),"counts":counts,"instances":classes,"negative_images":negatives}

def prepare(project: Path, output: Path) -> dict:
    if output.exists(): raise ValueError("Destination already exists; choose a new directory to preserve your data")
    with zipfile.ZipFile(project) as archive:
        entries=archive.infolist()
        if len(entries)>2500 or sum(e.file_size for e in entries)>2_000_000_000: raise ValueError("Project ZIP exceeds import limits")
        raw=archive.read("annotations.json")
        if len(raw)>5_000_000: raise ValueError("Annotation file is too large")
        meta=json.loads(raw)
        if meta.get("schema")!="warirak.project.v1"or meta.get("classes")!=CLASSES: raise ValueError("Wrong project schema or classes")
        images=meta["images"];splits=grouped_split(images)
        # Validate all annotation fields and ZIP paths before creating the destination.
        for r in images:
            if not re.fullmatch(r"[A-Za-z0-9-]{1,80}",r["id"])or r["extension"]not in("jpg","png","webp"): raise ValueError("Invalid image id/extension")
            if r["file"]!=f'images/{r["id"]}.{r["extension"]}': raise ValueError("Invalid image path")
            if r.get("reviewed")is not True or any(not valid_box(b)for b in r["boxes"]): raise ValueError("All images must have reviewed, valid annotations")
            if type(r.get("negative"))is not bool or r["negative"]!=(not bool(r["boxes"])): raise ValueError("Negative flag disagrees with labels")
            if archive.getinfo(r["file"]).file_size>20*1024*1024: raise ValueError("Image exceeds 20 MB")
        output.mkdir(parents=True)
        result=[]
        for r in images:
            split=splits[r["session_id"]];name=f'{r["id"]}.{r["extension"]}';relative=f"images/{split}/{name}"
            path=safe_path(output,relative);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.read(r["file"]))
            labels=output/"labels"/split/(r["id"]+".txt");labels.parent.mkdir(parents=True,exist_ok=True)
            rows=[str(int(v[0]))+" "+" ".join(f"{n:.6f}"for n in v[1:])for v in map(yolo_values,r["boxes"])]
            labels.write_text("\n".join(rows)+("\n"if rows else""),encoding="utf-8")
            result.append(dict(r,file=relative,split=split))
        (output/"manifest.json").write_text(json.dumps({"schema":"warirak.dataset.v1","classes":CLASSES,"seed":42,"group_splits":splits,"images":result},indent=2),encoding="utf-8")
        (output/"data.yaml").write_text(yaml.safe_dump({"path":".","train":"images/train","val":"images/val","test":"images/test","names":dict(enumerate(CLASSES))},sort_keys=False),encoding="utf-8")
    return validate(output)

def training_yaml(root: Path, destination: Path) -> Path:
    report=validate(root)
    if not report["valid"]: raise ValueError("Dataset validation failed:\n"+"\n".join(report["errors"]))
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(yaml.safe_dump({"path":str(root.resolve()),"train":"images/train","val":"images/val","test":"images/test","names":dict(enumerate(CLASSES))},sort_keys=False),encoding="utf-8")
    return destination.resolve()

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest="command",required=True)
    v=sub.add_parser("validate");v.add_argument("--data",type=Path,required=True);v.add_argument("--report",type=Path)
    q=sub.add_parser("prepare");q.add_argument("--project",type=Path,required=True);q.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    try: report=validate(a.data)if a.command=="validate"else prepare(a.project,a.out)
    except (ValueError,OSError,KeyError,zipfile.BadZipFile) as e:p.exit(2,str(e)+"\n")
    text=json.dumps(report,ensure_ascii=False,indent=2);print(text)
    if getattr(a,"report",None):a.report.write_text(text,encoding="utf-8")
    raise SystemExit(0 if report["valid"]else 2)
if __name__=="__main__": main()
