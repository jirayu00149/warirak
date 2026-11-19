"""Create native SOLIDWORKS drawing views/dimensions, then export via SW PDF."""
from pathlib import Path
import sys,os,json,math
ROOT=Path(__file__).resolve().parents[2]
runtime=ROOT/'work/pvc4-cad/com-runtime'
sys.path[:0]=[str(runtime),str(runtime/'win32'),str(runtime/'win32/lib'),str(runtime/'Pythonwin')]
os.add_dll_directory(str(runtime/'pywin32_system32'))
import pythoncom,pywintypes,win32com.client
lib=pythoncom.LoadTypeLib('C:/Program Files/SOLIDWORKS Corp/SOLIDWORKS/sldworks.tlb')
a=lib.GetLibAttr();api=win32com.client.gencache.EnsureModule(a[0],a[1],a[3],a[4])
try:
    sw=api.ISldWorks(win32com.client.GetActiveObject('SldWorks.Application')._oleobj_)
except pythoncom.com_error:
    sw=api.ISldWorks(pythoncom.CoCreateInstance(pywintypes.IID('SldWorks.Application'),None,pythoncom.CLSCTX_LOCAL_SERVER,pythoncom.IID_IDispatch))
    sw.Visible=True
sw.UserControl=True
def typed(interface,obj):return interface(obj._oleobj_.QueryInterface(interface.CLSID,pythoncom.IID_IDispatch))
NATIVE=ROOT/'outputs/Warirak_PVC3_RevG_Full/Frame_Only/SolidWorks'
TARGET=NATIVE/'Warirak_PVC3_Frame_Drawing.SLDDRW'
PDF=ROOT/'output/pdf/Warirak_PVC3_Frame_SolidWorks_Drawing.pdf'
REPORT=ROOT/'work/pvc3-drawing'
REPORT.mkdir(exist_ok=True)

lib=pythoncom.LoadTypeLib('C:/Program Files/SOLIDWORKS Corp/SOLIDWORKS/swconst.tlb')
a=lib.GetLibAttr();C=win32com.client.gencache.EnsureModule(a[0],a[1],a[3],a[4]).constants
DIMENSIONS=[];VIEWS=[]

def text(txt,x,y,size=3,bold=False):
    model.ClearSelection2(True);draw.ActivateView('')
    n=typed(api.INote,model.InsertNote(txt));an=typed(api.IAnnotation,n.GetAnnotation())
    fmt=typed(api.ITextFormat,an.GetTextFormat(0));fmt.CharHeight=size/1000;fmt.TypeFaceName='Arial';fmt.Bold=bold
    assert an.SetTextFormat(0,False,fmt)
    n.SetTextJustification(1);assert an.SetPosition2(x/1000,y/1000,0)
    return n

def sheet_format(title,index):
    model.ClearSelection2(True);draw.ActivateView('');draw.EditTemplate()
    sm=typed(api.ISketchManager,model.SketchManager);sm.AddToDB=True
    for x1,y1,x2,y2 in [(5,5,292,5),(292,5,292,205),(292,205,5,205),(5,205,5,5),(5,25,292,25),(210,5,210,25),(263,5,263,25)]:
        assert sm.CreateLine(x1/1000,y1/1000,0,x2/1000,y2/1000,0)
    sm.AddToDB=False
    text('WARIRAK / '+('PVC3 SOLAR CLEANING BOAT' if index>=3 else 'PVC3 STEEL FRAME'),10,22,3,True)
    text('TSU ENGINEERING | SHS 19.05 x 19.05 x 1.2 | mm',10,13,2.5)
    text('REV G / 2026-11-07',214,22,2.5)
    text('3RD ANGLE / mm',214,13,2.5)
    text('SHEET '+str(index),266,22,2.5)
    text('A4',266,13,2.5)
    draw.EditSheet()
    text(title,10,200,4,True)

def new_sheet(name):
    assert draw.NewSheet4(name,6,13,1,5,False,'',.297,.210,'',.01,.01,.01,.01,0,0)
    assert draw.ActivateSheet(name)

