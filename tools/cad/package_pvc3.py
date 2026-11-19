from pathlib import Path
import csv, hashlib, json, shutil, zipfile
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[2]
out=ROOT/'outputs/Warirak_PVC3_RevG_Full';frame=out/'Frame_Only'
data=json.loads((out/'CAD_parameters.json').read_text(encoding='utf-8'))
assert len(data['parts'])==89 and not data['clashes']
def files(folder):
    return sorted(p for p in folder.rglob('*') if p.is_file() and not p.name.startswith('~$'))
for folder,count in [(out,89),(frame,16)]:
    native=json.loads((folder/'SolidWorks_Verification.json').read_text(encoding='utf-8'))
    portable=json.loads((folder/'Portability_Verification.json').read_text(encoding='utf-8'))
    assert native['complete'] and native['component_count']==count
    assert portable['copied_folder_opened'] and portable['loaded_local_components']==count
    assert portable['copied_assembly_load_warnings'] & ~32 == 0
    if portable['copied_assembly_load_warnings'] & 32:
        assert portable['copy_and_source_rebuilt_and_saved']
    assert len([p for p in files(folder/'SolidWorks') if p.suffix.upper()=='.SLDPRT'])==count
for p in data['parts']:
    assert (out/p['file']).is_file()
    if p['group']=='welded_frame':shutil.copy2(out/p['file'],frame/'Parts_STEP'/Path(p['file']).name)
with (out/'Cut_List_mm.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.reader(f))
with (frame/'Frame_Cut_List_mm.csv').open('w',encoding='utf-8-sig',newline='') as f:csv.writer(f).writerows([rows[0]]+[r for r in rows[1:] if r[0].startswith('F')])
for name in ['frame_reference','frame_assembled','frame_exploded']:shutil.copy2(out/'images'/(name+'.png'),frame/(name+'.png'))
for name,n in [('Warirak_PVC3_Frame_A4.pdf',2),('Warirak_PVC3_Full_Three_Rounds_A4.pdf',4)]:
    shutil.copy2(ROOT/'output/pdf'/name,out/name)
    assert len(PdfReader(out/name).pages)==n
shutil.copy2(out/'Warirak_PVC3_Frame_A4.pdf',frame/'Warirak_PVC3_Frame_A4.pdf')
plan=json.loads((out/'Purchase_Plan.json').read_text(encoding='utf-8'))
assert sum(p['low'] for p in plan['rows'])==7285
assert [sum(p['low'] for p in plan['rows'] if p['round']==i) for i in range(1,4)]==[700,566,6019]
for package in [frame,out]:
    paths=[p for p in files(package) if p.name!='SHA256SUMS.txt']
    (package/'SHA256SUMS.txt').write_text('\n'.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(package).as_posix() for p in paths)+'\n',encoding='utf-8')
for package,name,prefix in [(frame,'Warirak_PVC3_Frame_Only.zip','Warirak_PVC3_Frame_Only'),(out,'Warirak_PVC3_RevG_Full.zip','Warirak_PVC3_RevG_Full')]:
    dest=ROOT/'outputs'/name
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for p in files(package):z.write(p,prefix+'/'+p.relative_to(package).as_posix())
    with zipfile.ZipFile(dest) as z:assert z.testzip() is None
    print(dest.name,'bytes',dest.stat().st_size,'SHA256',hashlib.sha256(dest.read_bytes()).hexdigest(),flush=True)
summary={'full_native_components':89,'frame_native_components':16,'native_reference_portability':'both verified with local references from copied folders; full warning0, frame warning32 NeedsRegen with rebuild/save performed','cad_clashes':0,'physical_tests':False,'purchase_total_thb':7285,'pdf_pages':[2,4]}
(ROOT/'work/PVC3_DELIVERY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary),flush=True)
