"""Native unwrap packing on a many-chart organic surface and a self-covering ramp."""
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp import blender_geometry as geometry

bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4, radius=1)
lumpy = bpy.context.active_object
lumpy.name = 'Lumpy'
# Per-vertex radial noise splits Smart UV Project into many charts, like a generated surface.
rng = np.random.default_rng(3)
for vertex in lumpy.data.vertices:
    vertex.co *= 1 + 0.15 * rng.standard_normal()

state = bridge.dispatch('session_control', {'action': 'inspect'})
lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'unwrap',
                                          'expected_project': state['project_id']})['lease_id']
result = bridge.dispatch('owned_edit', {'operation': 'unwrap_mesh', 'params': {
    'lease_id': lease, 'name': 'Lumpy', 'angle_limit_degrees': 66, 'island_margin': None,
    'margin_px': 4, 'texture_resolution': 1024, 'uv_layer': None}})
uv = lumpy.data.uv_layers.active.data
area = 0.0
for polygon in lumpy.data.polygons:
    a, b, c = (np.array(uv[i].uv) for i in polygon.loop_indices)
    area += abs(np.cross(b - a, c - a)) / 2
layout = bridge.dispatch('inspect_uv_layout', {'names': ['Lumpy'], 'texture_resolution': [1024, 1024],
                                               'padding_pixels': 4})
print(f"unwrap: {layout['charts']} charts, UV coverage {area:.3f}, border "
      f"{layout['padding']['minimum_border_pixels']:.2f} px, overlaps {layout['overlap']['triangle_pairs']}")
assert layout['charts'] > 200, layout['charts']
assert layout['overlap']['triangle_pairs'] == 0, layout['overlap']
assert layout['padding']['triangle_pairs_below_requested'] == 0, layout['padding']
assert layout['padding']['minimum_border_pixels'] > 3.99, layout['padding']
assert area > 0.3, area
assert result['margin_uv'] == 4 / 1024, result

# A ramp of one and a half turns projects as one Smart UV chart that covers itself.
ramp = bmesh.new()
steps, rings = 96, 6
grid = []
for s in range(steps + 1):
    turn = 3 * math.pi * s / steps
    grid.append([ramp.verts.new((r * math.cos(turn), r * math.sin(turn), .12 * turn / (2 * math.pi)))
                 for r in (.5 + .5 * k / rings for k in range(rings + 1))])
for s in range(steps):
    for k in range(rings):
        ramp.faces.new((grid[s][k], grid[s + 1][k], grid[s + 1][k + 1], grid[s][k + 1]))
spiral = bpy.data.objects.new('Ramp', bpy.data.meshes.new('Ramp'))
ramp.to_mesh(spiral.data)
ramp.free()
bpy.context.scene.collection.objects.link(spiral)
bridge.dispatch('owned_edit', {'operation': 'unwrap_mesh', 'params': {
    'lease_id': lease, 'name': 'Ramp', 'angle_limit_degrees': 66, 'island_margin': None,
    'margin_px': 4, 'texture_resolution': 1024, 'uv_layer': None}})
folded = bridge.dispatch('inspect_uv_layout', {'names': ['Ramp'], 'texture_resolution': [1024, 1024],
                                               'padding_pixels': 4})
print(f"ramp: {folded['charts']} charts, overlaps {folded['overlap']['triangle_pairs']}, border "
      f"{folded['padding']['border_triangles_below_requested']}")
assert folded['overlap']['triangle_pairs'] == 0, folded['overlap']
assert folded['padding']['border_triangles_below_requested'] == 0, folded['padding']
assert folded['unique_tile_ready'], folded

# Decimation can weld corners onto each other; the collapsed faces are dissolved.
welded = bmesh.new()
a, b, c, d = (welded.verts.new(p) for p in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)))
welded.faces.new((a, b, c))
welded.faces.new((a, c, d))
twin = welded.verts.new((1, 1, 0))
welded.faces.new((b, twin, c))
sheet = bpy.data.meshes.new('Welded')
welded.to_mesh(sheet)
welded.free()
geometry.drop_collapsed(sheet)
sheet.calc_loop_triangles()
print(f"welded: {len(sheet.loop_triangles)} triangles")
assert [round(t.area, 6) for t in sheet.loop_triangles] == [.5, .5], [t.area for t in sheet.loop_triangles]
