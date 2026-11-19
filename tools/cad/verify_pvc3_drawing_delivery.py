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


stage=ROOT/'outputs/Warirak_PVC3_SolidWorks_Complete'
results=[]
for name,expected_views,expected_dims in [('PKG_Warirak_PVC3_Frame_Drawing.SLDDRW',7,17),('PKG_Warirak_PVC3_Engineering_Set.SLDDRW',12,20)]:
 raw,e,w=sw.OpenDoc6(str(stage/name),3,1,'',0,0);assert raw and e==0
 model=typed(api.IModelDoc2,raw);draw=typed(api.IDrawingDoc,model)
 records=[];dims=[]
 for sheetname in draw.GetSheetNames():
  draw.ActivateSheet(sheetname)
  v=typed(api.IView,draw.GetFirstView()).GetNextView()
  while v:
   v=typed(api.IView,v);ref=typed(api.IModelDoc2,v.ReferencedDocument)
   assert Path(ref.GetPathName()).parent.resolve()==stage.resolve()
   records.append({'sheet':sheetname,'view':v.Name,'reference':Path(ref.GetPathName()).name})
   dd=v.GetFirstDisplayDimension5()
   while dd:
    dd=typed(api.IDisplayDimension,dd);dim=typed(api.IDimension,dd.GetDimension2(0));ann=typed(api.IAnnotation,dd.GetAnnotation())
    dangling=getattr(ann,'IsDangling',False);dangling=dangling() if callable(dangling) else dangling
    assert not dangling,dim.FullName
    dims.append({'name':dim.FullName,'system_value':dim.SystemValue,'dangling':False})
    dd=dd.GetNext5()
   v=v.GetNextView()
 assert len(records)==expected_views and len(dims)==expected_dims,(len(records),len(dims))
 results.append({'drawing':name,'sheet_count':len(draw.GetSheetNames()),'views':records,'dimensions':dims,'open_warning':w})
 print('VERIFIED PACKAGED DRAWING',name,len(records),len(dims),flush=True)
for name,count in [('PKG_Warirak_PVC3_Frame.SLDASM',16),('PKG_Warirak_PVC3_RevG_Full.SLDASM',89)]:
 raw,e,w=sw.OpenDoc6(str(stage/name),2,1,'',0,0);assert raw and e==0
 asm=typed(api.IAssemblyDoc,raw);comps=asm.GetComponents(False);assert len(comps)==count
 for c in comps:
  c=typed(api.IComponent2,c)
  assert Path(c.GetPathName()).parent.resolve()==stage.resolve()
  assert c.GetModelDoc2() is not None
 print('VERIFIED PACKAGED ASSEMBLY',name,count,flush=True)
(REPORT/'packaged_drawing_audit.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
raw,e,w=sw.OpenDoc6(str(stage/'PKG_Warirak_PVC3_Engineering_Set.SLDDRW'),3,1,'',0,0)
model=typed(api.IModelDoc2,raw);draw=typed(api.IDrawingDoc,model)
sw.ActivateDoc3(model.GetTitle(),False,0,0);draw.ActivateSheet('BOAT');model.ViewZoomtofit2();model.Save3(1,0,0)
