"""Rev G: two PVC3 pontoons and 3/4in SHS x1.2. Nominal fit model, mm."""
from pathlib import Path
import csv,json,math,shutil,sys
OLD=Path('C:/Users/Administrator/Documents/Codex/2026-10-22/solid-mini-prototype-scale-model-350')
sys.path.insert(0,str(OLD/'work/cad_runtime_b'))
import cadquery as cq
from cadquery import Vector as V
import ezdxf

ROOT=Path(__file__).resolve().parents[2]
MODEL='Warirak_PVC3_RevG_Full'
OUT=Path(sys.argv[sys.argv.index('--output')+1]).resolve() if '--output' in sys.argv else ROOT/'outputs'/MODEL
SRC=Path(__file__).resolve().parent
PREV=ROOT/'outputs/Warirak_PVC4_RevF_Full'
for sub in ['Parts_STEP','DXF_mm','images','source','Frame_Only/Parts_STEP','Frame_Only/DXF_mm']:(OUT/sub).mkdir(parents=True,exist_ok=True)
B,T,W,L=19.05,1.2,480.,500.
BOTTOM=109.;TOP=BOTTOM+B;DY=TOP-154.
R,WALL=44.5,2.6
RAIL=(W-B)/2
PITCH=99.;PW=135.
BLUE=(.04,.45,.78);STEEL=(.31,.36,.39);GRAY=(.62,.67,.68);TEAL=(.08,.50,.43);BLACK=(.10,.14,.16)
PARTS=[];reused=[]
def box(w,h,d,x,y,z):return cq.Workplane('XY').box(w,h,d).val().translate((x,y,z))
def cyl(r,length,x,y,z,axis=(0,0,1)):return cq.Solid.makeCylinder(r,length,V(x,y,z),V(*axis))
def add(code,shape,group,material,color,exploded,note=''):
    assert shape.isValid() and shape.Volume()>0,code
    PARTS.append(dict(code=code,shape=shape,group=group,material=material,color=color,exploded=exploded,note=note))
def tube(w,h,d,x,y,z,axis):
    inner=[w-2*T,h-2*T,d-2*T];inner[{'x':0,'y':1,'z':2}[axis]]+=2*T+2
    return box(w,h,d,x,y,z).cut(box(*inner,x,y,z)).clean()

# Preserve the outside 480x500 base and rear-bay front face at Z=-30.
rear=-L/2+B/2;mid=-30-B/2;clear=W-2*B;runner=220-2*B
for side,sign in [('L',-1),('R',1)]:
    add('F01-'+side,tube(B,B,L,sign*RAIL,BOTTOM+B/2,0,'z'),'welded_frame','steel',STEEL,(sign*90,0,0),'3/4in=19.05 nominal; measure actual tube before cutting')
for name,z,ez in [('REAR',rear,-75),('MID',mid,75)]:
    add('F02-'+name,tube(clear,B,B,0,BOTTOM+B/2,z,'x'),'welded_frame','steel',STEEL,(0,0,ez),'Cut length=480-2*actual_section')
for side,sign in [('L',-1),('R',1)]:
    add('F03-'+side,tube(B,B,runner,sign*80,BOTTOM+B/2,-140,'z'),'welded_frame','steel',STEEL,(sign*35,80,0),'Cut length=220-2*actual_section')
for sign in [-1,1]:
    for z,dz,name in [(-250+B,1,'REAR'),(-30-B,-1,'MID')]:
        x=sign*(240-B)
        wire=cq.Wire.makePolygon([V(x,TOP-2,z),V(x-sign*20,TOP-2,z),V(x,TOP-2,z+dz*20),V(x,TOP-2,z)])
        add(f'F04-{sign}-{name}',cq.Solid.extrudeLinear(wire,[],V(0,2,0)),'welded_frame','steel',STEEL,(sign*40,110,0),'triangle20x20 t2; 90/45/45deg')
for side,sign in [('L',-1),('R',1)]:
    plate=box(50,3,45,sign*121,TOP+1.5,-40)
    for x in [sign*116,sign*126]:plate=plate.cut(cyl(2.25,5,x,TOP-1,-55,(0,1,0)))
    add('F06-'+side,plate.clean(),'welded_frame','steel',STEEL,(sign*20,75,25),'Original plate50x45x3, holes4.5 pitch10')

