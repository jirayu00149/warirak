"""Visualize a connected two-piece BM70 mount with the existing stern frame."""

import json
import math
from pathlib import Path
import sys

sys.path.insert(0, "C:/Users/Administrator/Documents/Codex/2026-10-22/solid-mini-prototype-scale-model-350/work/cad_runtime_b")
import cadquery as cq
from cadquery import Vector as V
import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "outputs/Warirak_PVC3_RevG_Full"
OUT = ROOT / "output/Warirak_BM70_Mount_Model"
OUT.mkdir(parents=True, exist_ok=True)
data = json.loads((BASE / "CAD_parameters.json").read_text(encoding="utf-8"))
rows = {row["code"]: row for row in data["parts"]}

ORANGE = (.91, .47, .14)
TEAL = (.04, .49, .48)
GREY = (.53, .60, .64)
DARK = (.16, .20, .23)
WHITE = (.91, .93, .94)
MX, MY, MZ = 140., 16., -255.
parts = []


def box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1-x0, y1-y0, z1-z0, V(x0,y0,z0))


def cylinder(r, length, point, direction=(0,0,1)):
    return cq.Solid.makeCylinder(r, length, V(*point), V(*direction))


def component(name, geometry, color, explode=(0,0,0)):
    assert geometry.isValid(), name
    parts.append(dict(name=name, geometry=geometry, color=color, explode=explode))


def z_hole(x,y,r=2.75):
    return cylinder(r, 45, (x,y,-268))


bore = cylinder(15.5, 30, (MX,MY,-269))
annulus = cylinder(19,12,(MX,MY,-261)).cut(bore)
upper_ring = annulus.intersect(box(MX-40,MX+40,MY+.5,MY+50,-263,-247))
lower_ring = annulus.intersect(box(MX-40,MX+40,MY-50,MY-.5,-263,-247))
upper = upper_ring.fuse(
    box(MX-28,MX+28,MY+.5,MY+6,-261,-249),
    box(MX-14,MX+14,MY+12,MY+26,-261,-249),
    box(MX-28,MX+28,34,137,-256,-250),
).cut(bore)
lower = lower_ring.fuse(box(MX-28,MX+28,MY-6,MY-.5,-261,-249)).cut(bore)
for dx in (-23,23):
    hole=cylinder(2.3,30,(MX+dx,0,-255),(0,1,0))
    upper=upper.cut(hole)
    lower=lower.cut(hole)
for dx in (-14,14):
    upper=upper.cut(z_hole(MX+dx,118.525))
for dx in (-24,21):
    wire=cq.Wire.makePolygon([V(MX+dx,36,-272),V(MX+dx,36,-253),V(MX+dx,91,-253)],close=True)
    upper=upper.fuse(cq.Solid.extrudeLinear(wire,[],V(3,0,0)))
upper=upper.clean()
lower=lower.clean()
assert len(upper.Solids())==len(lower.Solids())==1
component("1_Hanger",upper,ORANGE)
component("2_Lower_clamp",lower,TEAL,(0,-30,0))
liner=cylinder(15.5,12,(MX,MY,-261)).cut(cylinder(15,14,(MX,MY,-262)))
component("Rubber_liner_reference",liner,(.21,.25,.28))

motor=cylinder(15,45,(MX,MY,-277)).fuse(
    cylinder(6,3,(MX,MY,-280)),
    cylinder(1,7,(MX,MY,-287)),
).clean()
component("3_BM70_reference",motor,WHITE,(0,-10,-70))
prop=cylinder(4,3,(MX,MY,-289))
for angle in range(0,360,120):
    blade=box(MX+3,MX+17.8,MY-2.3,MY+2.3,-289,-286)
    blade=blade.rotate(V(MX,MY,0),V(MX,MY,1),angle)
    prop=prop.fuse(blade)
component("Propeller_reference",prop.clean(),DARK,(0,-10,-70))

