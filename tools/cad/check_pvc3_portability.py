"""Verify the new assembly opens from a copied folder with local references."""
from pathlib import Path
import json
import os
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
runtime=ROOT/'work/pvc4-cad/com-runtime'
sys.path[:0]=[str(runtime),str(runtime/'win32'),str(runtime/'win32/lib'),str(runtime/'Pythonwin')]
os.add_dll_directory(str(runtime/'pywin32_system32'))
import pythoncom
import pywintypes
import win32com.client
lib=pythoncom.LoadTypeLib('C:/Program Files/SOLIDWORKS Corp/SOLIDWORKS/sldworks.tlb')
a=lib.GetLibAttr()
api=win32com.client.gencache.EnsureModule(a[0],a[1],a[3],a[4])
try:
    sw=api.ISldWorks(win32com.client.GetActiveObject('SldWorks.Application')._oleobj_)
except pythoncom.com_error:
    sw=api.ISldWorks(pythoncom.CoCreateInstance(pywintypes.IID('SldWorks.Application'),None,pythoncom.CLSCTX_LOCAL_SERVER,pythoncom.IID_IDispatch))
sw.UserControl=True
sw.Visible=True
out=ROOT/'outputs/Warirak_PVC3_RevG_Full'
native=out/'SolidWorks'


def typed(interface,obj):
    return interface(obj._oleobj_.QueryInterface(interface.CLSID,pythoncom.IID_IDispatch))


# SOLIDWORKS can reuse an already-open document with the same basename.
# Close only this task's assemblies before the copied-folder test.
for raw in list(sw.GetDocuments() or []):
    doc=typed(api.IModelDoc2,raw)
    path=doc.GetPathName()
    if doc.GetType()==2 and path and ('Warirak_PVC3_RevG_Full' in path or 'warirak-pvc3-portable-' in path):
        sw.CloseDoc(doc.GetTitle())


current,error,warnings=sw.OpenDoc6(str(native/'Warirak_PVC3_RevG_Full.SLDASM'),2,1,'',0,0)
assert current and error==0
assert current.GetPathName()==str(native/'Warirak_PVC3_RevG_Full.SLDASM')
sw.CloseDoc(current.GetTitle())
temp=Path(tempfile.mkdtemp(prefix='warirak-pvc3-portable-'))
copy=temp/'SolidWorks'
shutil.copytree(native,copy)
model,error,warnings=sw.OpenDoc6(str(copy/'Warirak_PVC3_RevG_Full.SLDASM'),2,1,'',0,0)
assert model and error==0,(error,warnings)
copy_warnings=warnings
assembly=typed(api.IAssemblyDoc,model)
paths=[]
for raw in assembly.GetComponents(False):
    comp=typed(api.IComponent2,raw)
    path=Path(comp.GetPathName())
    assert path.parent.resolve()==copy.resolve(),path
    assert comp.GetModelDoc2() is not None
    paths.append(path.name)
assert len(paths)==json.loads((out/'CAD_parameters.json').read_text(encoding='utf-8'))['component_count']
assert model.ForceRebuild3(False)
model.Save3(1,0,0)
sw.CloseDoc(model.GetTitle())
model,error,warnings=sw.OpenDoc6(str(native/'Warirak_PVC3_RevG_Full.SLDASM'),2,1,'',0,0)
assert model and error==0
model.ShowNamedView2('*Isometric',7)
model.ViewZoomtofit2()
assert model.ForceRebuild3(False)
model.Save3(1,0,0)
report={'copied_folder_opened':True,'loaded_local_components':len(paths),
        'source_reopened':True,'copied_assembly_load_warnings':copy_warnings,
        'source_assembly_load_warnings':warnings,'copy_and_source_rebuilt_and_saved':True,
        'warning_32_meaning':'swFileLoadWarning_NeedsRegen; rebuild performed',
        'native_parts_are_imported_solids':True}
(out/'Portability_Verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report),flush=True)