for side,sign in [('L',-1),('R',1)]:
    x=sign*RAIL
    pipe=cyl(R,600,x,R,-300).cut(cyl(R-WALL,602,x,R,-301)).clean()
    add('P01-PVC3-'+side,pipe,'pontoons','PVC',BLUE,(sign*150,-35,0),'OD89; assumed wall2.6; raw cut600; measure actual Class5 pipe')
    for direction,tag in [(1,'BOW'),(-1,'STERN')]:
        z=273*direction
        cap=cyl(48.5,32,x,R,z,(0,0,direction)).cut(cyl(R+.2,27.1,x,R,z-direction*.1,(0,0,direction))).clean()
        add('P02-CAP-'+side+'-'+tag,cap,'pontoons','PVC',BLUE,(sign*150,-35,direction*80),'Nominal reference OD97,length32,socket27,endwall5; bought cap fit pending')
    for z,station in [(-180,'A'),(120,'B')]:
        plate=box(PW,3,30,x,BOTTOM-1.5,z)
        for dx in [-PITCH/2,PITCH/2]:plate=plate.cut(cyl(3.5,5,x+dx,BOTTOM-4,z,(0,1,0)))
        add(f'F05G-{side}-{station}',plate.clean(),'welded_frame','steel',STEEL,(sign*80,65,0),'135x30x3, holes7 pitch99; match actual PVC3 U-bolt')
        saddle=box(80,24,30,x,94,z).cut(cyl(46.5,32,x,R,z-16)).clean()
        add(f'S01-SADDLE-{side}-{station}',saddle,'saddles','HDPE_or_sealed_wood',TEAL,(sign*100,15,0),'Top106; stock80x30x24; recessR46.5')
        rubber=cyl(46.5,30,x,R,z-15).cut(cyl(R,32,x,R,z-16)).intersect(box(80,40,30,x,85,z)).clean()
        add(f'S02-RUBBER-{side}-{station}',rubber,'saddles','rubber',BLACK,(sign*110,-10,0),'Nominal2mm liner; compression not simulated')
        path=cq.Workplane('XY').moveTo(x-PITCH/2,118).lineTo(x-PITCH/2,R).threePointArc((x,-5),(x+PITCH/2,R)).lineTo(x+PITCH/2,118)
        rod=cq.Workplane('XZ',origin=(x-PITCH/2,118,0)).circle(3).sweep(path).val().translate((0,0,z))
        hardware=[rod]
        for dx in [-PITCH/2,PITCH/2]:
            washer=cyl(8,1.5,x+dx,BOTTOM,z,(0,1,0)).cut(cyl(3.4,2,x+dx,BOTTOM-.2,z,(0,1,0)))
            nut=cq.Workplane('XZ',origin=(x+dx,BOTTOM+6.5,z)).polygon(6,11.55).extrude(5).val().cut(cyl(3.4,7,x+dx,BOTTOM+.5,z,(0,1,0)))
            hardware.extend([washer.clean(),nut.clean()])
        add(f'H01-UBOLT-M6-{side}-{station}',cq.Compound.makeCompound(hardware),'clamps','stainless_steel',GRAY,(sign*130,-45,0),'Five-body reference set: M6 rod,2washers,2nuts. Leg pitch99; vendor fit pending')

# Keep the checked conveyor, deck, electronics and solar layout relative to the frame top.
seed_manifest=SRC/'seed_manifest.json'
records=json.loads(seed_manifest.read_text(encoding='utf-8')) if seed_manifest.exists() else json.loads((PREV/'CAD_parameters.json').read_text(encoding='utf-8'))['parts']
seeds=SRC/'seed_components' if (SRC/'seed_components').exists() else PREV/'Parts_STEP'
for p in records:
    if p['group'] in ['welded_frame','pontoons','saddles','clamps']:continue
    shift=-25. if p['group']=='propulsion_reference' else DY
    shape=cq.importers.importStep(str(seeds/(p['code']+'.step'))).val().translate((0,shift,0))
    add(p['code'],shape,p['group'],p['material'],p['color'],p['exploded'],'RevG layout shifted with new frame top. '+p.get('note',''))
    reused.append({k:p[k] for k in ['code','group','material','color','exploded','note']})

