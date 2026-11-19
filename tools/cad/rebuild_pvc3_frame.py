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
sw.UserControl=True
out = ROOT/'outputs/Warirak_PVC3_RevG_Full'
native = out/'Frame_Only/SolidWorks'
native.mkdir(parents=True,exist_ok=True)
data = json.loads((out/'CAD_parameters.json').read_text(encoding='utf-8'))
assert not data['clashes']
old_interconnect = sw.GetUserPreferenceToggle(691)
report = {'solidworks_version': sw.RevisionNumber(), 'parts': [], 'complete': False}
expected = {part['code']: part for part in data['parts'] if part['group']=='welded_frame'}


def typed(interface, obj):
    return interface(obj._oleobj_.QueryInterface(interface.CLSID, pythoncom.IID_IDispatch))

model,error,warnings=sw.OpenDoc6(str(native/'Warirak_PVC3_Frame.SLDASM'),2,1,'',0,0)
assert model and error==0
assembly=typed(api.IAssemblyDoc,model)
for raw in assembly.GetComponents(False):
    comp=typed(api.IComponent2,raw)
    pd=typed(api.IModelDoc2,comp.GetModelDoc2())
    assert pd.ForceRebuild3(False)
    result=pd.Save3(1,0,0)
    assert result[0] if isinstance(result,tuple) else result
assert model.ForceRebuild3(False)
result=model.Save3(1,0,0)
assert result[0] if isinstance(result,tuple) else result
print('FRAME PARTS AND ASSEMBLY REBUILT AND SAVED',flush=True)
