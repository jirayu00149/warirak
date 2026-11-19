"""Warirak PVC4 Rev E. Units mm, X right, Y up, Z bow.

Fabrication concept with nominal reference envelopes for bought components.
Requires CadQuery 2.8.0 and ezdxf. Run from the project root.
"""
from pathlib import Path
import csv
import json
import math
import sys
import shutil

OLD = Path('C:/Users/Administrator/Documents/Codex/2026-10-22/solid-mini-prototype-scale-model-350')
sys.path.insert(0, str(OLD / 'work/cad_runtime_b'))
import cadquery as cq
from cadquery import Vector as V
import ezdxf

ROOT = Path(__file__).resolve().parents[2]
FULL = '--full' in sys.argv
MODEL_NAME = 'Warirak_PVC4_RevF_Full' if FULL else 'Warirak_PVC4_RevE'
OUT = Path(sys.argv[sys.argv.index('--output')+1]).resolve() if '--output' in sys.argv else ROOT / 'outputs' / MODEL_NAME
for name in ('Parts_STEP', 'DXF_mm', 'source', 'images'):
    (OUT / name).mkdir(parents=True, exist_ok=True)

PARTS = []
BLUE = (0.04, .45, .78)
STEEL = (.31, .36, .39)
GRAY = (.62, .67, .68)
TEAL = (.08, .50, .43)
ORANGE = (.96, .48, .12)
BLACK = (.10, .14, .16)


def box(w, h, d, x, y, z):
    return cq.Workplane('XY').box(w, h, d).val().translate((x, y, z))


def cylinder(r, length, x, y, z, axis=(0, 0, 1)):
    return cq.Solid.makeCylinder(r, length, V(x, y, z), V(*axis))


def add(code, shape, group, material, color, exploded, note=''):
    assert shape.isValid() and shape.Volume() > 0, code
    PARTS.append(dict(code=code, shape=shape, group=group, material=material,
                      color=color, exploded=exploded, note=note))


def join(*shapes):
    return shapes[0].fuse(*shapes[1:]).clean()


# Reuse the previously checked in-plane Rev D frame, moving its height to the new floats.
SEEDS = Path(__file__).resolve().parent
FRAME = SEEDS/'seed_frame' if (SEEDS/'seed_frame').exists() else OLD / 'outputs/Warirak_Steel_Frame_RevD/Separate_STEP'
frame_ids = ['F01-L', 'F01-R', 'F02-REAR', 'F02-MID', 'F03-L', 'F03-R',
             'F04--1-REAR', 'F04--1-MID', 'F04-1-REAR', 'F04-1-MID', 'F06-L', 'F06-R']
for index, code in enumerate(frame_ids):
    shape = cq.importers.importStep(str(FRAME / (code + '.step'))).val().translate((0, -33, 0))
    center = shape.Center()
    add(code, shape, 'welded_frame', 'steel', STEEL,
        (80 if center.x > 0 else -80, 100 + index * 4, 0))

