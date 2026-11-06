"""Native source-state audit layered on the artist extrusion fixture."""
import json
import os
import runpy
from pathlib import Path

import bpy

from cavi_blender_mcp.blender_mesh_regions import mesh_digest

runpy.run_path(str(Path(__file__).with_name('mesh_regions_fixture.py')))
root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
bpy.data.objects['Panel'].data.uv_layers['BakeAtlas'].data[0].pin_uv = True


@bpy.app.handlers.persistent
def audit(*_):
    value = bpy.data.objects.get('Panel')
    if value is None or len(value.data.vertices) != 12:
        return
    mesh = value.data
    (root/'uv-audit.json').write_text(json.dumps({'mesh': mesh.name, 'geometry': mesh_digest(mesh),
        'uvs': {l.name: [list(row.uv) for row in l.data] for l in mesh.uv_layers},
        'pins': {l.name: [row.pin_uv for row in l.data] for l in mesh.uv_layers},
        'float_colors': [list(row.color) for row in mesh.color_attributes['ArtistTint'].data],
        'materials': [(s.link, s.material.name if s.material else None) for s in value.material_slots],
        'selected': sorted(o.name for o in bpy.context.selected_objects), 'mode': bpy.context.mode,
        'active': bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None,
        'transform': [*value.location, *value.rotation_euler, *value.scale],
        'loops': {str(f.index): list(f.loop_indices) for f in mesh.polygons},
        'file': bpy.data.filepath}))


bpy.app.handlers.depsgraph_update_post.append(audit)
bpy.app.handlers.load_post.append(audit)
