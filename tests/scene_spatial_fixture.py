"""Placement cases with independently known metre gaps and scene-state readback."""
import json
import os
from pathlib import Path

import bpy

root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
scene = bpy.context.scene
for value in list(bpy.data.objects):
    bpy.data.objects.remove(value, do_unlink=True)
scene.unit_settings.scale_length = .5
scene.frame_set(17)


def mesh(name, points, faces):
    data = bpy.data.meshes.new(name)
    data.from_pydata(points, [], faces)
    value = bpy.data.objects.new(name, data)
    scene.collection.objects.link(value)
    return value


subject = mesh('Shelter', [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)], [(0, 1, 2, 3)])
parent = bpy.data.objects.new('Parent', None)
scene.collection.objects.link(parent)
parent.location = (2, 0, 0)
parent.scale = (2, 1, 1)
subject.parent = parent
mesh('Above', [(-20, -20, 2), (20, -20, 2), (20, 20, 2), (-20, 20, 2)], [(0, 1, 2, 3)])
mesh('Crossing', [(4, -2, -2), (4, 4, -2), (4, 4, 2), (4, -2, 2)], [(0, 1, 2, 3)])
mesh('SparseTown', [(-10, 0, 0), (-8, 0, 0), (-8, 2, 0), (-10, 2, 0),
                    (10, 0, 0), (12, 0, 0), (12, 2, 0), (10, 2, 0)],
     [(0, 1, 2, 3), (4, 5, 6, 7)])
generated = mesh('Generated', [(0, 6, 0), (2, 6, 0), (2, 8, 0), (0, 8, 0)], [(0, 1, 2, 3)])
solidify = generated.modifiers.new('Thickness', 'SOLIDIFY')
solidify.thickness = 2
solidify.offset = -1
bpy.ops.mesh.primitive_cube_add(size=20, location=(2, 0, 0))
bpy.context.object.name = 'Enclosing'
subject.select_set(True)
bpy.context.view_layer.objects.active = subject


@bpy.app.handlers.persistent
def audit(*_):
    (root/'audit.json').write_text(json.dumps({
        'frame': scene.frame_current, 'unit': scene.unit_settings.scale_length,
        'active': bpy.context.view_layer.objects.active.name,
        'objects': {o.name: {'matrix': [list(row) for row in o.matrix_world],
            'selected': o.select_get(), 'hidden': o.hide_render,
            'vertices': [list(v.co) for v in o.data.vertices] if o.type == 'MESH' else None,
            'modifiers': [[m.name, m.type] for m in o.modifiers]}
            for o in bpy.data.objects}}))


bpy.context.view_layer.update()
bpy.app.handlers.save_post.append(audit)
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'), check_existing=False)
