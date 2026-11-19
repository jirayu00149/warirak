"""Convert this task's verified STEP components into SolidWorks 2023 files."""
from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[2]
runtime = ROOT / 'work/pvc4-cad/com-runtime'
sys.path[:0] = [str(runtime), str(runtime/'win32'), str(runtime/'win32/lib'), str(runtime/'Pythonwin')]
os.add_dll_directory(str(runtime/'pywin32_system32'))
import pythoncom
import pywintypes
import win32com.client

lib = pythoncom.LoadTypeLib('C:/Program Files/SOLIDWORKS Corp/SOLIDWORKS/sldworks.tlb')
attr = lib.GetLibAttr()
api = win32com.client.gencache.EnsureModule(attr[0], attr[1], attr[3], attr[4])
try:
    sw = api.ISldWorks(win32com.client.GetActiveObject('SldWorks.Application')._oleobj_)
except pythoncom.com_error:
    sw = api.ISldWorks(pythoncom.CoCreateInstance(pywintypes.IID('SldWorks.Application'),None,pythoncom.CLSCTX_LOCAL_SERVER,pythoncom.IID_IDispatch))
    sw.Visible = True
out = ROOT/'outputs/Warirak_PVC4_RevF_Full'
native = out/'SolidWorks'
native.mkdir(exist_ok=True)
data = json.loads((out/'CAD_parameters.json').read_text(encoding='utf-8'))
assert not data['clashes']
old_interconnect = sw.GetUserPreferenceToggle(691)
report = {'solidworks_version': sw.RevisionNumber(), 'parts': [], 'complete': False}
expected = {part['code']: part for part in data['parts']}


def typed(interface, obj):
    return interface(obj._oleobj_.QueryInterface(interface.CLSID, pythoncom.IID_IDispatch))


current=typed(api.IModelDoc2,sw.ActiveDoc)
assert current.GetPathName()==str(native/'Warirak_PVC4_RevF_Full.SLDASM')
sw.CloseDoc(current.GetTitle())
old=sw.GetUserPreferenceToggle(691)
try:
    sw.SetUserPreferenceToggle(691,False)
    path=str(out/'Parts_STEP/C02-CAMERA-REFERENCE.step')
    model,error=sw.LoadFile4(path,'r',sw.GetImportFileData(path),0)
    assert model and error==0
    assert model.SaveAs3(str(native/'C02-CAMERA-REFERENCE.SLDPRT'),0,1)==0
    sw.CloseDoc(model.GetTitle())
finally:
    sw.SetUserPreferenceToggle(691,old)
model,error,warnings=sw.OpenDoc6(str(native/'Warirak_PVC4_RevF_Full.SLDASM'),2,1,'',0,0)
assert model and error==0
assembly=typed(api.IAssemblyDoc,model)
checks=[]
for raw in assembly.GetComponents(False):
    comp=typed(api.IComponent2,raw)
    code=comp.Name2.rsplit('-',1)[0]
    pd=typed(api.IPartDoc,comp.GetModelDoc2())
    bodies=pd.GetBodies2(0,False)
    volumes=[typed(api.IBody2,b).GetMassProperties(1)[3]*1e9 for b in bodies]
    measured=sum(volumes)
    target=expected[code]['volume_mm3']
    assert abs(measured-target)<=max(.1,target*1e-3),(code,measured,target)
    checks.append({'code':code,'volume_mm3':measured,'matches_step':True})
assert len(checks)==len(expected)
model.ForceRebuild3(False)
model.ShowNamedView2('*Isometric',7)
model.ViewZoomtofit2()
model.Save3(1,0,0)
verification=json.loads((out/'Verification.json').read_text(encoding='utf-8'))
verification.update(native_solidworks_verified=True,solidworks_component_count=len(checks))
(out/'Verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
(out/'Native_Volume_Verification.json').write_text(json.dumps({'all_match':True,'relative_volume_tolerance':0.001,'absolute_volume_tolerance_mm3':0.1,'note':'STEP-to-SolidWorks healing may slightly change volume','components':checks},indent=2),encoding='utf-8')
print('ALL NATIVE VOLUMES MATCH FINAL STEP',len(checks),flush=True)
