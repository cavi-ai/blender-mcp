"""Native signed clearance, component union, sampling coverage and frame restoration."""

import sys
from pathlib import Path

import bmesh
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cavi_blender_mcp import blender_bridge as bridge

for value in list(bpy.data.objects):
    bpy.data.objects.remove(value, do_unlink=True)
scene = bpy.context.scene
scene.unit_settings.scale_length = 1

def cube(name, scale, location=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=2, location=location)
    value = bpy.context.object
    value.name = name
    value.scale = (scale,)*3
    return value
body = cube('Body', 1)
outside = cube('Outside', 1.2)
inside = cube('Inside', .8)
animated = cube('Animated', 1.2)
for frame, scale in ((1, 1.2), (25, .8)):
    animated.scale = (scale,)*3
    animated.keyframe_insert('scale', frame=frame)
mesh = bpy.data.meshes.new('Cross')
mesh.from_pydata([(-3, -2, 0), (3, -2, 0), (0, 3, 0)], [], [(0, 1, 2)])
cross = bpy.data.objects.new('Cross', mesh)
scene.collection.objects.link(cross)
opened = cube('OpenBody', 1)
bm = bmesh.new()
bm.from_mesh(opened.data)
bm.faces.ensure_lookup_table()
bm.faces.remove(bm.faces[0])
bm.to_mesh(opened.data)
bm.free()
second = cube('UnionBody', 1, (.5, 0, 0))
coords = [tuple(vertex.co) for vertex in body.data.vertices]
coords += [tuple(vertex.co+second.location) for vertex in second.data.vertices]
faces = [tuple(face.vertices) for face in body.data.polygons]
faces += [tuple(index+8 for index in face.vertices) for face in second.data.polygons]
second.data = bpy.data.meshes.new('Union')
second.data.from_pydata(coords, [], faces)
second.location = (0, 0, 0)
scene.frame_set(7, subframe=.375)
bpy.context.view_layer.update()
prior = scene.frame_current, scene.frame_subframe

def inspect(name='Outside', **options):
    params = {'body': 'Body', 'garments': [name], 'start_frame': 1, 'end_frame': 25,
              'min_clearance_m': .1, 'samples': 3, **options}
    result = bridge.dispatch('inspect_skin_clearance', params)
    assert (scene.frame_current, scene.frame_subframe) == prior
    return result
result = inspect()
assert result['complete'] and result['passed'], result
assert abs(result['garments'][0]['min_clearance_m']-.2) < 1e-6
result = inspect('Inside')
assert result['complete'] and not result['passed'], result
assert result['garments'][0]['inside_samples'] > 0
assert abs(result['garments'][0]['min_clearance_m']+.2) < 1e-6
assert result['garments'][0]['violation_examples']
result = inspect('Animated')
# The midpoint is exact contact; it must remain ambiguous rather than pass.
assert not result['complete'] and not result['passed'], result
assert result['garments'][0]['ambiguous_samples'] > 0
assert result['garments'][0]['worst_frame'] == 25
assert inspect('Cross', surface_samples='vertices')['passed']
result = inspect('Cross')
assert result['complete'] and not result['passed'], result
assert result['garments'][0]['worst_probe']['kind'] == 'triangle_centre'
result = inspect('Inside', body='UnionBody')
assert result['complete'] and not result['passed'], result
assert result['body_topology'][0]['components'] == 2
result = inspect(body='OpenBody')
assert not result['complete'] and not result['passed']
assert result['body_topology'][0]['boundary_edges'] > 0
result = inspect(max_queries=1)
assert not result['complete'] and not result['passed'] and result['queries'] == 1
body.scale.x = -1
bpy.context.view_layer.update()
assert inspect()['passed']
scene.unit_settings.scale_length = .01
result = inspect(min_clearance_m=.001)
assert result['passed'] and abs(result['garments'][0]['min_clearance_m']-.002) < 1e-8
assert not inspect(min_clearance_m=.003)['passed']
print('Native garment clearance: signed gaps, animation, centres, component union, units and restoration passed')