def view(path,orientation,x,y,scale):
    raw=draw.CreateDrawViewFromModelView3(str(path),orientation,x/1000,y/1000,0)
    assert raw,(path,orientation)
    v=typed(api.IView,raw);v.UseSheetScale=False;v.ScaleDecimal=scale
    assert v.SetDisplayMode3(False,2,False,True)
    model.ForceRebuild3(False)
    VIEWS.append({'sheet':typed(api.ISheet,draw.GetCurrentSheet()).GetName(),'name':v.Name,'model':str(path),'orientation':orientation,'scale':scale,'outline_m':list(v.GetOutline())})
    return v

def entities(v):
    result=[]
    comps=v.GetVisibleComponents() or [None]
    for comp in comps:
        for e in v.GetVisibleEntities2(comp,1) or []:
            result.append(typed(api.IEdge,e))
    return result

def vertex(v,xyz):
    target=[i/1000 for i in xyz];found=[]
    for e in entities(v):
        for ver in [e.GetStartVertex(),e.GetEndVertex()]:
            if ver:
                ver=typed(api.IVertex,ver);pt=list(ver.GetPoint());found.append((sum((a-b)**2 for a,b in zip(pt,target)),ver,pt))
    distance,ver,pt=min(found,key=lambda q:q[0]);assert distance<1e-12,('vertex',xyz,pt,distance)
    return typed(api.IEntity,ver)

def circle(v,xyz,r):
    target=[i/1000 for i in xyz];found=[]
    for e in entities(v):
        c=typed(api.ICurve,e.GetCurve())
        if c.IsCircle():
            a=list(c.CircleParams);dist=sum((a[i]-target[i])**2 for i in range(3))+(a[6]-r/1000)**2
            found.append((dist,e,a))
    dist,e,a=min(found,key=lambda q:q[0]);assert dist<1e-12,('circle',xyz,r,a)
    return typed(api.IEntity,e)

def edge(v,a,b):
    a=[i/1000 for i in a];b=[i/1000 for i in b];found=[]
    for e in entities(v):
        p=e.GetStartVertex();q=e.GetEndVertex()
        if p and q:
            p=list(typed(api.IVertex,p).GetPoint());q=list(typed(api.IVertex,q).GetPoint())
            d=min(sum((p[i]-a[i])**2+(q[i]-b[i])**2 for i in range(3)),sum((q[i]-a[i])**2+(p[i]-b[i])**2 for i in range(3)))
            found.append((d,e))
    d,e=min(found,key=lambda q:q[0]);assert d<1e-12
    return typed(api.IEntity,e)

def dimension(v,kind,items,x,y,expected,label,angle=False):
    model.ClearSelection2(True);draw.ActivateView(v.Name)
    sm=typed(api.ISelectionMgr,model.SelectionManager);sd=typed(api.ISelectData,sm.CreateSelectData());sd.View=v
    for i,e in enumerate(items):assert e.Select4(i>0,sd)
    funcs={'h':model.AddHorizontalDimension2,'v':model.AddVerticalDimension2,'d':model.AddDiameterDimension2,'a':model.AddDimension2}
    raw=funcs[kind](x/1000,y/1000,0);assert raw,('dimension failed',label)
    dd=typed(api.IDisplayDimension,raw);dim=typed(api.IDimension,dd.GetDimension2(0))
    val=dim.SystemValue*(180/math.pi if angle else 1000)
    assert abs(val-expected)<.02,(label,val,expected)
    an=typed(api.IAnnotation,dd.GetAnnotation());fmt=typed(api.ITextFormat,an.GetTextFormat(0))
    fmt.CharHeight=.003;fmt.TypeFaceName='Arial';an.SetTextFormat(0,False,fmt)
    dd.ShowParenthesis=False
    DIMENSIONS.append({'sheet':typed(api.ISheet,draw.GetCurrentSheet()).GetName(),'label':label,'native_measured_value':val,'unit':'deg' if angle else 'mm','no_value_override':True})
    model.ClearSelection2(True)
    print('NATIVE DIMENSION',label,round(val,4),flush=True)
    return dd

