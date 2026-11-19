"""Render the meshes exported from the verified Rev E CAD geometry."""
from pathlib import Path
import json
import sys

OLD=Path('C:/Users/Administrator/Documents/Codex/2026-10-22/solid-mini-prototype-scale-model-350')
sys.path.insert(0,str(OLD/'work/cad_runtime_b'))
import vtk
import numpy as np
from vtk.util.numpy_support import numpy_to_vtk

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/Warirak_PVC4_RevF_Full'
data=json.loads((OUT/'CAD_parameters.json').read_text(encoding='utf-8'))

for name,position,up,explode in [
    ('assembled',(1000,770,1100),(0,1,0),False),
    ('exploded',(1000,770,1100),(0,1,0),True),
    ('top',(0,1500,0),(0,0,1),False),
    ('front',(0,150,1500),(0,1,0),False),
    ('frame_assembled',(1000,770,1100),(0,1,0),False),
    ('frame_exploded',(1000,770,1100),(0,1,0),True),
    ('frame_reference',(1000,1150,1100),(0,1,0),False),
]:
    renderer=vtk.vtkRenderer()
    renderer.SetBackground(.965,.980,.981)
    window=vtk.vtkRenderWindow()
    window.AddRenderer(renderer)
    window.SetOffScreenRendering(1)
    window.SetSize(1600,1000) if name=='frame_reference' else window.SetSize(1500,1150)
    window.SetMultiSamples(8)

    for part in data['parts']:
        if name.startswith('frame_') and part['group']!='welded_frame':
            continue
        mesh=part['mesh']
        points=vtk.vtkPoints()
        points.SetData(numpy_to_vtk(np.asarray(mesh['vertices'],dtype=np.float32),deep=True))
        triangles=vtk.vtkCellArray()
        for face in mesh['triangles']:
            triangles.InsertNextCell(3)
            for index in face:
                triangles.InsertCellPoint(index)
        poly=vtk.vtkPolyData()
        poly.SetPoints(points)
        poly.SetPolys(triangles)
        normals=vtk.vtkPolyDataNormals()
        normals.SetInputData(poly)
        normals.SetFeatureAngle(40)
        mapper=vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(normals.GetOutputPort())
        actor=vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*((.58,.62,.63) if name.startswith('frame_') else part['color']))
        actor.GetProperty().SetAmbient(.35)
        actor.GetProperty().SetDiffuse(.65)
        if part['code'].endswith('-BOX') or part['code'].endswith('-LID'):
            actor.GetProperty().SetOpacity(.4)
        if explode:
            actor.SetPosition(*part['exploded'])
        renderer.AddActor(actor)
        if name.startswith('frame_'):
            clean=vtk.vtkCleanPolyData()
            clean.SetInputData(poly)
            edges=vtk.vtkFeatureEdges()
            edges.SetInputConnection(clean.GetOutputPort())
            edges.FeatureEdgesOn();edges.BoundaryEdgesOn()
            edges.NonManifoldEdgesOff();edges.ManifoldEdgesOff();edges.SetFeatureAngle(25)
            edge_mapper=vtk.vtkPolyDataMapper()
            edge_mapper.SetInputConnection(edges.GetOutputPort());edge_mapper.ScalarVisibilityOff()
            edge_actor=vtk.vtkActor();edge_actor.SetMapper(edge_mapper)
            edge_actor.GetProperty().SetColor(.06,.09,.10)
            edge_actor.GetProperty().SetLineWidth(1.15)
            if explode:edge_actor.SetPosition(*part['exploded'])
            renderer.AddActor(edge_actor)

    camera=renderer.GetActiveCamera()
    camera.ParallelProjectionOn()
    camera.SetFocalPoint(0,115,0)
    camera.SetPosition(*position)
    camera.SetViewUp(*up)
    renderer.ResetCamera()
    camera.Zoom(1.45 if name=='frame_reference' else (.87 if explode else .98))
    renderer.ResetCameraClippingRange()

    title=vtk.vtkTextActor()
    title.SetInput('WARIRAK | '+('STEEL FRAME ONLY' if name.startswith('frame_') else 'PVC 4 INCH')+' | REV F')
    title.SetPosition(35,1090)
    title.GetTextProperty().SetColor(.08,.23,.26)
    title.GetTextProperty().SetFontSize(29)
    if name!='frame_reference':renderer.AddViewProp(title)
    caption=vtk.vtkTextActor()
    caption.SetInput(('SHS20 x 20 x 1.2 mm  |  Base480 x 500 mm  |  Mount tabs620 mm overall' if name.startswith('frame_') else '2 x OD114 x 600 mm pipes  |  Steel base480 x 500 mm  |  Conveyor32deg + 5W solar roof') +
                     ('  |  EXPLODED VIEW' if explode else ''))
    caption.SetPosition(35,1053)
    caption.GetTextProperty().SetColor(.25,.40,.43)
    caption.GetTextProperty().SetFontSize(21)
    if name!='frame_reference':renderer.AddViewProp(caption)
    foot=vtk.vtkTextActor()
    foot.SetInput('X = width   Y = up   Z = bow    |    Bought components are reference envelopes')
    foot.SetPosition(35,25)
    foot.GetTextProperty().SetColor(.25,.40,.43)
    foot.GetTextProperty().SetFontSize(19)
    if name!='frame_reference':renderer.AddViewProp(foot)
    window.Render()
    capture=vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.ReadFrontBufferOff()
    capture.Update()
    writer=vtk.vtkPNGWriter()
    writer.SetFileName(str(OUT/'images'/f'{name}.png'))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()
    window.Finalize()
    print('RENDERED',name,flush=True)
