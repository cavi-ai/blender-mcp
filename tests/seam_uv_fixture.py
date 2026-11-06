"""Closed sleeve with authored caps and a read-only native data audit."""
import json
import math
import os
from pathlib import Path

import bpy

from cavi_blender_mcp.blender_mesh_regions import mesh_digest

root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
bpy.data.objects.remove(bpy.data.objects['Cube'], do_unlink=True)
points = [(math.cos(i*math.tau/8), math.sin(i*math.tau/8), z) for z in (0, 1) for i in range(8)]
faces = [(i, (i+1)%8, (i+1)%8+8, i+8) for i in range(8)]
faces += [tuple(reversed(range(8))), tuple(range(8, 16))]
mesh = bpy.data.meshes.new('SleeveSource')
mesh.from_pydata(points, [], faces)
mesh.update()
value = bpy.data.objects.new('Sleeve', mesh)
bpy.context.scene.collection.objects.link(value)
value.location = (.25, -.1, .3)
value.rotation_euler = (.1, .2, .3)
value.scale = (.7, 1.2, 1.5)
mesh['finish'] = 'authored'
mesh.materials.append(bpy.data.materials.new('Body'))
mesh.materials.append(bpy.data.materials.new('Caps'))
for face in mesh.polygons:
    face.material_index = int(face.index >= 8)
for name in ('BakeAtlas', 'ArtistUV'):
    layer = mesh.uv_layers.new(name=name)
    for face in mesh.polygons:
        for j, index in enumerate(face.loop_indices):
            angle = j*math.tau/face.loop_total
            layer.data[index].uv = (.15+.04*math.cos(angle), .15+.04*math.sin(angle))
            layer.data[index].pin_uv = face.index >= 8
mesh.uv_layers.active_index = 1
mesh.uv_layers['BakeAtlas'].active_render = True
color = mesh.color_attributes.new(name='Finish', type='FLOAT_COLOR', domain='CORNER')
for i, item in enumerate(color.data):
    item.color = (.1234567+i*.001, .2345678, .3456789, 1)
next(edge for edge in mesh.edges if all(mesh.vertices[i].co.z == 0 for i in edge.vertices)).use_seam = True
group = value.vertex_groups.new(name='RetainedWeight')
group.add([0], .375, 'REPLACE')


@bpy.app.handlers.persistent
def audit(*_):
    obj = bpy.data.objects['Sleeve']
    data = obj.data
    (root/'seam-audit.json').write_text(json.dumps({
        'geometry': mesh_digest(data), 'seams': [e.use_seam for e in data.edges],
        'uvs': {l.name: [list(row.uv) for row in l.data] for l in data.uv_layers},
        'pins': {l.name: [row.pin_uv for row in l.data] for l in data.uv_layers},
        'colors': [list(row.color) for row in data.color_attributes['Finish'].data],
        'materials': [(s.link, s.material.name) for s in obj.material_slots],
        'material_indices': [f.material_index for f in data.polygons],
        'weights': [[(g.group, g.weight) for g in v.groups] for v in data.vertices],
        'custom_property': data['finish'], 'transform': [*obj.location, *obj.rotation_euler, *obj.scale],
        'selected': sorted(o.name for o in bpy.context.selected_objects),
        'active': bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None,
        'mode': bpy.context.mode, 'active_uv': data.uv_layers.active.name,
        'render_uv': next(l.name for l in data.uv_layers if l.active_render),
        'loops': {str(f.index): list(f.loop_indices) for f in data.polygons},
        'native_unwrap_methods': [i.identifier for i in bpy.ops.uv.unwrap.get_rna_type().properties['method'].enum_items],
        'blender': bpy.app.version_string}))


bpy.app.handlers.depsgraph_update_post.append(audit)
bpy.app.handlers.load_post.append(audit)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'), check_existing=False)
audit()
