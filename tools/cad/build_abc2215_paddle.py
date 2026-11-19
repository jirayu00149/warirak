"""Build the detachable Rev H paddle drive on the Rev G PVC3 assembly."""

import json
import math
from pathlib import Path

import cadquery as cq
from cadquery import Vector

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "outputs/Warirak_PVC3_RevG_Full"
OUT = ROOT / "output/Warirak_PVC3_ABC2215_RevH"
NAME = "Warirak_PVC3_ABC2215_RevH"
PARTS = OUT / "Drive_STEP"
PRINT = OUT / "Print_STL"
for folder in (PARTS, PRINT):
    folder.mkdir(parents=True, exist_ok=True)

COLORS = {
    "aluminum": (0.66, 0.73, 0.76),
    "steel": (0.36, 0.42, 0.46),
    "PETG": (0.09, 0.58, 0.59),
    "guard": (0.94, 0.65, 0.16),
    "belt": (0.16, 0.19, 0.24),
    "motor": (0.72, 0.30, 0.16),
    "battery": (0.41, 0.35, 0.52),
}
DENSITY = {"aluminum": 2.70, "steel": 7.85, "PETG": 1.27, "guard": 1.27, "belt": 1.23}
SMALL = 16 / math.pi
LARGE = 60 / math.pi
DELTA = LARGE - SMALL


def belt_length(center):
    return (
        2 * math.sqrt(center**2 - DELTA**2)
        + math.pi * (LARGE + SMALL)
        + 2 * DELTA * math.asin(DELTA / center)
    )


lower, upper = 50.0, 90.0
for _ in range(40):
    middle = (lower + upper) / 2
    if belt_length(middle) < 220:
        lower = middle
    else:
        upper = middle
CENTER = (lower + upper) / 2
WHEEL = (112.0, -38.0)
JACK2 = (WHEEL[0] + 55, WHEEL[1] - math.sqrt(CENTER**2 - 55**2))
JACK1 = (JACK2[0] + 48, JACK2[1] + math.sqrt(CENTER**2 - 48**2))
MOTOR = (JACK1[0] + 12, JACK1[1] + math.sqrt(CENTER**2 - 12**2))
AXES = (MOTOR, JACK1, JACK2, WHEEL)
MOTOR_TENSION_DIRECTION = tuple((a-b)/CENTER for a, b in zip(MOTOR, JACK1))


def box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, Vector(x0, y0, z0))


def shaft(x0, x1, axis, radius):
    return cq.Solid.makeCylinder(radius, x1 - x0, Vector(x0, *axis), Vector(1, 0, 0))


def ring(x0, x1, axis, outer, inner):
    return shaft(x0, x1, axis, outer).cut(shaft(x0 - 1, x1 + 1, axis, inner))


def plate(x0, x1, points):
    wire = cq.Wire.makePolygon([Vector(x0, y, z) for y, z in points], close=True)
    return cq.Solid.extrudeLinear(wire, [], Vector(x1 - x0, 0, 0))


def link(x0, x1, a, b, width):
    dy, dz = b[0] - a[0], b[1] - a[1]
    size = math.hypot(dy, dz)
    y, z = -dz * width / (2 * size), dy * width / (2 * size)
    return plate(x0, x1, [(a[0]+y, a[1]+z), (b[0]+y, b[1]+z),
                          (b[0]-y, b[1]-z), (a[0]-y, a[1]-z)])


def slot(x0, x1, axis, length, radius, direction=(1, 0)):
    dy, dz = direction
    a = axis[0]-dy*length/2, axis[1]-dz*length/2
    b = axis[0]+dy*length/2, axis[1]+dz*length/2
    return shaft(x0, x1, a, radius).fuse(
        link(x0, x1, a, b, 2*radius), shaft(x0, x1, b, radius)
    ).clean()


def vertical_hole(x, z, y0, y1, radius):
    return cq.Solid.makeCylinder(radius, y1 - y0, Vector(x, y0, z), Vector(0, 1, 0))


def pattern(axis, radius, n, phase=0):
    for i in range(n):
        angle = phase + i * math.tau / n
        yield axis[0] + radius*math.cos(angle), axis[1] + radius*math.sin(angle)


def screw(x0, x1, axis, r=2.5):
    return shaft(x0, x1, axis, r).fuse(shaft(x1, x1+3, axis, r+1.7)).clean()


def pulley(x, p, bore, pitch, outside, phase):
    # Pitch envelope with flanges and a compact axial hub. Commercial profile varies.
    hub = (x+5, x+8) if phase else (x-8, x-5)
    return shaft(x-4, x+4, p, pitch-.32).fuse(
        shaft(x-5, x-4, p, outside), shaft(x+4, x+5, p, outside),
        shaft(*hub, p, min(outside, bore/2+3.5)),
    ).cut(shaft(x-9, x+9, p, bore/2)).clean()


