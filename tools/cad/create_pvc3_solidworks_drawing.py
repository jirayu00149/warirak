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

if '--boat' not in sys.argv:
    sw.CloseDoc(TARGET.name)
    template=sw.GetDocumentTemplate(3,'',6,.297,.210)
    raw=sw.NewDocument(template,12,.297,.210);assert raw
    model=typed(api.IModelDoc2,raw);assert model.GetType()==3
    draw=typed(api.IDrawingDoc,model)
    sh=typed(api.ISheet,draw.GetCurrentSheet())
    assert draw.SetupSheet6(sh.GetName(),6,13,1,5,False,'',.297,.210,'',True,.01,.01,.01,.01,0,0)
    sh.SetName('FRAME')
    ext=typed(api.IModelDocExtension,model.Extension)
    for key,val in [(263,5),(47,0),(49,2)]:assert ext.SetUserPreferenceInteger(key,0,val)
    sheet_format('FRAME ASSEMBLY',1)
    p=NATIVE/'Warirak_PVC3_Frame.SLDASM'
    top=view(p,'*Top',80,116,.2);front=view(p,'*Front',80,43,.2)
    right=view(p,'*Right',222,43,.2);iso=view(p,'*Isometric',222,130,.125)
    text('TOP 1:5',18,179,3,True);text('FRONT 1:5',20,36,3,True)
    text('RIGHT 1:5',173,36,3,True);text('ISOMETRIC 1:8',172,174,3,True)
    for kind,pts,x,y,n,label in [
        ('h',[(-240,128.05,250),(240,128.05,250)],80,55,480,'base width'),
        ('v',[(-240,128.05,-250),(-240,128.05,250)],10,116,500,'base length'),
        ('h',[(-297.975,109,-165),(297.975,109,-165)],80,187,595.95,'overall tabs width'),
        ('h',[(-220.95,128.05,-250),(220.95,128.05,-250)],80,174,441.9,'F02 cut length'),
        ('v',[(-70.475,128.05,-230.95),(-70.475,128.05,-49.05)],82,144,181.9,'F03 cut length'),
    ]:dimension(top,kind,[vertex(top,pt) for pt in pts],x,y,n,label)
    dimension(front,'v',[vertex(front,(-240,109,250)),vertex(front,(-240,128.05,250))],150,43,19.05,'SHS section')
    text('CUT LIST - SHS 19.05 x 19.05 x 1.2\nF01: 500.00 x2\nF02: 441.90 x2\nF03: 181.90 x2\nALL TUBE ENDS: 90 deg',170,94,2.7)
    text('VERIFY ACTUAL SHS, PVC3 AND U-BOLTS BEFORE FABRICATION.',10,31,2.4)
    new_sheet('FRAME_DETAILS');sheet_format('FRAME PLATES AND CUTTING DETAILS',2)
    plate=view(NATIVE/'PVC3_FRAME_F05G-R-A.SLDPRT','*Top',90,140,1)
    mount=view(NATIVE/'PVC3_FRAME_F06-R.SLDPRT','*Top',227,140,1)
    gusset=view(NATIVE/'PVC3_FRAME_F04-1-REAR.SLDPRT','*Top',227,60,2)
    text('F05G - t3 - QTY4 - 1:1',20,190,3,True)
    text('F06 - t3 - QTY2 - 1:1',191,190,3,True)
    text('F04 - t2 - QTY4 - 2:1',190,94,3,True)
    dimension(plate,'h',[vertex(plate,p) for p in [(162.975,109,-165),(297.975,109,-165)]],90,112,135,'F05G length')
    dimension(plate,'v',[vertex(plate,p) for p in [(162.975,109,-195),(162.975,109,-165)]],12,140,30,'F05G width')
    c1=circle(plate,(180.975,109,-180),3.5);c2=circle(plate,(279.975,109,-180),3.5)
    dimension(plate,'h',[c1,c2],90,166,99,'F05G hole pitch')
    dimension(plate,'d',[c2],147,177,7,'F05G hole diameter')
    dimension(mount,'h',[vertex(mount,p) for p in [(96,131.05,-17.5),(146,131.05,-17.5)]],227,107,50,'F06 length')
    dimension(mount,'v',[vertex(mount,p) for p in [(96,131.05,-62.5),(96,131.05,-17.5)]],190,140,45,'F06 width')
    c1=circle(mount,(116,131.05,-55),2.25);c2=circle(mount,(126,131.05,-55),2.25)
    dimension(mount,'h',[c1,c2],227,173,10,'F06 hole pitch')
    dimension(mount,'d',[c2],275,151,4.5,'F06 hole diameter')
    a=(200.95,128.05,-230.95);b=(220.95,128.05,-230.95);c=(220.95,128.05,-210.95)
    dimension(gusset,'h',[vertex(gusset,a),vertex(gusset,b)],227,31,20,'F04 leg X')
    dimension(gusset,'v',[vertex(gusset,b),vertex(gusset,c)],258,60,20,'F04 leg Z')
    dimension(gusset,'a',[edge(gusset,a,b),edge(gusset,a,c)],221,73,45,'F04 angle',True)
    text('SHS CUT LENGTHS (mm):\nF01 = 500.00 x2\nF02 = 441.90 x2\nF03 = 181.90 x2\nNET SHS LENGTH = 2247.60',15,88,3)
    text('IF ACTUAL SHS = 19.00: F02 = 442.00, F03 = 182.00.\nF05G HOLES: 18 FROM ENDS, 15 FROM SIDES.\nF06 HOLES: 20 / 30 FROM LEFT, 7.5 FROM REAR.\nALL PLATE CORNERS 90 deg; F04 ANGLES 90 / 45 / 45.',15,58,2.6)
    assert model.SaveAs3(str(TARGET),0,1)==0
    result=export_pdf(PDF)
    model.Save3(1,0,0)
    report={'producer':'SOLIDWORKS PDF Publisher','solidworks_version':sw.RevisionNumber(),'native_drawing':str(TARGET),'pdf':str(PDF),'sheets':list(draw.GetSheetNames()),'views':VIEWS,'dimensions':DIMENSIONS,'export_result':result}
    (REPORT/'frame_drawing_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('NATIVE FRAME DRAWING AND PDF EXPORTED',len(DIMENSIONS),flush=True)
else:
    from collections import Counter
    BOAT_NATIVE=ROOT/'outputs/Warirak_PVC3_RevG_Full/SolidWorks'
    COMBINED=BOAT_NATIVE/'Warirak_PVC3_Engineering_Set.SLDDRW'
    BOAT_PDF=ROOT/'output/pdf/Warirak_PVC3_SolidWorks_Engineering_Set.pdf'
    sw.CloseDoc(COMBINED.name)
    raw,error,warnings=sw.OpenDoc6(str(TARGET),3,1,'',0,0);assert raw and error==0
    model=typed(api.IModelDoc2,raw);draw=typed(api.IDrawingDoc,model)
    assert tuple(draw.GetSheetNames())==('FRAME','FRAME_DETAILS')
    assert model.SaveAs3(str(COMBINED),0,1)==0
    # Full assembly includes thousands of belt edges. Query only the component
    # supporting each dimension, and retain the returned native edge references.
    FILTER=None;EDGE_CACHE={}
    def entities(v):
        key=(v.Name,FILTER)
        if key not in EDGE_CACHE:
            result=[]
            for raw in v.GetVisibleComponents() or [None]:
                if raw:
                    comp=typed(api.IComponent2,raw)
                    if FILTER and FILTER not in comp.GetPathName():continue
                for e in v.GetVisibleEntities2(raw,1) or []:result.append(typed(api.IEdge,e))
            EDGE_CACHE[key]=result
        return EDGE_CACHE[key]
    def hv(v,p,hint):
        global FILTER
        FILTER=hint
        return vertex(v,p)
    def hc(v,p,r,hint):
        global FILTER
        FILTER=hint
        return circle(v,p,r)

    new_sheet('BOAT');sheet_format('COMPLETE BOAT ASSEMBLY',3)
    path=BOAT_NATIVE/'Warirak_PVC3_RevG_Full.SLDASM'
    top=view(path,'*Top',76,136,.125)
    front=view(path,'*Front',76,59,.125)
    right=view(path,'*Right',205,59,.125)
    iso=view(path,'*Isometric',210,140,.1)
    text('TOP 1:8',38,180,3,True);text('FRONT 1:8',38,32,3,True)
    text('RIGHT 1:8',165,32,3,True);text('ISOMETRIC 1:10',168,185,3,True)
    dimension(top,'h',[hv(top,(-297.975,109,-165),'F05G-L-A'),hv(top,(297.975,109,-165),'F05G-R-A')],76,90,595.95,'boat overall width')
    dimension(top,'v',[hc(top,(230.475,44.5,-305),48.5,'P02-CAP-R-STERN'),hc(top,(230.475,44.5,305),48.5,'P02-CAP-R-BOW')],23,136,610,'boat overall length')
    dimension(front,'v',[hv(front,(240,128.05,250),'F01-R'),hv(front,(101.5,337.65,-76),'Solar_5W_surface')],132,59,209.6,'frame top to solar surface')
    text('FRAME TOP TO\nSOLAR SURFACE',124,99,2.3)
    text('2 x PVC3 OD89 x600 | BELT190 / CENTRES350 / 32deg',10,194,2.6)

    new_sheet('BOAT_COMPONENTS');sheet_format('BOAT LAYOUT AND COMPONENT SCHEDULE',4)
    iso_large=view(path,'*Isometric',99,132,1/7)
    text('ISOMETRIC 1:7',12,187,3,True)
    d=json.loads((ROOT/'outputs/Warirak_PVC3_RevG_Full/CAD_parameters.json').read_text(encoding='utf-8'))
    counts=Counter(p['group'] for p in d['parts'])
    labels=[('welded_frame','STEEL FRAME F01-F06'),('pontoons','PVC3 TUBES / CAPS'),('saddles','SADDLES / RUBBER'),('clamps','U-BOLT SETS'),('propulsion_reference','MOTORS / HANGERS'),('conveyor','CONVEYOR CV-*'),('deck','DECK'),('collection','REMOVABLE BIN'),('electronics_reference','ELECTRONICS / BOXES'),('camera_reference','CAMERA / SENSOR'),('solar','SOLAR / SUPPORTS')]
    text('COMPONENT SCHEDULE',190,184,3,True)
    text('GROUP',190,176,2.6,True);text('QTY',276,176,2.6,True)
    for i,(key,label) in enumerate(labels):
        y=168-i*6
        text(label,190,y,2.5);text(str(counts[key]),279,y,2.5)
    text('TOTAL COMPONENT INSTANCES: 89',190,98,2.8,True)
    text('U-bolt set = rod +2washers +2nuts.\nCAD has 89 components /111 solid bodies.',190,91,2.4)
    text('ENVELOPE (REFERENCE): 595.95 x610 x345.65 mm\nPVC3: OD89, assumed wall2.6; raw cut600 x2.\nSOLAR: 5W18V, reference215 x180 x17 mm.\nCONVEYOR: width190, shaft centres350, incline32deg.',10,66,2.7)
    text('Prototype layout; purchased items are nominal.\nTwo pontoons selected by user; payload unrated.\nWeigh complete craft and test flotation before use.\nAt30mm freeboard, bare-pipe theory: ~5.25kg TOTAL.\nNo physical load / weld / autonomy test certified.',190,71,2.3)
    model.ClearSelection2(True);model.ForceRebuild3(False)
    assert model.SaveAs3(str(COMBINED),0,1)==0
    result=export_pdf(BOAT_PDF);model.Save3(1,0,0)
    report={'producer':'SOLIDWORKS PDF Publisher','solidworks_version':sw.RevisionNumber(),'native_drawing':str(COMBINED),'pdf':str(BOAT_PDF),'sheets':list(draw.GetSheetNames()),'new_boat_views':VIEWS,'new_boat_dimensions':DIMENSIONS,'component_schedule':dict(counts),'export_result':result}
    (REPORT/'engineering_set_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('COMPLETE NATIVE ENGINEERING SET AND PDF EXPORTED',flush=True)