for sign, side in [(-1, 'L'), (1, 'R')]:
    x = sign * 230
    pipe = cylinder(57, 600, x, 57, -300).cut(cylinder(53.8, 602, x, 57, -301)).clean()
    add('P01-PVC4-' + side, pipe, 'pontoons', 'PVC', BLUE, (sign * 180, -45, 0),
        'OD114, nominal wall3.2, bare cut600; verify actual pipe class and wall')
    for direction, tag in [(1, 'BOW'), (-1, 'STERN')]:
        base_z = 271 if direction == 1 else -271
        cap = cylinder(61, 35, x, 57, base_z, (0, 0, direction))
        cavity = cylinder(57.2, 29.1, x, 57, base_z - direction * .1, (0, 0, direction))
        add('P02-CAP-' + side + '-' + tag, cap.cut(cavity).clean(), 'pontoons', 'PVC', BLUE,
            (sign * 180, -45, direction * 90),
            'REFERENCE socket cap OD122, socket29, endwall6; measure supplied cap before cutting')

    for z, station in [(-180, 'A'), (120, 'B')]:
        plate = box(160, 3, 30, x, 132.5, z)
        for dx in (-62, 62):
            plate = plate.cut(cylinder(3.5, 5, x + dx, 130, z, (0, 1, 0)))
        add(f'F05E-{side}-{station}', plate.clean(), 'welded_frame', 'steel', STEEL,
            (sign * 100, 70, 0), '160x30x3; 2holes diameter7, pitch124; match actual U-bolt first')

        saddle = box(80, 24, 30, x, 119, z).cut(cylinder(59, 32, x, 57, z-16)).clean()
        add(f'S01-SADDLE-{side}-{station}', saddle, 'saddles', 'HDPE_or_sealed_wood', TEAL,
            (sign * 120, 15, 0), 'Top131; curved recess R59; nominal stock80x30x24')
        rubber = cylinder(59, 30, x, 57, z-15).cut(cylinder(57, 32, x, 57, z-16))
        rubber = rubber.intersect(box(80, 40, 30, x, 110, z)).clean()
        add(f'S02-RUBBER-{side}-{station}', rubber, 'saddles', 'rubber', BLACK,
            (sign * 130, -10, 0), '2mm reference curved liner; actual compression not simulated')

        path = (cq.Workplane('XY').moveTo(x-62, 143).lineTo(x-62, 57)
                .threePointArc((x, -5), (x+62, 57)).lineTo(x+62, 143))
        rod = cq.Workplane('XZ', origin=(x-62, 143, 0)).circle(3).sweep(path).val().translate((0, 0, z))
        hardware = [rod]
        for dx in (-62, 62):
            washer = cylinder(8, 1.5, x+dx, 134, z, (0, 1, 0)).cut(
                cylinder(3.4, 2, x+dx, 133.8, z, (0, 1, 0)))
            nut = (cq.Workplane('XZ', origin=(x+dx, 140.5, z)).polygon(6, 11.55)
                   .extrude(5).val())
            nut = nut.cut(cylinder(3.4, 7, x+dx, 134.5, z, (0, 1, 0)))
            hardware.extend([washer.clean(), nut.clean()])
        add(f'H01-UBOLT-M6-{side}-{station}', cq.Compound.makeCompound(hardware), 'clamps',
            'stainless_steel', GRAY, (sign * 150, -60, 0),
            'Hardware set, 5 bodies: U-bolt,2washers,2nuts. Rod dia6, leg center pitch124 REFERENCE')

# Passive collection tray. Hole pattern is illustrative, not a cutting pattern for mesh.
tray = join(box(326, 2, 200, 0, 54, 150),
            box(2, 44, 200, -162, 77, 150), box(2, 44, 200, 162, 77, 150),
            box(322, 44, 2, 0, 77, 51))
tools = [cylinder(5, 4, x, 52, z, (0, 1, 0))
         for x in range(-144, 145, 24) for z in range(70, 240, 24)]
tray = tray.cut(*tools).clean()
add('B01-CATCH-TRAY', tray, 'collection', 'PP_or_mesh_reference', TEAL, (0, 20, 160),
    'Reference envelope326x200x46; adapt reused perforated tray or PE mesh3-5mm; front mouth +Z; adjust height after float test')
for sign, side in [(-1, 'L'), (1, 'R')]:
    for z, station in [(80, 'A'), (220, 'B')]:
        support = join(box(77, 3, 20, sign*201.5, 155.5, z),
                       box(3, 100, 20, sign*164.5, 104, z))
        add(f'B02-TRAY-SUPPORT-{side}-{station}', support, 'collection', 'aluminium_or_steel_reference',
            GRAY, (sign * 55, 60, 50), 'Reference bent strip; top atY157, mount to frame atY154; replace with actual bracket')

deck = box(332, 4, 200, 0, 156, -140)
add('D01-REAR-DECK', deck, 'deck', 'reused_HDPE', BLACK, (0, 150, -40), '332x200x4 reference, verify reused plate')


def open_box(w, h, d, x, ybase, z):
    return box(w,h,d,x,ybase+h/2,z).cut(box(w-6,h,d-6,x,ybase+h/2+3,z)).clean()