for dx in (-23,23):
    screw=cylinder(2,19,(MX+dx,7,-255),(0,1,0)).fuse(
        cylinder(3.6,3,(MX+dx,22,-255),(0,1,0)))
    nut=cq.Workplane("XZ",origin=(MX+dx,10,-255)).polygon(6,8).extrude(3).val()
    nut=nut.cut(cylinder(2.1,5,(MX+dx,6,-255),(0,1,0)))
    component("Clamp_M4_bolt_"+str(dx),screw.clean(),GREY,(0,10,0))
    component("Clamp_M4_nut_"+str(dx),nut,GREY,(0,-38,0))
backplate=box(MX-28,MX+28,107.5,129.5,-230.95,-227.95)
for dx in (-14,14):
    backplate=backplate.cut(z_hole(MX+dx,118.525))
    bolt=cylinder(2.5,31,(MX+dx,118.525,-258)).fuse(cylinder(4.5,3,(MX+dx,118.525,-259)))
    nut=cq.Workplane("XY",origin=(MX+dx,118.525,-228)).polygon(6,9.2).extrude(4).val()
    nut=nut.cut(z_hole(MX+dx,118.525,2.75))
    component("Frame_M5_bolt_"+str(dx),bolt.clean(),GREY,(0,0,-15))
    component("Frame_M5_nut_"+str(dx),nut,GREY,(0,0,13))
component("Backing_plate",backplate.clean(),GREY,(0,0,15))

# Preserve the assembly origin for importing the STEP into the boat assembly.
model=cq.Assembly(name="BM70_Stern_Mount_Concept")
for p in parts:
    model.add(p["geometry"],name=p["name"],color=cq.Color(*p["color"]))
model.export(str(OUT/"BM70_Stern_Mount_Concept.step"))
reopened=cq.importers.importStep(str(OUT/"BM70_Stern_Mount_Concept.step")).val()
assert reopened.isValid() and len(reopened.Solids())==len(parts)
check=dict(body_diameter_mm=30,body_length_mm=45,motor_axis_Y=MY,motor_axis_X=MX,
           primary_hanger_solids=len(upper.Solids()),lower_clamp_solids=len(lower.Solids()),
           fabrication_status="Illustrative fit model; measure purchased motor and test mount before fabrication",
           frame_mounting="2 x M5 with backing plate; crossbeam hole positions require checking actual frame",
           parts=[dict(name=p["name"],solids=len(p["geometry"].Solids()),volume_mm3=round(p["geometry"].Volume(),3)) for p in parts])
(OUT/"Model_Check.json").write_text(json.dumps(check,indent=2),encoding="utf-8")
(OUT/"README_TH.md").write_text(
    "# ภาพตัวอย่างจุดยึด BM70 ท้ายเรือ\n\n"
    "สีส้มเป็นขายึดส่วนบน ยึดคานท้ายด้วย M5 สองตัวและแผ่นรอง สีเขียวเป็นฝาประกับล่าง "
    "ใช้ M4 สองตัวรัดมอเตอร์ผ่านยางรอง ตัว BM70 เป็นสีขาว ใบพัดอยู่ทางท้าย\n\n"
    "ภาพประกอบใช้ตัวมอเตอร์อ้างอิง OD30 × 45 มม. ตามสเปกผู้ผลิต ส่วนขายึด รู และตำแหน่งสายเป็นแนวคิดใหม่ "
    "ต้องวัดตัว BM70 จริง ความยาวส่วนที่รัดได้ และรูยึดกับคานก่อนทำชิ้นงาน "
    "เมื่อขันคานเหล็กกลวงให้ใช้แผ่นรองและจัดการการยุบของผนังตามงานประกอบจริง\n\n"
    "แบบนี้เพิ่มเนื้อเชื่อมจากแผ่นห้อยถึงแคลมป์ด้านบนให้เป็น solid ต่อเนื่อง และแยกฝาประกับล่างถอดได้ "
    "ไฟล์ STEP เป็นชุดแบบจำลองเพื่อดูการติดตั้ง ยังต้องทดสอบรับแรง ความร้อน การกันสาย และการลอยตัว\n\n"
    "https://www.underwaterthruster.com/products/apisqueen-2s-lipo-8-4v-28w-bm70-brushed-thruster-for-rov-toy-boats\n",
    encoding="utf-8")


