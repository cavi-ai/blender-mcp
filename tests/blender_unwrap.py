"""Native unwrap packing on a many-chart organic surface."""
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cavi_blender_mcp import blender_bridge as bridge

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