def belt(x, a, b):
    dy, dz = b[0] - a[0], b[1] - a[1]
    cx, cz = dy/CENTER, dz/CENTER
    phi = math.acos(-DELTA / CENTER)

    def capsule(dr):
        a_r, b_r = SMALL+dr, LARGE+dr
        va = [(-DELTA/CENTER, math.sin(phi)), (-DELTA/CENTER, -math.sin(phi))]
        points = []
        for r, origin, pair in [(a_r, a, va), (b_r, b, va[::-1])]:
            for along, across in pair:
                points.append((origin[0]+r*(along*cx-across*cz),
                               origin[1]+r*(along*cz+across*cx)))
        return plate(x-3, x+3, points).fuse(
            shaft(x-3, x+3, a, a_r), shaft(x-3, x+3, b, b_r)
        ).clean()

    core = capsule(-.3)
    return capsule(1.1).cut(core).clean()


def wheel():
    axis = WHEEL
    disks = [ring(x, x+4, axis, 75, 64).fuse(shaft(x, x+4, axis, 18)) for x in (370, 416)]
    blade = box(374, 416, axis[0]+42, axis[0]+74, axis[1]-1.75, axis[1]+1.75)
    spoke = box(370, 374, axis[0]+14, axis[0]+69, axis[1]-3.5, axis[1]+3.5)
    origin = Vector(0, *axis)
    axis_end = Vector(1, *axis)
    features = [*disks]
    for n in range(8):
        angle = 45 * n
        features.extend((spoke.rotate(origin, axis_end, angle),
                         spoke.translate(Vector(46, 0, 0)).rotate(origin, axis_end, angle),
                         blade.rotate(origin, axis_end, angle)))
    return features[0].fuse(*features[1:]).cut(
        shaft(369, 421, axis, 4.3),
        *(shaft(369, 421, p, 1.7) for p in pattern(axis, 12, 4))
    ).clean()


def hood(x0, x1, axis, inner, outer, start, stop):
    y, z = axis
    angles = [math.radians(start+(stop-start)*i/48) for i in range(49)]
    return plate(x0, x1, [(y+r*math.sin(a), z+r*math.cos(a))
                           for r, angles in [(outer, angles), (inner, angles[::-1])] for a in angles])


old = json.loads((BASE / "CAD_parameters.json").read_text(encoding="utf-8"))
old_parts = []
for data in old["parts"]:
    if data["group"] == "propulsion_reference" or data["code"] == "E05-BATTERY-REFERENCE":
        continue
    shape = cq.importers.importStep(str(BASE / data["file"])).val()
    old_parts.append((data["code"], shape, data["color"]))

pod = []


def add(code, geometry, material, note="", moving=True):
    assert geometry.isValid(), code
    assert geometry.Solids(), code
    pod.append((code, geometry, material, note, moving))


for z in (-4, 45):
    holes = [vertical_hole(x, z, 102, 135, 2.75) for x in (214, 247)]
    add(f"A01-TOP-REACH-{z}", box(207, 292, 128.05, 132.05, z-9, z+9).cut(*holes),
        "aluminum", "4 mm strap, fixed to rail by two M5 bolts", False)
    add(f"A02-LOWER-CLAMP-{z}", box(207, 254, 105, 109, z-9, z+9).cut(*holes),
        "aluminum", "4 mm clamp saddle", False)
    for x in (214, 247):
        add(f"A03-CLAMP-BOLT-{z}-{x}", vertical_hole(x, z, 103, 136, 2.5),
            "steel", "M5 x 35 reference shank", False)

mount_points = [(154, -4), (154, 45)]
spreader_points = [(JACK1[0]+28, JACK1[1]), (WHEEL[0]-28, WHEEL[1])]
guard_mount = (JACK1[0], JACK1[1]+15)
add("A04-FIXED-HEIGHT-PLATE", box(286, 292, 132.05, 179, -15, 56).cut(
    *(shaft(285, 293, p, 2.75) for p in mount_points)), "aluminum",
    "6 mm plate joins the strap ends. Mechanically fasten or TIG join aluminum before mounting.", False)

for index, p in enumerate(mount_points, 1):
    add(f"A06-HEIGHT-FASTENER-{index}", screw(283, 299, p), "steel", "M5 x 16 reference", False)

