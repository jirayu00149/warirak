"""Export existing Rev G printable components in millimeters, seated on Z=0."""

from collections import Counter
import json
import math
from pathlib import Path
import struct
from zipfile import ZIP_DEFLATED, ZipFile

import cadquery as cq
from cadquery import Vector

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "outputs/Warirak_PVC3_RevG_Full/Parts_STEP"
OUT = ROOT / "output/Warirak_BM70_3D_Print"
(OUT / "Optional").mkdir(parents=True, exist_ok=True)


def seat_on_face(shape):
    """Place the largest planar face on the bed, then center the part."""
    support = max((f for f in shape.Faces() if f.geomType() == "PLANE"), key=lambda f: f.Area())
    normal = support.normalAt().normalized()
    target = Vector(0, 0, -1)
    angle = math.acos(max(-1, min(1, normal.dot(target))))
    axis = normal.cross(target)
    if angle > 1e-9:
        shape = shape.rotate(Vector(), axis if axis.Length > 1e-8 else Vector(1, 0, 0), math.degrees(angle))
    bb = shape.BoundingBox()
    return shape.translate(Vector(-(bb.xmin+bb.xmax)/2, -(bb.ymin+bb.ymax)/2, -bb.zmin))


def verify_stl(path):
    raw = path.read_bytes()
    count, = struct.unpack_from("<I", raw, 80)
    assert len(raw) == 84 + 50*count
    edges = Counter()
    positions = []
    for index in range(count):
        xyz = struct.unpack_from("<12f", raw, 84+50*index)[3:]
        vertices = [tuple(round(x, 4) for x in xyz[i:i+3]) for i in (0, 3, 6)]
        positions.extend(vertices)
        assert len(set(vertices)) == 3
        edges.update(tuple(sorted((vertices[i], vertices[(i+1)%3]))) for i in range(3))
    assert all(incident == 2 for incident in edges.values()), path
    minimum = [min(p[i] for p in positions) for i in range(3)]
    size = [max(p[i] for p in positions)-minimum[i] for i in range(3)]
    assert abs(minimum[2]) < .0001
    return count, size, minimum[2]


entries = (
    ("CV-P30_Lower_bush_R", "CV-P30_Flanged_Bush_x6.stl", 6, "บูชสายพานมีบ่า รู 6.3 มม. ปลอก OD10 บ่า OD14 ยาวรวม 7 มม."),
    ("CV-P13_Upper_cleat_1", "CV-P13_Conveyor_Cleat_x8.stl", 8, "ครีบสายพานยาว 186 มม. มีรูยึด 4 รู Ø3.2"),
    ("S01-SADDLE-R-A", "Optional/S01_PVC89_Saddle_x4.stl", 4, "อานทุ่น PVC OD89 พร้อมยางรองตามแบบ ใช้แทนชิ้นตัดไม้หรือ HDPE เมื่อทดสอบรับแรงแล้ว"),
    ("CV-P09_Lower_roller", "Optional/CV-P09_Roller_OD32_L198_x2.stl", 2, "ลูกกลิ้ง OD32 ยาว 198 รูแกน 6.2 มม. ใช้เมื่อเลือกพิมพ์ลูกกลิ้ง"),
)
records = []
for code, filename, quantity, note in entries:
    source = cq.importers.importStep(str(SOURCE / (code + ".step"))).val()
    assert source.isValid() and len(source.Solids()) == 1
    shape = seat_on_face(source)
    path = OUT / filename
    cq.exporters.export(shape, str(path), tolerance=.04, angularTolerance=.08)
    facets, mesh_size, base_z = verify_stl(path)
    records.append(dict(
        file=filename, quantity=quantity, note=note, source_step=str(SOURCE / (code + ".step")),
        size_mm=[round(x,3) for x in mesh_size], units="mm",
        base_z_mm=base_z, solid_count=1, closed_triangle_mesh=True, facets=facets,
        source_volume_mm3=round(source.Volume(),3),
    ))

