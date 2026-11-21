"""Native signed clearance, component union, sampling coverage and frame restoration."""

import sys
import unittest
from pathlib import Path

import bmesh
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp import blender_clearance

sys.path.insert(0, str(Path(__file__).parent))
from test_clearance_parity import ClearanceParityTests

native_parity = type('NativeClearanceParityTests', (ClearanceParityTests,), {'kernel': blender_clearance})
parity_result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(native_parity))
assert parity_result.wasSuccessful()

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
role_mesh = bpy.data.meshes.new('RoleGarment')
role_mesh.from_pydata([(1.1, -.5, -.5), (1.2, .5, -.5), (1.2, .5, .5),
                       (1.2, -.5, .5), (2, 0, 0)], [], [(0, 1, 2), (0, 2, 3)])
role_attr = role_mesh.attributes.new('garment_role', 'INT', 'FACE')
role_attr.data[0].value, role_attr.data[1].value = 0, 1
role_garment = bpy.data.objects.new('RoleGarment', role_mesh)
scene.collection.objects.link(role_garment)
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
rig_data = bpy.data.armatures.new('RestRigData')
rig = bpy.data.objects.new('RestRig', rig_data)
scene.collection.objects.link(rig)
for obj in (body, role_garment):
    mod = obj.modifiers.new('Rig', 'ARMATURE')
    mod.object = rig
rig_data.pose_position = 'POSE'
rest = inspect('RoleGarment', rest_armature='RestRig', sample_frames=[12.5])
assert rest['rest_armature'] == 'RestRig' and rig_data.pose_position == 'POSE'
rest_budget = inspect('RoleGarment', rest_armature='RestRig', sample_frames=[12.5], max_queries=1)
assert not rest_budget['complete'] and rig_data.pose_position == 'POSE'
for options in ({'sample_frames': [1, 2]}, {'sample_frames': [12.5], 'region_attribute': 'missing'}):
    try:
        inspect('RoleGarment', rest_armature='RestRig', **options)
    except ValueError:
        assert rig_data.pose_position == 'POSE' and (scene.frame_current, scene.frame_subframe) == prior
    else:
        raise AssertionError('Invalid rest clearance accepted')
shared = bpy.data.objects.new('SharedRestRig', rig_data)
scene.collection.objects.link(shared)
try:
    inspect('RoleGarment', rest_armature='RestRig', sample_frames=[12.5])
except ValueError:
    assert rig_data.pose_position == 'POSE'
else:
    raise AssertionError('Shared armature data accepted')
bpy.data.objects.remove(shared, do_unlink=True)
result = inspect()
assert result['complete'] and result['passed'], result
baseline = inspect('RoleGarment')
regional = inspect('RoleGarment', region_attribute='garment_role')
garment = regional['garments'][0]
buckets = garment.pop('regions')
assert regional == baseline, (regional, baseline)
assert {tuple(bucket['region_ids']) for bucket in buckets} == {(), (0,), (1,), (0, 1)}, buckets
assert sum(bucket['samples_checked'] for bucket in buckets) == garment['samples_checked'] == 21
for key in ('inside_samples', 'violating_samples', 'ambiguous_samples'):
    assert sum(bucket[key] for bucket in buckets) == garment[key], buckets
assert any(bucket['min_clearance_m'] == garment['min_clearance_m']
           and bucket['worst_probe'] == garment['worst_probe']
           and bucket['worst_frame'] == garment['worst_frame'] for bucket in buckets)
witnessed = inspect('RoleGarment', region_attribute='garment_role', include_worst_support=True)
rows = witnessed['garments'][0]
for row in (rows, *rows['regions']):
    support = row['worst_support']
    if row['min_clearance_m'] is not None:
        assert isinstance(support['body_triangle_index'], int) and 0 <= support['body_triangle_index'] < 12
        from mathutils import Vector
        distance = (Vector(support['garment_point_world']) - Vector(support['body_point_world'])).length
        assert abs(distance - abs(row['min_clearance_m'])) < 1e-5, row
    else:
        assert support is None
