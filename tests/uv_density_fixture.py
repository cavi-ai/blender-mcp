"""Rigged source and save observers for a selected-face physical density case."""
import json
import os
import runpy
from pathlib import Path

import bpy

from cavi_blender_mcp.blender_mesh_regions import mesh_digest

runpy.run_path(str(Path(__file__).with_name('uv_transform_fixture.py')))
root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
surface = bpy.data.objects['TileGrid']
surface.location = (7, 2, 3)
surface.rotation_euler = (.2, .1, .3)
surface.scale = (2, 3, 1)
surface.data.shape_keys.key_blocks['Lift'].value = .5
bpy.context.scene.unit_settings.system = 'METRIC'
bpy.context.scene.unit_settings.scale_length = .01
surface.data.polygons[1].material_index = 1
surface.data.uv_layers['UVMap'].data[0].pin_uv = True
surface.data.uv_layers['UVMap'].data[4].pin_uv = True
color = surface.data.color_attributes.new(name='Tint', type='FLOAT_COLOR', domain='CORNER')
for i, row in enumerate(color.data):
    row.color = (.1234567+i*.001, .2345678, .3456789, 1)
bpy.context.view_layer.update()


@bpy.app.handlers.persistent
def audit(*_):
    obj = bpy.data.objects['TileGrid']
    mesh = obj.data
    (root/'density-audit.json').write_text(json.dumps({
        'geometry': mesh_digest(mesh),
        'uvs': {l.name: [list(row.uv) for row in l.data] for l in mesh.uv_layers},
        'pins': {l.name: [row.pin_uv for row in l.data] for l in mesh.uv_layers},
        'keys': {k.name: {'value': k.value, 'points': [list(p.co) for p in k.data]}
                 for k in mesh.shape_keys.key_blocks},
        'weights': [[(g.group, g.weight) for g in v.groups] for v in mesh.vertices],
        'modifiers': [(m.name, m.type, m.object.name) for m in obj.modifiers],
        'parent': obj.parent.name, 'materials': [s.material.name for s in obj.material_slots],
        'slots': [f.material_index for f in mesh.polygons],
        'colors': [list(row.color) for row in mesh.color_attributes['Tint'].data],
        'seams': [e.use_seam for e in mesh.edges], 'face_selection': [f.select for f in mesh.polygons],
        'transform': [*obj.location, *obj.rotation_euler, *obj.scale],
        'selected': sorted(o.name for o in bpy.context.selected_objects), 'mode': bpy.context.mode,
        'active': bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None,
        'active_uv': mesh.uv_layers.active_index, 'render_uv': [l.active_render for l in mesh.uv_layers],
        'scene_units': [bpy.context.scene.unit_settings.system, bpy.context.scene.unit_settings.scale_length]}))


bpy.app.handlers.save_post.append(audit)
bpy.app.handlers.load_post.append(audit)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'), check_existing=False)