for code, w, h, d, x, z, color in [
    ('E01-CONTROL', 130, 70, 145, -90, -140, BLACK),
    ('E02-BATTERY', 85, 55, 135, 85, -140, ORANGE),
]:
    add(code+'-BOX', open_box(w,h,d,x,158,z), 'electronics_reference', 'plastic_reference', color,
        (0, 190, -70), 'Outer envelope; purchase box with internal clearance, gasket and cable glands')
    add(code+'-LID', box(w,3,d,x,158+h+1.5,z), 'electronics_reference', 'plastic_reference', color,
        (0, 270, -70), 'Reference lid; heat removal and waterproofing require hardware trials')

pi = join(box(85,1.6,56,-90,172,-140), box(15,7,15,-90,176.3,-140))
add('E03-PI5-REFERENCE', pi, 'electronics_reference', 'reference', (.08,.48,.23), (0, 240, -70),
    '85x56 board envelope; connector/active-cooler/USB wire clearance must be checked against actual Pi5')
add('E04-ESP32-REFERENCE', box(28,5,52,-90,199,-140), 'electronics_reference', 'reference', TEAL,
    (0, 260, -70), 'Representative DevKit envelope; actual board can differ')
add('E05-BATTERY-REFERENCE', box(45,22,102,85,180,-140), 'electronics_reference', 'reference', ORANGE,
    (0, 220, -70), '2S2200 envelope only; replace with chosen battery dimensions')

mast = join(box(12,76,12,0,192,-34), box(12,4,34,0,228,-11))
add('C01-CAMERA-MAST', mast, 'camera_reference', 'aluminium_or_plastic_reference', GRAY,
    (0, 250, 15), 'Reference mounting bracket; camera looks toward +Z')
camera = join(box(24,24,2,0,232,7), cylinder(5.5,6,0,232,8))
add('C02-CAMERA-REFERENCE', camera, 'camera_reference', 'reference', BLACK, (0, 270, 35),
    'OV5647 envelope24x24; CSI22to15 for Pi5 or replace with UVC camera')

for sign, side in [(-1,'L'),(1,'R')]:
    x = sign * 140
    body = cylinder(15,45,x,45,-255)
    guard = cylinder(23,25,x,45,-285).cut(cylinder(20,27,x,45,-286))
    prop = cylinder(4,4,x,45,-274)
    for angle in (0,120,240):
        blade = box(13,5,1.8,x+9.5,45,-272)
        prop = prop.fuse(blade.rotate((x,45,0),(x,45,1),angle))
    motor = cq.Compound.makeCompound([body,guard.clean(),prop.clean()])
    add('M01-BM70-'+side+'-REFERENCE', motor, 'propulsion_reference', 'reference', BLACK,
        (sign*60,-50,-130), 'Motor body30x45; prop/cage/total length is representative; requires vendor dimensions before mount holes')
    bracket = join(box(42,3,20,x,132.5,-240),
                   box(3,72,20,x-19.5,95,-240),box(3,72,20,x+19.5,95,-240),
                   cylinder(19.5,10,x,45,-245).cut(cylinder(15.5,12,x,45,-246)))
    add('M02-MOTOR-HANGER-'+side, bracket, 'propulsion_reference', 'reference', GRAY,
        (sign*80,20,-100), 'Concept hanging bracket; vendor fit and bolt-hole pattern pending')