for inside, x0, x1 in ((True, 292, 299), (False, 352, 359)):
    features = [shaft(x0, x1, p, r) for p, r in zip(AXES, (18, 12, 12, 15)) if inside or p != MOTOR]
    for a, b in zip(AXES, AXES[1:]):
        if inside or a != MOTOR:
            features.append(link(x0, x1, a, b, 17 if inside else 14))
    cuts = [shaft(x0-1, x1+1, p, r) for p, r in zip(AXES[1:], (8, 8, 11))]
    for axis, p in zip((JACK1, WHEEL), spreader_points):
        features.extend((link(x0, x1, axis, p, 9), shaft(x0, x1, p, 6)))
        cuts.append(shaft(x0-1, x1+1, p, 2.25))
    if inside:
        for p, anchor in zip(mount_points, (JACK1, MOTOR)):
            features.extend((link(x0, x1, anchor, p, 17), slot(x0, x1, p, 30, 8.7)))
            cuts.append(slot(x0-1, x1+1, p, 30, 2.75))
        # Move the motor along the first belt's centerline to change effective tension.
        cuts.append(slot(x0-1, x1+1, MOTOR, 4, 7, MOTOR_TENSION_DIRECTION))
        cuts.extend(slot(x0-1, x1+1, p, 4, 1.65, MOTOR_TENSION_DIRECTION)
                    for p in pattern(MOTOR, 11, 4, math.pi/4))
    else:
        features.extend((link(x0, x1, JACK1, guard_mount, 9), shaft(x0, x1, guard_mount, 5.5)))
        cuts.append(shaft(x0-1, x1+1, guard_mount, 1.65))
    add("A05-INNER-CARRIER" if inside else "A07-OUTER-CARRIER",
        features[0].fuse(*features[1:]).cut(*cuts).clean(), "aluminum",
        "7 mm bearing carrier. Shaft holes nominal. Ream to fit measured bearings.")

# Space the two carriers outside the belt loops.
for i, p in enumerate(spreader_points, 1):
    add(f"A08-SPREADER-{i}", ring(299, 352, p, 4, 1.65), "aluminum",
        "53 mm spacer tapped M4 at both ends")

body = shaft(261, 292, MOTOR, 14).cut(shaft(285, 293, MOTOR, 7))
add("D01-ABC2215-REFERENCE", body, "motor",
    "Generic diameter 28 x 31 envelope. 3 mm shaft per listing. Measure actual shell, shaft stickout and mounting pattern.")
add("D02-MOTOR-AXLE-3", shaft(285, 313, MOTOR, 1.5), "steel", "Reference shaft")

for i, x in enumerate((304, 323, 342), 1):
    a, b = AXES[i-1:i+1]
    add(f"D03-PULLEY-16T-S{i}", pulley(x, a, 3 if i == 1 else 5, SMALL, 6.8, True),
        "aluminum", "GT2 2 mm pitch, belt width 6 mm. Envelope excludes tooth detail.")
    add(f"D04-PULLEY-60T-S{i}", pulley(x, b, 8 if i == 3 else 5, LARGE, 20.5, i != 3),
        "aluminum", "GT2 2 mm pitch, belt width 6 mm. Envelope excludes tooth detail.")
    add(f"D05-BELT-220-S{i}", belt(x, a, b), "belt", "220 mm pitch length, 110T. Simplified toothless belt.")

for i, p in enumerate(AXES[1:], 1):
    is_output = i == 3
    inner, outer, width = (4, 11, 7) if is_output else (2.5, 8, 5)
    add(f"D06-AXLE-{i}", shaft(287, 421 if is_output else 364, p, inner),
        "steel", "Stainless shaft. Add retaining collars located clear of deck and guard.")
    add(f"D07-INNER-BEARING-{i}", ring(292, 292+width, p, outer, inner),
        "steel", "608-2RS" if is_output else "625-2RS")
    add(f"D08-OUTER-BEARING-{i}", ring(359-width, 359, p, outer, inner),
        "steel", "608-2RS" if is_output else "625-2RS")

hub = ring(360, 370, WHEEL, 11, 4).fuse(ring(367, 370, WHEEL, 17, 4)).cut(
    *(shaft(366, 371, p, 1.7) for p in pattern(WHEEL, 12, 4))
).clean()
add("W01-8MM-HUB-REFERENCE", hub, "aluminum",
    "8 mm metal clamp hub. Flange OD34 with 4 x M3 on PCD24 modeled. Match actual hub before printing.")
add("W02-PADDLE-WHEEL-150", wheel(), "PETG",
    "150 OD x 50, 8 blades, ring/spoke disks, bore 8.6 and 4 x 3.4 on PCD24.")
add("W03-PADDLE-GUARD", hood(371, 425, WHEEL, 81, 84, 0, 180), "guard",
    "Upper splash guard, removable. Nominal 6 mm radial gap; add side protection before powered trials.")
tab_elbow = (198, guard_mount[1])
tab_end = (198, WHEEL[1])
add("W04-GUARD-TOP-TAB", box(359, 396, 196, 200, WHEEL[1]-10, WHEEL[1]+10).fuse(
    link(359, 363, guard_mount, tab_elbow, 8),
    link(359, 363, tab_elbow, tab_end, 8),
    shaft(359, 363, guard_mount, 5.5)
).cut(shaft(358, 364, guard_mount, 1.65)).clean(), "aluminum",
    "Mount with M3 into outer carrier pad. Fasten guard flange to top tab.")

