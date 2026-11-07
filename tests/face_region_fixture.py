"""Connected, folded and ambiguous surfaces alongside a fully rigged source."""
import json
import os
import runpy
from pathlib import Path

import bpy

runpy.run_path(str(Path(__file__).with_name('face_material_fixture.py')))
root=Path(os.environ['CAVI_BLENDER_WORKSPACE'])
for edge in bpy.data.objects['TileGrid'].data.edges:
    if set(edge.vertices)=={1,2}:
        edge.use_seam=True


def object(name,points,polygons):
    mesh=bpy.data.meshes.new(name)
    mesh.from_pydata(points,[],polygons)
    mesh.update()
    mesh.materials.append(bpy.data.materials['ArtistFinish'])
    uv=mesh.uv_layers.new(name='UVMap')
    for face in mesh.polygons:
        for index,loop in enumerate(face.loop_indices):
            uv.data[loop].uv=((index%2)*.4+.1,(index//2)*.4+.1)
    value=bpy.data.objects.new(name,mesh)
    bpy.context.scene.collection.objects.link(value)


object('FoldedPanel',[(0,0,0),(1,0,0),(1,1,0),(0,1,0),(1,0,1),(1,1,1),(1,0,2),(1,1,2),
                      (0,0,0),(-1,0,0),(-1,1,0),(0,1,0)],
       [(0,1,2,3),(1,4,5,2),(4,6,7,5),(8,9,10,11)])
object('AmbiguousPanel',[(0,0,0),(1,0,0),(.5,1,0),(.5,-1,0),(.5,0,1)],
       [(0,1,2),(1,0,3),(0,1,4)])


@bpy.app.handlers.persistent
def audit(*_):
    result={}
    for name in ('FoldedPanel','AmbiguousPanel'):
        value=bpy.data.objects[name]
        mesh=value.data
        result[name]={'vertices':[list(v.co) for v in mesh.vertices],
            'faces':[list(f.vertices) for f in mesh.polygons],
            'seams':[e.use_seam for e in mesh.edges],
            'materials':[s.material.name if s.material else None for s in value.material_slots],
            'slots':[f.material_index for f in mesh.polygons],
            'uvs':{l.name:[list(v.uv) for v in l.data] for l in mesh.uv_layers}}
    (root/'region-audit.json').write_text(json.dumps(result))


bpy.app.handlers.save_post.append(audit)
bpy.app.handlers.load_post.append(audit)
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'),check_existing=False)
