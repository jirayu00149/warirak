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
native = out/'SolidWorks'
native.mkdir(exist_ok=True)
data = json.loads((out/'CAD_parameters.json').read_text(encoding='utf-8'))
assert not data['clashes']
old_interconnect = sw.GetUserPreferenceToggle(691)
report = {'solidworks_version': sw.RevisionNumber(), 'parts': [], 'complete': False}
expected = {part['code']: part for part in data['parts']}


def typed(interface, obj):
    return interface(obj._oleobj_.QueryInterface(interface.CLSID, pythoncom.IID_IDispatch))

try:
    sw.CloseDoc('Warirak_PVC3_Frame.SLDASM' if 'frame_native' in __file__ else 'Warirak_PVC3_RevG_Full.SLDASM')
    assembly_doc = None
    if assembly_doc is None or not assembly_doc.GetTitle().startswith('Warirak_PVC3_RevG_Full_Assembly'):
        sw.SetUserPreferenceToggle(691, False)
        path = str(out/'Warirak_PVC3_RevG_Full_Assembly.step')
        assembly_doc, error = sw.LoadFile4(path, 'r', sw.GetImportFileData(path), 0)
        assert assembly_doc and error == 0
    assert assembly_doc.GetType() == 2
    assembly = typed(api.IAssemblyDoc, assembly_doc)
    assembly_path = native/'Warirak_PVC3_RevG_Full.SLDASM'
    components = assembly.GetComponents(False)
    assert len(components) == len(expected)
    identity_values = (1.,0.,0., 0.,1.,0., 0.,0.,1., 0.,0.,0., 1.,0.,0.,0.)

    for index, raw in enumerate(components, start=1):
        component = typed(api.IComponent2, raw)
        code = component.Name2.rsplit('-', 1)[0]
        assert code in expected, code
        part_doc = typed(api.IModelDoc2, component.GetModelDoc2())
        part = typed(api.IPartDoc, part_doc)
        solids = part.GetBodies2(0, False)
        assert len(solids) == expected[code]['solids'], code
        target = native/('PVC3_'+code+'.SLDPRT')
        assert part_doc.SaveAs3(str(target),0,1)==0,code
        current = tuple(typed(api.IMathTransform, component.Transform2).ArrayData)
        assert all(abs(a-b)<1e-10 for a,b in zip(current,identity_values)),(code,current)
        assembly_doc.ClearSelection2(True)
        assert component.Select4(False,None,False),code
        assembly.FixComponent()
        assembly_doc.ClearSelection2(True)
        report['parts'].append({'code':code,'file':target.name,'bytes':target.stat().st_size,
                                'solid_count':len(solids),'transform_identity':True})
        print(f'NATIVE {index}/{len(expected)} {code}',flush=True)

    assembly_doc.ForceRebuild3(False)
    assembly_doc.ShowNamedView2('*Isometric',7)
    assembly_doc.ViewZoomtofit2()
    assert assembly_doc.SaveAs3(str(assembly_path),0,1)==0
    components = assembly.GetComponents(False)
    assert len(components)==len(data['parts'])
    for raw in components:
        component = typed(api.IComponent2, raw)
        assert Path(component.GetPathName()).parent.resolve() == native.resolve()
        assert component.IsFixed()
    report.update(complete=True, assembly=assembly_path.name,
                  component_count=len(components), fixed_components=True,
                  all_references_in_package=True,
                  feature_history='Imported solid bodies; fixed assembly; no original SolidWorks sketches or mates')
finally:
    sw.SetUserPreferenceToggle(691,old_interconnect)
    (out/'SolidWorks_Verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')

verification=json.loads((out/'Verification.json').read_text(encoding='utf-8'))
verification['native_solidworks_verified']=True
verification['solidworks_component_count']=report['component_count']
(out/'Verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
print('NATIVE ASSEMBLY VERIFIED',assembly_path,flush=True)
