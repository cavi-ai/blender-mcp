"""Private headless UV solver. Reads selected geometry only; never opens a project or bridge."""
import hashlib
import json
import math
import runpy
import sys
from pathlib import Path

import bpy


def solve(request):
    from cavi_blender_mcp.blender_geometry import PACK
    from cavi_blender_mcp.uv_regions import frame, map_uv, quality, region

    spec = region(request['region'])
    mesh = bpy.data.meshes.new('UVRegion')
    mesh.from_pydata(request['vertices'], [], request['faces'])
    mesh.update()
    if [list(f.vertices) for f in mesh.polygons] != request['faces']:
        raise ValueError('Native mesh changed face-loop ordering')
    mesh.uv_layers.new(name='UVRegion')
    value = bpy.data.objects.new('UVRegion', mesh)
    bpy.context.scene.collection.objects.link(value)
    for item in bpy.context.selected_objects:
        item.select_set(False)
    value.select_set(True)
    bpy.context.view_layer.objects.active = value
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    if 'FINISHED' not in bpy.ops.uv.smart_project(angle_limit=math.radians(request['angle']),
            island_margin=0, correct_aspect=False, scale_to_bounds=False, rotate_method='AXIS_ALIGNED'):
        raise RuntimeError('Native UV projection failed')
    _, scale = frame(spec)
    margin = min(.49, spec['margin_px']/scale*1.25)
    for attempt in range(3):
        bpy.ops.uv.select_all(action='SELECT')
        if 'FINISHED' not in bpy.ops.uv.pack_islands(margin=margin, scale=True, **PACK):
            raise RuntimeError('Native UV packing failed')
        bpy.ops.object.mode_set(mode='OBJECT')
        # Edit Mode rebuilds custom data; reacquire the RNA layer after leaving it.
        rows = [tuple(item.uv) for item in mesh.uv_layers['UVRegion'].data]
        rows, report = quality(map_uv(rows, spec), request['triangles'], request['triangle_vertices'], spec)
        if report['passed']:
            return {'uv': rows, 'quality': report, 'attempts': attempt+1, 'blender': bpy.app.version_string}
        margin = min(.49, max(margin*1.5, .001))
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
    raise ValueError('Native packing did not meet the requested overlap and pixel-padding checks')


if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).with_name('bootstrap.py')))['load_package']()
    input_path, output_path = map(Path, sys.argv[sys.argv.index('--')+1:])
    payload = input_path.read_bytes()
    if len(payload) > 16*1024*1024:
        raise ValueError('UV worker input exceeds 16 MiB')
    result = solve(json.loads(payload))
    result['input_sha256'] = hashlib.sha256(payload).hexdigest()
    output_path.write_text(json.dumps(result))