def export_pdf(path):
    active,error=sw.ActivateDoc3(model.GetTitle(),False,0,0)
    assert active and error==0
    model.ClearSelection2(True);model.ForceRebuild3(False)
    data=typed(api.IExportPdfData,sw.GetExportFileData(1))
    names=win32com.client.VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_BSTR,tuple(draw.GetSheetNames()))
    assert data.SetSheets(3,names)
    data.ViewPdfAfterSaving=False
    key=getattr(C,'swPDFExportInColor',None);old=None
    if key is not None:old=sw.GetUserPreferenceToggle(key);sw.SetUserPreferenceToggle(key,False)
    try:
        result=typed(api.IModelDocExtension,model.Extension).SaveAs(str(path),0,1,data,0,0)
        assert result[0] and result[1]==0,result
    finally:
        if key is not None:sw.SetUserPreferenceToggle(key,old)
    return result


import shutil
base=ROOT/'outputs/Warirak_PVC3_RevG_Full'
stage=ROOT/'outputs/Warirak_PVC3_SolidWorks_Complete';stage.mkdir(exist_ok=True)
sources=[]
for folder in [base/'SolidWorks',base/'Frame_Only/SolidWorks']:
 sources.extend(p for p in folder.iterdir() if p.is_file() and not p.name.startswith('~$') and p.suffix.upper() in ['.SLDPRT','.SLDASM','.SLDDRW'])
assert len(sources)==109,len(sources)
mapping={str(p.resolve()):stage/('PKG_'+p.name) for p in sources}
for source,target in mapping.items():shutil.copy2(source,target)
full=base/'SolidWorks/Warirak_PVC3_RevG_Full.SLDASM';frame=base/'Frame_Only/SolidWorks/Warirak_PVC3_Frame.SLDASM'
data=json.loads((base/'CAD_parameters.json').read_text(encoding='utf-8'))
graph={str(full.resolve()):[str((base/'SolidWorks'/('PVC3_'+p['code']+'.SLDPRT')).resolve()) for p in data['parts']],str(frame.resolve()):[str((base/'Frame_Only/SolidWorks'/('PVC3_FRAME_'+p['code']+'.SLDPRT')).resolve()) for p in data['parts'] if p['group']=='welded_frame']}
audits=json.loads((REPORT/'native_drawing_audit.json').read_text(encoding='utf-8'))
for item in audits:graph[str(Path(item['drawing']).resolve())]=sorted({str(Path(v['model']).resolve()) for v in item['views']})
changes=[]
for parent,children in graph.items():
 for child in children:
  assert child in mapping,child
  ok=sw.ReplaceReferencedDocument(str(mapping[parent]),child,str(mapping[child]))
  assert ok,(parent,child)
  changes.append({'parent':mapping[parent].name,'reference':mapping[child].name})
 print('RELINKED',mapping[parent].name,len(children),flush=True)
main=stage/'PKG_Warirak_PVC3_Engineering_Set.SLDDRW'
raw,e,w=sw.OpenDoc6(str(main),3,1,'',0,0);assert raw and e==0,(e,w)
model=typed(api.IModelDoc2,raw);draw=typed(api.IDrawingDoc,model)
assert len(draw.GetSheetNames())==4
views=[]
for name in draw.GetSheetNames():
 draw.ActivateSheet(name)
 v=typed(api.IView,draw.GetFirstView()).GetNextView()
 while v:
  v=typed(api.IView,v);path=Path(v.GetReferencedModelName())
  assert path.parent.resolve()==stage.resolve(),path
  ref=typed(api.IModelDoc2,v.ReferencedDocument)
  assert Path(ref.GetPathName()).parent.resolve()==stage.resolve(),ref.GetPathName()
  views.append({'sheet':name,'view':v.Name,'reference':path.name})
  v=v.GetNextView()
assert len(views)==12
assert model.ForceRebuild3(False)
model.Save3(1,0,0)
report={'package':'Native SOLIDWORKS files with references rewritten through ReplaceReferencedDocument','stage':str(stage),'native_file_count':len(sources),'relinked_reference_count':len(changes),'drawing_opened_from_delivery_folder':True,'drawing_open_warnings':w,'view_references_local':views,'changes':changes}
(REPORT/'delivery_reference_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('DELIVERY DRAWING VERIFIED: 4 SHEETS,12 VIEWS,ALL LOCAL REFERENCES',flush=True)