if FULL:
    PARTS = [p for p in PARTS if p['group'] not in
             ('collection', 'deck', 'electronics_reference', 'camera_reference')]
    seed = SEEDS/'seed_conveyor' if (SEEDS/'seed_conveyor').exists() else OLD/'outputs/Warirak_Pi4_PVC2inch_5W/Separate_STEP_parts'
    wanted = ('P06_', 'P07_', 'P08_', 'P09_', 'P10_', 'P11_', 'P12_',
              'P13_', 'P17_', 'P18_', 'P20_', 'P21_', 'P22_', 'P29_', 'P30_')
    for path in sorted(seed.glob('*.step')):
        if path.name.startswith(wanted):
            shape=cq.importers.importStep(str(path)).val().translate((0,12,0))
            if path.name.startswith('P09_'):
                b=shape.BoundingBox()
                shape=shape.intersect(cylinder(16,200,-100,(b.ymin+b.ymax)/2,(b.zmin+b.zmax)/2,(1,0,0))).clean()
            if path.name.startswith('P22_'):
                # The bought coupling OD19 needs clearance through the mounting plate.
                b=next(p['shape'] for p in PARTS if p['code']=='CV-P09_Upper_roller').BoundingBox()
                shape=shape.cut(cylinder(10,8,136,(b.ymin+b.ymax)/2,(b.zmin+b.zmax)/2,(1,0,0))).clean()
            add('CV-'+path.stem,shape,'conveyor','conveyor_reference',GRAY,(0,100,140),
                'Reused conveyor fit geometry: centers350mm, inclination32deg, beltwidth190. Purchased motor/coupling fit must be measured.')
    for sign,side in [(-1,'L'),(1,'R')]:
        add('CV-BASE-RISER-'+side,box(25,45,45,sign*121,179.5,-40),
            'conveyor','aluminium_or_HDPE',GRAY,(sign*20,60,30),
            'Riser25x45x45 between F06 topY157 and conveyor supportY202; drill after fitting')
    add('D01-REAR-DECK',box(460,5,185,0,156.5,-157.5),'deck','reused_HDPE',BLACK,
        (0,100,-70),'460x185x5 reference. Frontedge-65 clears conveyor risers')
    replacements=[
        ('P14_Removable_bin','BIN-REMOVABLE',(0,-41,0),TEAL),
        ('Controls_commercial_box_ENVELOPE','E01-CONTROL-BOX',(0,-40,-15),BLACK),
        ('Controls_lid_ENVELOPE','E01-CONTROL-LID',(0,-40,-15),BLACK),
        ('Battery_commercial_box_ENVELOPE','E02-BATTERY-BOX',(0,-40,0),ORANGE),
        ('Battery_lid_ENVELOPE','E02-BATTERY-LID',(0,-40,0),ORANGE),
        ('Owned_Raspberry_Pi4_board_REFERENCE','E03-PI5-REFERENCE',(0,-40,-15),TEAL),
        ('Owned_ESP32_REFERENCE','E04-ESP32-REFERENCE',(0,-40,-15),TEAL),
    ]
    for filename,code,shift,color in replacements:
        shape=cq.importers.importStep(str(seed/(filename+'.step'))).val().translate(shift)
        add(code,shape,'electronics_reference' if code.startswith('E') else 'collection',
            'reference',color,(0,200,-100),
            'Bought/reused component envelope. Pi5 board outline85x56 only, connector and cooler clearances require actual hardware')
    add('E05-BATTERY-REFERENCE',box(45,22,102,174,180,-150),
        'electronics_reference','reference',ORANGE,(0,220,-90),'2S2200 reference envelope')
    bridge=next(p['shape'] for p in PARTS if p['code']=='CV-P17_Front_sensor_bridge')
    bridge_top=bridge.BoundingBox().ymax
    mast=join(box(8,28,8,0,bridge_top+14,-39),box(8,4,36,0,bridge_top+28,-17))
    add('C01-CAMERA-MAST',mast,'camera_reference','reference',GRAY,(0,150,30),
        'Camera bracket attached to front bridge, fit to actual camera')
    camera_y=bridge_top+37.5
    camera=join(box(38,15,24,0,camera_y,13),cylinder(5.5,6,0,camera_y,25))
    add('C02-CAMERA-REFERENCE',camera,'camera_reference','reference',BLACK,(0,180,50),
        'Budget USB camera nominal38x15x30 reference looking +Z; body/connector/splash enclosure require actual hardware')
    add('C03-SONAR-REFERENCE',cylinder(8,12,55,319,-28),
        'camera_reference','reference',BLACK,(30,120,35),'Single JSN head representative envelope')
    for sign in (-1,1):
        for z in (-240,-80):
            add(f'SOL-POST-{sign}-{z}',box(7,181.5,7,sign*113,249.75,z),
                'solar','aluminium_or_reused_stock',GRAY,(sign*20,180,0),
                '181.5mm post reference, from deckY159 to crossbar undersideY340.5')
    for name in ['Solar_crossbar_-240','Solar_crossbar_-80',
                 'Hopesun_5W_215x180x17_ENVELOPE','Solar_5W_surface_REFERENCE']:
        shape=cq.importers.importStep(str(seed/(name+'.step'))).val().translate((0,12,0))
        add('SOL-'+name,shape,'solar','solar_reference',(.46,.61,.84) if 'surface' in name else GRAY,
            (0,220,0),'5W panel215x180x17, nominal0.53kg. Solar charging circuit selected after battery verification')

