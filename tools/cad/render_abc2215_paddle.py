"""Generate isometric images from the exported Rev H STEP shapes."""

import json
from pathlib import Path

import cadquery as cq
import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "outputs/Warirak_PVC3_RevG_Full"
OUT = ROOT / "output/Warirak_PVC3_ABC2215_RevH"
base = json.loads((BASE / "CAD_parameters.json").read_text(encoding="utf-8"))
new = json.loads((OUT / "CAD_Check.json").read_text(encoding="utf-8"))
COLORS = {"aluminum": (.65,.72,.76), "steel": (.34,.40,.45), "PETG": (.08,.51,.53),
          "guard": (.94,.64,.14), "motor": (.73,.24,.14), "belt": (.17,.2,.24)}


def imported_mesh(path):
    shape = cq.importers.importStep(str(path)).val()
    points, faces = shape.tessellate(.14, .16)
    return dict(vertices=[p.toTuple() for p in points], triangles=faces)


def actor(mesh, color, opacity=1):
    points = vtk.vtkPoints()
    points.SetData(numpy_to_vtk(np.asarray(mesh["vertices"],dtype=np.float32),deep=True))
    polys = vtk.vtkCellArray()
    for face in mesh["triangles"]:
        polys.InsertNextCell(3)
        for index in face:
            polys.InsertCellPoint(index)
    poly = vtk.vtkPolyData()
    poly.SetPoints(points)
    poly.SetPolys(polys)
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(poly)
    normals.SetFeatureAngle(35)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(normals.GetOutputPort())
    result = vtk.vtkActor()
    result.SetMapper(mapper)
    prop = result.GetProperty()
    prop.SetColor(*color)
    prop.SetAmbient(.35)
    prop.SetDiffuse(.65)
    prop.SetOpacity(opacity)
    return result


def label(renderer, words, size, y, color):
    title = vtk.vtkTextActor()
    title.SetInput(words)
    title.SetPosition(34, y)
    title.GetTextProperty().SetColor(*color)
    title.GetTextProperty().SetFontSize(size)
    renderer.AddViewProp(title)


meshes = [(row, imported_mesh(OUT / "Drive_STEP" / f'{row["code"][5:]}.step'))
          for row in new["records"] if row["code"].startswith("PH-R-")]
for detail in (False, True):
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(.945,.966,.968)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(1500,1050)
    window.SetMultiSamples(8)
    window.AddRenderer(renderer)
    if not detail:
        for part in base["parts"]:
            if part["group"] == "propulsion_reference" or part["code"] == "E05-BATTERY-REFERENCE":
                continue
            renderer.AddActor(actor(part["mesh"], part["color"]))

    for row, mesh in meshes:
        opacity = .44 if "PADDLE-GUARD" in row["code"] and detail else 1
        renderer.AddActor(actor(mesh, COLORS[row["material"]], opacity))
        if not detail:
            mirror = dict(vertices=[(-x,y,z) for x,y,z in mesh["vertices"]],
                          triangles=[(a,c,b) for a,b,c in mesh["triangles"]])
            renderer.AddActor(actor(mirror, COLORS[row["material"]]))

    camera=renderer.GetActiveCamera()
    camera.ParallelProjectionOn()
    camera.SetFocalPoint(*( (342,161,-25) if detail else (0,125,0) ))
    camera.SetPosition(*( (1000,495,625) if detail else (1000,750,1100) ))
    camera.SetViewUp(0,1,0)
    renderer.ResetCamera()
    camera.Zoom(1.02 if detail else 1.03)
    renderer.ResetCameraClippingRange()
    label(renderer, "WARIRAK  |  REV H  |  " + ("RIGHT DRIVE" if detail else "ABC 2215 PADDLE BOAT"),
          32, 987, (.10,.22,.25))
    label(renderer, "3 x 16T : 60T stages  /  52.73 : 1  /  30 mm height travel" if detail else
          "Twin PVC OD89 x 600  /  Twin paddle wheels OD150 x 50  /  Beam 850 mm", 20, 951, (.24,.40,.42))
    label(renderer, "Reference CAD  |  Dimensions in millimeters  |  X transverse, Y up, Z bow",
          17, 23, (.24,.40,.42))
    window.Render()
    capture=vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.ReadFrontBufferOff()
    capture.Update()
    writer=vtk.vtkPNGWriter()
    writer.SetFileName(str(OUT / ("Drive.png" if detail else "Assembly.png")))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()
    window.Finalize()