# All six bush positions in the assembly use the same nominal geometry.
volumes = []
for path in SOURCE.glob("CV-P30_*.step"):
    shape = cq.importers.importStep(str(path)).val()
    bb = shape.BoundingBox()
    volumes.append(shape.Volume())
    assert abs(bb.xlen-7) < 1e-5 and abs(bb.ylen-14) < 1e-5 and abs(bb.zlen-14) < 1e-5
assert len(volumes) == 6 and max(volumes)-min(volumes) < .001

text = """# ไฟล์ปริ้น 3D สำหรับวารีรักษ์ BM70 ใบพัดท้ายเรือ

ไฟล์ STL ส่งออกจากชิ้นส่วนเดิมในชุด STEP Rev G หน่วยมิลลิเมตร จัดชิ้นให้ฐานอยู่ที่ Z=0 แล้ว ตั้งสเกลในโปรแกรม slicer เป็น 100% และตรวจขนาดก่อนปริ้น

| ไฟล์ | จำนวนตามแบบ | ใช้ทำอะไร |
|---|---:|---|
| CV-P30_Flanged_Bush_x6.stl | 6 | บูชรองเพลาสายพาน 6 มม. สองตัวล่าง สองตัวบน และสองตัวรองรับเพลาบน |
| CV-P13_Conveyor_Cleat_x8.stl | 8 | ครีบยกขยะบนสายพาน ยึดกับตาข่ายด้วยรูสี่รูตามแบบ |
| Optional/S01_PVC89_Saddle_x4.stl | 4 | อานรองทุ่น OD89 แทนชิ้นตัดไม้หรือ HDPE เมื่อผ่านทดสอบรับแรง |
| Optional/CV-P09_Roller_OD32_L198_x2.stl | 2 | ลูกกลิ้งสายพาน OD32 × 198 รูแกน 6.2 มม. เลือกพิมพ์เมื่อยังไม่มีลูกกลิ้งจริง |

ตัวเลข x6 และ x8 ในชื่อไฟล์เป็นจำนวนที่ต้องตั้งใน slicer แต่ละ STL มีชิ้นงานหนึ่งตัว แนะนำพิมพ์บูชหนึ่งตัวลองสวมเพลาและรางก่อนทำครบชุด รูอาจต้องเก็บผิวตามค่าคลาดเคลื่อนของเครื่องพิมพ์ หมุนเพลาให้คล่องโดยไม่ฝืน ตรวจการสึกและความร้อนระหว่างทดสอบ

ครีบมีความยาว 186 มม. ให้ตรวจว่าพื้นที่พิมพ์พอดีและรูอยู่ตรงตาข่ายจริง อานต้องมีแผ่นยางรองและต้องทดสอบแรงรัด U-bolt กับทุ่นจริง ลูกกลิ้งพิมพ์ยังต้องจัดวิธียึดเพลาขับให้ส่งแรงบิดได้ตามชุดจริง

## จุดยึด BM70

ใช้ขายึดโลหะและแคลมป์ที่พอดีตัว BM70 ได้ หากต้องการปริ้น ให้ปรับแบบจากเส้นผ่านศูนย์กลางตัวมอเตอร์และตำแหน่งยึดจริงก่อน ชิ้น M02-MOTOR-HANGER ในแบบ STEP เดิมเป็นแบบอ้างอิงที่ยังไม่มีรูยึดและประกอบด้วยเนื้อ solid สองชิ้นแยกจากกัน จึงต้องแก้แบบก่อนส่งปริ้นใช้งาน

ไฟล์ชุดนี้ใช้กับเรือ BM70 ที่เลือก ส่วนไฟล์ล้อตีน้ำของแบบ ABC 2215 อยู่ในโฟลเดอร์รุ่นนั้น
"""
(OUT / "PRINT_LIST_TH.md").write_text(text, encoding="utf-8")
(OUT / "STL_Check.json").write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
archive = OUT.with_suffix(".zip")
with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
    for path in sorted(OUT.rglob("*")):
        if path.is_file():
            bundle.write(path, path.relative_to(OUT.parent).as_posix())
with ZipFile(archive) as bundle:
    assert bundle.testzip() is None
print(json.dumps(records, indent=2))
print("PACKAGE", archive)