def mesh_actor(shape,color,opacity=1):
    vertices,faces=shape.tessellate(.13,.12)
    points=vtk.vtkPoints()
    points.SetData(numpy_to_vtk(np.array([v.toTuple() for v in vertices],dtype=np.float32),deep=True))
    cells=vtk.vtkCellArray()
    for face in faces:
        cells.InsertNextCell(3)
        for idx in face:
            cells.InsertCellPoint(idx)
    poly=vtk.vtkPolyData()
    poly.SetPoints(points)
    poly.SetPolys(cells)
    normals=vtk.vtkPolyDataNormals()
    normals.SetInputData(poly)
    normals.SetFeatureAngle(40)
    mapper=vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(normals.GetOutputPort())
    actor=vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(*color)
    actor.GetProperty().SetOpacity(opacity)
    actor.GetProperty().SetAmbient(.3)
    actor.GetProperty().SetDiffuse(.7)
    return actor


def caption(renderer,s,x,y,size=24,color=(.10,.22,.26)):
    item=vtk.vtkTextActor()
    item.SetInput(s)
    item.SetPosition(x,y)
    item.GetTextProperty().SetFontSize(size)
    item.GetTextProperty().SetColor(*color)
    renderer.AddViewProp(item)


def imported(code):
    return cq.importers.importStep(str(BASE/rows[code]["file"])).val()


for kind in ("installed","detail","exploded"):
    window=vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(1400,1000)
    window.SetMultiSamples(8)
    renderer=vtk.vtkRenderer()
    renderer.SetBackground(.95,.97,.97)
    window.AddRenderer(renderer)
    geometries=[]
    if kind=="installed":
        for code in ("F01-L","F01-R","F02-REAR","F02-MID",
                     "P01-PVC3-L","P01-PVC3-R","P02-CAP-L-STERN","P02-CAP-R-STERN"):
            shape=imported(code)
            if code=="F02-REAR":
                for x in (-154,-126,126,154):
                    shape=shape.cut(z_hole(x,118.525))
            geometries.append((shape,rows[code]["color"],1))
    elif kind=="detail":
        rail=imported("F02-REAR").intersect(box(87,193,105,134,-252,-228))
        rail=rail.cut(*(z_hole(MX+dx,118.525) for dx in (-14,14)))
        geometries.append((rail,(.43,.49,.52),1))

    for p in parts:
        shape=p["geometry"]
        if kind=="exploded":
            shape=shape.translate(V(*p["explode"]))
        geometries.append((shape,p["color"],1))
        if kind=="installed":
            geometries.append((shape.mirror("YZ"),p["color"],1))
    for shape,color,opacity in geometries:
        renderer.AddActor(mesh_actor(shape,color,opacity))

    camera=renderer.GetActiveCamera()
    camera.ParallelProjectionOn()
    camera.SetViewUp(0,1,0)
    if kind=="installed":
        camera.SetFocalPoint(0,69,-135)
        camera.SetPosition(690,440,-930)
    else:
        camera.SetFocalPoint(140,67,-261)
        camera.SetPosition(350,180,-500)
    renderer.ResetCamera()
    camera.Zoom(.9 if kind=="installed" else .9)
    renderer.ResetCameraClippingRange()
    caption(renderer,"BM70  |  STERN MOUNT  |  "+kind.upper(),34,935,29)
    caption(renderer,"1  Orange hanger    2  Teal lower clamp    3  White motor",34,895,23)
    caption(renderer,"Illustrative model  |  Motor reference OD30 x 45 mm  |  Measure actual parts before fabrication",34,24,19)
    if kind=="installed":
        caption(renderer,"View from behind the boat  |  Twin mounts",34,61,21)
    elif kind=="exploded":
        caption(renderer,"M5 bolts to frame + backing plate  |  M4 clamp bolts + rubber liner",34,61,21)
    window.Render()
    capture=vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.ReadFrontBufferOff()
    capture.Update()
    writer=vtk.vtkPNGWriter()
    writer.SetInputConnection(capture.GetOutputPort())
    writer.SetFileName(str(OUT/(kind+".png")))
    writer.Write()
    window.Finalize()
    print(kind,flush=True)
print("CHECK",len(upper.Solids()),len(lower.Solids()),flush=True)