assembly = cq.Assembly(name=MODEL_NAME)
exploded = cq.Assembly(name=MODEL_NAME+'_Exploded')
frame_assembly = cq.Assembly(name=MODEL_NAME+'_Frame')
frame_exploded = cq.Assembly(name=MODEL_NAME+'_Frame_Exploded')
manifest = []
for part in PARTS:
    name, shape = part['code'], part['shape']
    cq.exporters.export(shape,str(OUT/'Parts_STEP'/f'{name}.step'))
    assembly.add(shape,name=name,color=cq.Color(*part['color']))
    exploded.add(shape,name=name,color=cq.Color(*part['color']),loc=cq.Location(V(*part['exploded'])))
    if part['group']=='welded_frame':
        frame_assembly.add(shape,name=name,color=cq.Color(*part['color']))
        frame_exploded.add(shape,name=name,color=cq.Color(*part['color']),loc=cq.Location(V(*part['exploded'])))
    bounds=shape.BoundingBox()
    vertices,triangles=shape.tessellate(.6,.25)
    manifest.append({k:v for k,v in part.items() if k!='shape'} | {
        'file':f'Parts_STEP/{name}.step','solids':len(shape.Solids()),
        'volume_mm3':shape.Volume(),
        'bounds_mm':[bounds.xmin,bounds.ymin,bounds.zmin,bounds.xmax,bounds.ymax,bounds.zmax],
        'mesh':{'vertices':[[v.x,v.y,v.z] for v in vertices],'triangles':triangles}})

for assy,filename in [(assembly,MODEL_NAME+'_Assembly.step'),
                      (exploded,MODEL_NAME+'_Exploded.step'),
                      (frame_assembly,MODEL_NAME+'_Frame.step'),
                      (frame_exploded,MODEL_NAME+'_Frame_Exploded.step')]:
    assy.export(str(OUT/filename))
    imported=cq.importers.importStep(str(OUT/filename)).val()
    assert imported.isValid(),filename
    print('STEP VERIFIED',filename,len(imported.Solids()),flush=True)

# Verify each broad-phase candidate pair. Small intended mating contacts have zero volume.
clashes=[]
for i,p in enumerate(PARTS):
    a=p['shape'].BoundingBox()
    for q in PARTS[i+1:]:
        b=q['shape'].BoundingBox()
        if a.xmax<=b.xmin+.001 or b.xmax<=a.xmin+.001 or a.ymax<=b.ymin+.001 or b.ymax<=a.ymin+.001 or a.zmax<=b.zmin+.001 or b.zmax<=a.zmin+.001:
            continue
        overlap=p['shape'].intersect(q['shape']).Volume()
        if overlap>.01:
            clashes.append({'parts':[p['code'],q['code']],'overlap_mm3':overlap})

parameters = {'revision':'F' if FULL else 'E','assembly_name':MODEL_NAME,'full_conveyor_solar':FULL,'units':'mm','axes':{'X':'right','Y':'up','Z':'bow'},
              'pipe':{'OD':114,'wall_assumed':3.2,'cut_length':600,'quantity':2},
              'cap_reference':{'OD':122,'length':35,'engagement':29,'quantity':4},
              'nominal_overall_mm':{'width_including_tabs':620,'pipe_caps_length':612},
              'frame_mm':{'width':480,'length':500,'section':20,'wall':1.2,'bottom_y':134,'top_y':154},
              'F05E':{'size':[160,30,3],'hole_diameter':7,'pitch':124,'x_centers':[-230,230],'z_stations':[-180,120]},
              'bare_pipe_full_displacement_liters':math.pi*57**2*600*2/1e6,
              'bare_pipe_half_immersed_displacement_kg':math.pi*57**2*600/1e6,
              'fabrication_status':'REFERENCE fit model. Pipe/caps/U-bolts/motors require actual measurements. Weld and flotation tests pending.',
              'component_count':len(PARTS),'clashes':clashes,'parts':manifest}