assy=cq.Assembly(name=MODEL);exp=cq.Assembly(name=MODEL+'_Exploded');fa=cq.Assembly(name=MODEL+'_Frame');fe=cq.Assembly(name=MODEL+'_Frame_Exploded')
manifest=[]
for p in PARTS:
    s=p['shape'];name=p['code'];target=OUT/'Parts_STEP'/(name+'.step')
    cq.exporters.export(s,str(target));assy.add(s,name=name,color=cq.Color(*p['color']));exp.add(s,name=name,color=cq.Color(*p['color']),loc=cq.Location(V(*p['exploded'])))
    if p['group']=='welded_frame':
        fa.add(s,name=name,color=cq.Color(*p['color']));fe.add(s,name=name,color=cq.Color(*p['color']),loc=cq.Location(V(*p['exploded'])))
        shutil.copy2(target,OUT/'Frame_Only/Parts_STEP'/target.name)
    b=s.BoundingBox();vs,fs=s.tessellate(.6,.25)
    manifest.append({k:v for k,v in p.items() if k!='shape'}|{'file':'Parts_STEP/'+target.name,'solids':len(s.Solids()),'volume_mm3':s.Volume(),'bounds_mm':[b.xmin,b.ymin,b.zmin,b.xmax,b.ymax,b.zmax],'mesh':{'vertices':[[v.x,v.y,v.z] for v in vs],'triangles':fs}})
for a,suffix in [(assy,'Assembly'),(exp,'Exploded'),(fa,'Frame'),(fe,'Frame_Exploded')]:
    file=OUT/(MODEL+'_'+suffix+'.step');a.export(str(file));s=cq.importers.importStep(str(file)).val();assert s.isValid();print('STEP VERIFIED',suffix,len(s.Solids()),flush=True)
    if suffix.startswith('Frame'):shutil.copy2(file,OUT/'Frame_Only'/('Warirak_PVC3_'+suffix+'.step'))
clashes=[]
for i,p in enumerate(PARTS):
    a=p['shape'].BoundingBox()
    for q in PARTS[i+1:]:
        b=q['shape'].BoundingBox()
        if a.xmax<=b.xmin+.001 or b.xmax<=a.xmin+.001 or a.ymax<=b.ymin+.001 or b.ymax<=a.ymin+.001 or a.zmax<=b.zmin+.001 or b.zmax<=a.zmin+.001:continue
        overlap=p['shape'].intersect(q['shape']).Volume()
        if overlap>.01:clashes.append({'parts':[p['code'],q['code']],'overlap_mm3':overlap})
full=math.pi*R**2*600*2/1e6
def displacement(freeboard):
    h=2*R-freeboard
    area=R**2*math.acos((R-h)/R)-(R-h)*math.sqrt(max(0,2*R*h-h*h))
    return area*600*2/1e6