battery = box(147, 187, 143, 171, -207, -92)
for file, geometry in [("W02_Paddle_150", wheel()), ("W03_Upper_Guard", pod[-2][1])]:
    # Rotate so the wheel axis is vertical on the build plate, then center and raise to Z=0.
    aligned = geometry.rotate(Vector(), Vector(0, 1, 0), -90) if file.startswith("W02") else geometry
    bb = aligned.BoundingBox()
    aligned = aligned.translate(Vector(-(bb.xmax+bb.xmin)/2, -(bb.ymax+bb.ymin)/2, -bb.zmin))
    cq.exporters.export(aligned, str(PRINT / f"{file}.stl"), tolerance=.08, angularTolerance=.12)

assembly = cq.Assembly(name=NAME)
drive = cq.Assembly(name=NAME + "_Drive")
right = cq.Assembly(name=NAME + "_Right")
for code, shape, color in old_parts:
    assembly.add(shape, name=code, color=cq.Color(*color))
assembly.add(battery, name="E05-3S-PACK-REFERENCE", color=cq.Color(*COLORS["battery"]))

new_parts = []
for side in ("R", "L"):
    for code, positive, material, note, moving in pod:
        shape = positive if side == "R" else positive.mirror("YZ")
        label = f"PH-{side}-{code}"
        color = cq.Color(*COLORS[material])
        assembly.add(shape, name=label, color=color)
        drive.add(shape, name=label, color=color)
        if side == "R":
            right.add(shape, name=label, color=color)
            cq.exporters.export(shape, str(PARTS / f"{code}.step"))
        new_parts.append((label, shape, material, note, moving))

for model in (assembly, drive, right):
    model.export(str(OUT / f"{model.name}.step"))


def bounds(geometry):
    bb = geometry.BoundingBox()
    return [bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax]


def overlap(a, b):
    return all(min(a[i+3], b[i+3]) - max(a[i], b[i]) > .0001 for i in range(3))


def intersections(first, second, self_check=False):
    result = []
    secondary = [(code, shape, bounds(shape)) for code, shape, *_ in second]
    for index, (code, shape, *_) in enumerate(first):
        bb = bounds(shape)
        for other, target, target_bb in secondary[index+1 if self_check else 0:]:
            if overlap(bb, target_bb):
                shared = shape.intersect(target)
                volume = sum(solid.Volume() for solid in shared.Solids())
                if volume > .05:
                    result.append([code, other, round(volume, 3)])
    return result


def expected_solids(shape):
    return len(shape.Solids())


records = [
    dict(code=label, material=material, note=note, bounds_mm=bounds(shape), solids=expected_solids(shape),
         volume_mm3=shape.Volume(), mass_g=round(shape.Volume()*DENSITY[material]/1000, 2)
         if material in DENSITY else None)
    for label, shape, material, note, _ in new_parts
]
right_parts = [p for p in new_parts if p[0].startswith("PH-R")]
moving = [part for part in right_parts if part[-1]]
fixed = [part for part in right_parts if not part[-1] and "FASTENER" not in part[0]]
motion = {}
for offset in (-15, 0, 15):
    shifted = [(code, shape.translate(Vector(0, offset, 0))) for code, shape, *_ in moving]
    sweep = shaft(370, 420, (WHEEL[0]+offset, WHEEL[1]), 75)
    motion[str(offset)] = {
        "moving_vs_boat": intersections(shifted, old_parts),
        "moving_vs_brackets": intersections(shifted, fixed),
        "rotating_wheel_sweep_vs_boat": intersections([("swept wheel", sweep)], old_parts),
    }

report = dict(
    assembly=NAME, component_count=len(old_parts)+1+len(new_parts),
    assembly_solid_count=sum(expected_solids(shape) for _, shape, *_ in [*old_parts, *new_parts])+1,
    ratio=(60/16)**3, belt_pitch_length_mm=220, pulley_centers_mm=CENTER,
    shafts_yz_mm=dict(zip(("motor", "jack1", "jack2", "wheel"), AXES)),
    bounds_mm=bounds(cq.Compound.makeCompound([shape for _, shape, *_ in [*old_parts, *new_parts]])),
    pod_modeled_mass_excluding_motor_g=round(sum(row["mass_g"] or 0 for row in records)/2, 1),
    nominal_new_vs_boat=intersections(new_parts, [*old_parts, ("3S-reference", battery)]),
    within_right_pod=intersections(right_parts, right_parts, self_check=True),
    motion=motion, records=records,
    physical_verified=False,
)
# Compact geometry data for review or reproduction.
(OUT / "CAD_Check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({key: value for key, value in report.items() if key != "records"}, indent=2))
