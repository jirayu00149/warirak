"""Save the Rev H assembly as a portable SolidWorks assembly, in a hidden session."""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
runtime = ROOT / "work/pvc4-cad/com-runtime"
sys.path[:0] = [str(p) for p in (runtime, runtime/"win32", runtime/"win32/lib", runtime/"Pythonwin")]
dll = os.add_dll_directory(str(runtime/"pywin32_system32"))
import pythoncom
import pywintypes
import win32com.client

NAME = "Warirak_PVC3_ABC2215_RevH"
OUT = ROOT / "output" / NAME
native = OUT / "SolidWorks"
native.mkdir(exist_ok=True)
data = json.loads((OUT / "CAD_Check.json").read_text(encoding="utf-8"))
base = json.loads((ROOT/"outputs/Warirak_PVC3_RevG_Full/CAD_parameters.json").read_text(encoding="utf-8"))
solids = {p["code"]: p["solids"] for p in [*base["parts"], *data["records"]]}
solids["E05-3S-PACK-REFERENCE"] = 1

lib = pythoncom.LoadTypeLib("C:/Program Files/SOLIDWORKS Corp/SOLIDWORKS/sldworks.tlb")
attr = lib.GetLibAttr()
api = win32com.client.gencache.EnsureModule(attr[0], attr[1], attr[3], attr[4])
try:
    win32com.client.GetActiveObject("SldWorks.Application")
except pythoncom.com_error:
    pass
else:
    raise SystemExit("Existing interactive SolidWorks session detected. Use the STEP file.")

sw = api.ISldWorks(pythoncom.CoCreateInstance(
    pywintypes.IID("SldWorks.Application"), None, pythoncom.CLSCTX_LOCAL_SERVER, pythoncom.IID_IDispatch
))
sw.Visible = False
old_interconnect = sw.GetUserPreferenceToggle(691)
report = {"complete": False, "parts": []}


def typed(interface, obj):
    return interface(obj._oleobj_.QueryInterface(interface.CLSID, pythoncom.IID_IDispatch))


try:
    sw.DocumentVisible(False, 1)
    sw.DocumentVisible(False, 2)
    sw.SetUserPreferenceToggle(691, False)
    source = str(OUT/f"{NAME}.step")
    print(f"Importing {data['component_count']} STEP components", flush=True)
    doc, error = sw.LoadFile4(source, "r", sw.GetImportFileData(source), 0)
    assert doc and error == 0 and doc.GetType() == 2, error
    assembly = typed(api.IAssemblyDoc, doc)
    components = assembly.GetComponents(False)
    assert len(components) == data["component_count"], len(components)
    for index, raw in enumerate(components, 1):
        component = typed(api.IComponent2, raw)
        code = component.Name2.rsplit("-", 1)[0]
        part_doc = typed(api.IModelDoc2, component.GetModelDoc2())
        count = len(typed(api.IPartDoc, part_doc).GetBodies2(0, False))
        assert count == solids[code], (code, count, solids[code])
        file = native / f"{code}.SLDPRT"
        assert part_doc.SaveAs3(str(file), 0, 1) == 0, code
        doc.ClearSelection2(True)
        assert component.Select4(False, None, False), code
        assembly.FixComponent()
        report["parts"].append({"code":code, "file":file.name, "solid_count":count})
        if index % 20 == 0:
            print(f"Saved {index}/{len(components)} parts", flush=True)
    doc.ClearSelection2(True)
    doc.ForceRebuild3(False)
    file = native/f"{NAME}.SLDASM"
    assert doc.SaveAs3(str(file), 0, 1) == 0
    for raw in assembly.GetComponents(False):
        component = typed(api.IComponent2, raw)
        path = Path(component.GetPathName()).resolve()
        assert path.is_file() and path.parent == native.resolve(), path
        assert component.IsFixed(), component.Name2
    report.update(complete=True, assembly=file.name, component_count=len(components),
                  solid_count=sum(row["solid_count"] for row in report["parts"]),
                  feature_history="Native files with imported solids and fixed positions")
    # Remove in-memory references before opening the package at another path.
    sw.CloseAllDocuments(True)
    with tempfile.TemporaryDirectory(prefix="warirak-abc2215-portability-") as scratch:
        copied = Path(scratch) / "SolidWorks"
        shutil.copytree(native, copied)
        reopened, error, warning = sw.OpenDoc6(str(copied/file.name), 2, 1, "", 0, 0)
        assert reopened and not error, (error, warning)
        loaded = typed(api.IAssemblyDoc, reopened).GetComponents(False)
        assert len(loaded) == len(components)
        for raw in loaded:
            component = typed(api.IComponent2, raw)
            part = Path(component.GetPathName()).resolve()
            assert part.parent == copied.resolve() and part.is_file(), part
            assert component.GetModelDoc2() is not None
        rebuilt = reopened.ForceRebuild3(False)
        assert rebuilt
        report.update(copied_folder_opened=True, copied_folder_load_warnings=warning, copied_folder_rebuilt=True)
        sw.CloseAllDocuments(True)
finally:
    sw.SetUserPreferenceToggle(691, old_interconnect)
    (OUT/"SolidWorks_Check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    sw.ExitApp()