(OUT/'CAD_parameters.json').write_text(json.dumps(parameters,ensure_ascii=False,indent=2),encoding='utf-8')
steel_volume=sum(p['shape'].Volume() for p in PARTS if p['group']=='welded_frame')
verification={'component_count':len(PARTS),'solid_count':sum(len(p['shape'].Solids()) for p in PARTS),
              'valid_step_roundtrip':True,'steel_theoretical_mass_kg':steel_volume*7.85e-6,
              'clashes':clashes,'native_solidworks_verified':False,'physical_tests':False}
(OUT/'Verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
with (OUT/'Cut_List_mm.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.writer(f)
    writer.writerow(['Code','Material','Dimensions_mm','Qty','Cut_angle_deg','Notes'])
    writer.writerows([
        ['F01','SHS20x20x1.2','500',2,'90/90','side beams'],
        ['F02','SHS20x20x1.2','440',2,'90/90','cross beams'],
        ['F03','SHS20x20x1.2','180',2,'90/90','rear bin supports'],
        ['F04','steel t2','20x20 right triangle',4,'90/45/45','reuse RevD gussets'],
        ['F05E','steel t3','160x30',4,'90 corners','holes dia7 pitch124, confirm U-bolt first'],
        ['F06','steel t3','50x45',2,'90 corners','original conveyor mounting plates; use existing STEP hole pattern'],
        ['P01','PVC4 nominal OD114','600',2,'90/90','wall assumed3.2; caps add12 overall'],
        ['P02','PVC socket cap','reference122ODx35',4,'bought','measure actual socket before cutting'],
        ['S01','HDPE or sealed wood','80x30x24',4,'90 corners','cut curved recessR59'],
    ])
    if FULL:
        writer.writerows([
            ['CV-RISER','HDPE or aluminium','25x45x45',2,'90 corners','support between F06 and conveyor'],
            ['CV-RAIL','HDPE t6','378x28 overall; shaft pitch350',2,'profile','inclination32deg; shaft seats dia10.2'],
            ['CV-ROLLER','PVC or printed drum','dia32x198; bore6.2',2,'90/90','positive drive hub and grip sleeve needed'],
            ['CV-SHAFT-UP','stainless dia6','244',1,'90/90','retain against axial motion'],
            ['CV-SHAFT-LOW','stainless dia6','217',1,'90/90','retain against axial motion'],
            ['CV-BELT','PE mesh','190wide; neutral loop approx807',1,'fit splice','buy900mm length; cleats8 high20'],
            ['SOL-POST','reused aluminium bar','7x7x181.5',4,'90/90','verify rigidity and joints'],
            ['SOL-CROSS','aluminium bar','240x10x5',2,'90/90','reference crossbars'],
            ['SOL-PANEL','bought 5W18V','215x180x17',1,'bought','measure chosen panel before mounting'],
            ['DECK','HDPE t5','460x185',1,'90 corners','use offcuts'],
        ])
doc=ezdxf.new('R2010');doc.units=4;modelspace=doc.modelspace()
modelspace.add_lwpolyline([(0,0),(160,0),(160,30),(0,30)],close=True)
for x in [18,142]:modelspace.add_circle((x,15),3.5)
doc.saveas(OUT/'DXF_mm/F05E_160x30_t3_holes7_pitch124_REFERENCE.dxf')
(OUT/'source/build_pvc4_boat.py').write_bytes(Path(__file__).read_bytes())
for folder, paths in [('seed_frame',[FRAME/(code+'.step') for code in frame_ids]),
                      ('seed_conveyor',list(seed.glob('*.step')) if FULL else [])]:
    target=OUT/'source'/folder
    target.mkdir(exist_ok=True)
    # Include only seed geometry actually used by this revision.
    used=[p for p in paths if folder=='seed_frame' or p.name.startswith(wanted) or p.stem in [r[0] for r in replacements] or p.stem in ['Solar_crossbar_-240','Solar_crossbar_-80','Hopesun_5W_215x180x17_ENVELOPE','Solar_5W_surface_REFERENCE']]
    for path in used:
        if path.resolve() != (target/path.name).resolve():
            shutil.copy2(path,target/path.name)
print('COMPONENTS',len(PARTS),'CLASHES',json.dumps(clashes),flush=True)
if clashes:
    raise SystemExit('Correct the listed clashes before delivery')