params={'revision':'G','assembly_name':MODEL,'full_conveyor_solar':True,'units':'mm','axes':{'X':'right','Y':'up','Z':'bow'},'pipe':{'OD':89,'wall_assumed':WALL,'cut_length':600,'quantity':2,'x_centers':[-RAIL,RAIL]},'cap_reference':{'OD':97,'length':32,'engagement':27,'quantity':4},'nominal_overall_mm':{'width_including_tabs':2*(RAIL+PW/2),'pipe_caps_length':610},'frame_mm':{'width':W,'length':L,'section':B,'wall':T,'bottom_y':BOTTOM,'top_y':TOP},'F05G':{'size':[PW,30,3],'hole_diameter':7,'pitch':PITCH,'x_centers':[-RAIL,RAIL],'z_stations':[-180,120]},'crossbeam_center_z':[rear,mid],'crossbeam_cut':clear,'runner_cut':runner,'component_count':len(PARTS),'clashes':clashes,'parts':manifest,'bare_pipe_full_displacement_liters':full,'bare_pipe_half_immersed_displacement_kg':full/2,'bare_pipe_mass_limit_for_30mm_freeboard_kg':displacement(30),'physical_tests':False,'payload_certified_kg':None,'fabrication_status':'User chose two3in pontoons. Weight-limited layout; flotation and structural tests pending.'}
(OUT/'CAD_parameters.json').write_text(json.dumps(params,ensure_ascii=False,indent=2),encoding='utf-8')
verification={'component_count':len(PARTS),'solid_count':sum(p['solids'] for p in manifest),'valid_step_roundtrip':True,'steel_theoretical_mass_kg':sum(p['volume_mm3'] for p in manifest if p['group']=='welded_frame')*7.85e-6,'clashes':clashes,'native_solidworks_verified':False,'physical_tests':False}
(OUT/'Verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
hydro={'assumptions':'Freshwater1000kg/m3, horizontal sealed bare pipes only. Caps excluded; no stability/wave/trim calculation. These are gross total supported mass, not payload.','OD_mm':89,'bare_length_mm':600,'tubes':2,'full_displacement_kg':full,'at_freeboard_mm':[{'freeboard_mm':v,'gross_total_mass_kg':displacement(v)} for v in [44.5,40,30,20,10]],'physical_tests':False,'payload_certified_kg':None}
(OUT/'Buoyancy_Reference.json').write_text(json.dumps(hydro,indent=2),encoding='utf-8')
rows=[['F01','SHS19.05x19.05x1.2','500',2,'90/90','nominal3/4in; measure section'],['F02','SHS19.05x19.05x1.2',f'{clear:.2f}',2,'90/90','480-2*actual_section'],['F03','SHS19.05x19.05x1.2',f'{runner:.2f}',2,'90/90','220-2*actual_section'],['F04','steel t2','20x20 right triangle',4,'90/45/45','legs20; hypotenuse28.284'],['F05G','steel t3','135x30',4,'90 corners','holes7 pitch99; centre18 from end,15 from side; bought clamp fit first'],['F06','steel t3','50x45',2,'90 corners','holes4.5 pitch10; from left20,30; rear7.5'],['P01','PVC3 OD89 wall assumed2.6','600',2,'90/90','two pontoons per user; load test before use'],['P02','PVC3 cap','referenceOD97x32',4,'bought','actual socket depth required'],['S01','HDPE/sealed wood','80x30x24',4,'profile','recessR46.5']]
seed_cut=SRC/'seed_cut_list.csv' if (SRC/'seed_cut_list.csv').exists() else PREV/'Cut_List_mm.csv'
with seed_cut.open(encoding='utf-8-sig',newline='') as f:
    rows.extend(r for r in list(csv.reader(f))[1:] if r[0].startswith(('CV-','SOL-','DECK')))
for file,selection in [(OUT/'Cut_List_mm.csv',rows),(OUT/'Frame_Only/Frame_Cut_List_mm.csv',[r for r in rows if r[0].startswith('F')])]:
    with file.open('w',encoding='utf-8-sig',newline='') as f:csv.writer(f).writerows([['Code','Material','Dimensions_mm','Qty','Cut_angle_deg','Notes']]+selection)
for code,w,h,t,holes in [('F05G',135,30,3,[(18,15,3.5),(117,15,3.5)]),('F06',50,45,3,[(20,7.5,2.25),(30,7.5,2.25)])]:
    doc=ezdxf.new('R2010');doc.units=4;m=doc.modelspace();m.add_lwpolyline([(0,0),(w,0),(w,h),(0,h)],close=True)
    for x,z,r in holes:m.add_circle((x,z),r)
    file=OUT/'DXF_mm'/(code+'_flat_reference_mm.dxf');doc.saveas(file);shutil.copy2(file,OUT/'Frame_Only/DXF_mm'/file.name)
(OUT/'source/build_pvc3_boat.py').write_bytes(Path(__file__).read_bytes())
(OUT/'source/seed_manifest.json').write_text(json.dumps(reused,ensure_ascii=False,indent=2),encoding='utf-8')
with (OUT/'source/seed_cut_list.csv').open('w',encoding='utf-8-sig',newline='') as f:
    csv.writer(f).writerows([['Code','Material','Dimensions_mm','Qty','Cut_angle_deg','Notes']]+[r for r in rows if r[0].startswith(('CV-','SOL-','DECK'))])
(OUT/'source/seed_components').mkdir(exist_ok=True)
for p in reused:
    source=seeds/(p['code']+'.step');target=OUT/'source/seed_components'/source.name
    if source.resolve()!=target.resolve():shutil.copy2(source,target)
print('COMPONENTS',len(PARTS),'CLASHES',json.dumps(clashes),'FULL FLOAT',round(full,3),flush=True)
assert not clashes,clashes