without = inspect('RoleGarment', region_attribute='garment_role')
rows.pop('worst_support')
for row in rows['regions']:
    row.pop('worst_support')
assert witnessed == without
empty = inspect('RoleGarment', region_attribute='garment_role', include_worst_support=True, max_queries=1)
assert empty['garments'][0]['worst_support'] is None
partial = inspect('RoleGarment', region_attribute='garment_role', max_queries=10)
partial_garment = partial['garments'][0]
assert not partial['complete'], partial
for key in ('samples_checked', 'inside_samples', 'violating_samples', 'ambiguous_samples'):
    assert sum(bucket[key] for bucket in partial_garment['regions']) == partial_garment[key], partial
for name, domain, datatype in [('wrong_domain', 'POINT', 'INT'), ('wrong_type', 'FACE', 'FLOAT')]:
    role_mesh.attributes.new(name, datatype, domain)
for name in ('absent', 'wrong_domain', 'wrong_type', '', 'x'*64):
    try:
        inspect('RoleGarment', region_attribute=name)
    except ValueError:
        assert (scene.frame_current, scene.frame_subframe) == prior
    else:
        raise AssertionError(f'Accepted invalid region_attribute {name!r}')
many_mesh = bpy.data.meshes.new('ManyRegions')
many_mesh.from_pydata([(2, i*.01, z) for i in range(65) for z in (0, .001, .002)], [],
                      [(3*i, 3*i+1, 3*i+2) for i in range(65)])
many_attr = many_mesh.attributes.new('garment_role', 'INT', 'FACE')
for index, entry in enumerate(many_attr.data):
    entry.value = index
many = bpy.data.objects.new('ManyRegions', many_mesh)
scene.collection.objects.link(many)
try:
    inspect('ManyRegions', region_attribute='garment_role')
except ValueError as error:
    assert '64 distinct' in str(error) and (scene.frame_current, scene.frame_subframe) == prior
else:
    raise AssertionError('Accepted more than 64 region buckets')
assert result['frames'] == [1., 13., 25.] and result['requested_samples'] == 3
result = inspect(sample_frames=[1., 12.5, 25.])
assert result['complete'] and result['frames'] == [1., 12.5, 25.] and result['requested_samples'] == 3
result = inspect(sample_frames=[12.5])
assert result['complete'] and result['frames'] == [12.5] and result['requested_samples'] == 1
result = inspect(sample_frames=[1., 12.5, 25.], max_queries=1)
assert not result['complete'] and result['frames'] == [1.] and result['requested_samples'] == 3
result = inspect(end_frame=3, sample_frames=[1, 2, 3], max_queries=1)
assert not result['complete'] and not result['all_frames_tested'], result
result = inspect(end_frame=3, sample_frames=[1, 2, 3])
assert result['complete'] and result['all_frames_tested'], result
result = inspect(end_frame=3, samples=9)
assert result['requested_samples'] == 9, result
for invalid in ([], [True], [float('nan')], [0], [26], [3, 3], [4, 2], list(range(1, 34))):
    try:
        inspect(sample_frames=invalid)
    except ValueError:
        assert (scene.frame_current, scene.frame_subframe) == prior
    else:
        raise AssertionError(f'Accepted invalid sample_frames {invalid!r}')
result = inspect()
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
# Unitless scenes measure one unit as one metre, as Blender's FBX export does.
scene.unit_settings.system = 'NONE'
result = inspect(min_clearance_m=.1)
assert result['scene_unit_meters'] == 1 and abs(result['garments'][0]['min_clearance_m']-.2) < 1e-6, result
scene.unit_settings.system = 'METRIC'
print('Native garment clearance: signed gaps, animation, centres, component union, units and restoration passed')
