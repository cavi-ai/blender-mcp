"""Native barycentric transfer, originals, budgets and animated binding checks."""

import sys
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cavi_blender_mcp import blender_bridge as bridge

for value in list(bpy.data.objects):
    bpy.data.objects.remove(value, do_unlink=True)
scene = bpy.context.scene
scene.unit_settings.scale_length = 1
controller = bpy.data.objects.new('BodyControl', None)
scene.collection.objects.link(controller)
for frame, value in ((1, 0), (25, .2)):
    controller.location.x = value
    controller.keyframe_insert('location', frame=frame)
state = bridge.dispatch('session_control', {'action': 'inspect'})
lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'skin-transfer-test',
                                          'expected_project': state['project_id']})['lease_id']
def edit(operation, **params):
    return bridge.dispatch('owned_edit', {'operation': operation, 'params': {**params, 'lease_id': lease}})
edit('create_armature', name='Rig', bones=[{'name': name, 'head': [0, 0, 0],
     'tail': [0, 0, 1]} for name in ('A', 'B', 'C')])
rig = bpy.data.objects['Rig']
rig.parent = controller
transform = Matrix.LocRotScale(Vector((2, -1, .3)), Euler((.1, .2, .3)).to_quaternion(),
                              Vector((1.5, .75, 2)))
rig.matrix_basis = transform

def surface(name, coordinates):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(coordinates, [], [(0, 1, 2)])
    value = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(value)
    value.parent = controller
    value.matrix_basis = transform
    return value
source = surface('Body', [(0, 0, 0), (1, 0, 0), (0, 1, 0)])
source.modifiers.new('Skin', 'ARMATURE').object = rig
for index, name in enumerate(('A', 'B', 'C')):
    source.vertex_groups.new(name=name).add([index], 1, 'REPLACE')
source.vertex_groups.new(name='BodyMask').add([0, 1, 2], .314159, 'REPLACE')
target = surface('Coat', [(.25, .25, .01), (.6, .1, .01), (.1, .6, .01)])
target.vertex_groups.new(name='FinishMask').add([0, 1, 2], .1234567, 'REPLACE')
target.data.uv_layers.new(name='CoatUV')
for loop in target.data.uv_layers.active.data:
    loop.uv = (.12345, .76543)
target.data.materials.append(bpy.data.materials.new('Cloth'))
target.shape_key_add(name='Basis')
puff = target.shape_key_add(name='Puff')
for point in puff.data:
    point.co.z += .002
puff.value = .35
scene.frame_set(7, subframe=.25)
bpy.context.view_layer.update()
prior_frame = scene.frame_current, scene.frame_subframe
originals = {value.name: (value.data, value.parent, value.matrix_world.copy(),
             [[(g.group, g.weight) for g in vertex.groups] for vertex in value.data.vertices])
             for value in (source, target)}
options = {'name': 'Coat', 'source': 'Body', 'max_distance_m': .021,
           'max_discarded_weight': 0., 'max_influences': 3}
for name, changes in (('TooFar', {'max_distance_m': .001}),
                      ('TooFew', {'max_influences': 1, 'max_discarded_weight': .001})):
    objects, meshes = set(bpy.data.objects), set(bpy.data.meshes)
    try:
        edit('transfer_skin_weights', **{**options, **changes, 'new_name': name})
    except ValueError as error:
        assert 'before edits' in str(error), error
    else:
        raise AssertionError('Transfer budget violation accepted')
    assert set(bpy.data.objects) == objects and set(bpy.data.meshes) == meshes
result = edit('transfer_skin_weights', **options, new_name='CoatSkin')
copy = bpy.data.objects[result['name']]
assert result['scope'] == 'rest_base_surface_weight_transfer'
assert abs(result['max_distance_m']-.02) < 1e-6, result
scene.unit_settings.scale_length = .01
scaled = edit('transfer_skin_weights', **{**options, 'max_distance_m': .00021}, new_name='MetricSkin')
assert abs(scaled['max_distance_m']-.0002) < 1e-8, scaled
scene.unit_settings.scale_length = 1
limited = edit('transfer_skin_weights', **{**options, 'max_influences': 2,
               'max_discarded_weight': .251}, new_name='LimitedSkin')
assert abs(limited['max_discarded_weight']-.25) < 1e-6, limited
assert limited['weights']['max_influences'] == 2
limited_skin = bpy.data.objects['LimitedSkin']
assert abs(limited_skin.vertex_groups['A'].weight(0)-2/3) < 1e-6
# The two equal analytic candidates can differ by native projection roundoff.
remaining = [item.weight for item in limited_skin.data.vertices[0].groups
             if limited_skin.vertex_groups[item.group].name in ('B', 'C') and item.weight > 0]
assert len(remaining) == 1 and abs(remaining[0]-1/3) < 1e-6
expected = [( .5, .25, .25), (.3, .6, .1), (.3, .1, .6)]
for index, values in enumerate(expected):
    for bone, weight in zip(('A', 'B', 'C'), values, strict=True):
        assert abs(copy.vertex_groups[bone].weight(index)-weight) < 1e-6
    assert abs(copy.vertex_groups['FinishMask'].weight(index)-.1234567) < 1e-7
assert copy.data != target.data and copy.data.shape_keys != target.data.shape_keys
assert copy.data.materials[:] == target.data.materials[:]
assert list(copy.data.uv_layers.active.data[0].uv) == list(target.data.uv_layers.active.data[0].uv)
assert (scene.frame_current, scene.frame_subframe) == prior_frame
for value in (source, target):
    data, parent, world, groups = originals[value.name]
    assert value.data == data and value.parent == parent and value.matrix_world == world
    assert groups == [[(g.group, g.weight) for g in vertex.groups] for vertex in value.data.vertices]
for frame, angle in ((1, 0), (25, .4)):
    scene.frame_set(frame)
    rig.pose.bones['B'].rotation_mode = 'XYZ'
    rig.pose.bones['B'].rotation_euler.z = angle
    rig.pose.bones['C'].location.z = .1 if frame == 25 else 0
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = copy.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        for index, factors in enumerate(expected):
            rest = copy.data.shape_keys.key_blocks['Basis'].data[index].co.copy()
            rest += (copy.data.shape_keys.key_blocks['Puff'].data[index].co-rest)*puff.value
            rest = rig.matrix_world.inverted() @ copy.matrix_world @ rest
            posed = Vector((0, 0, 0))
            for bone, factor in zip(('A', 'B', 'C'), factors, strict=True):
                posed += (rig.pose.bones[bone].matrix @ rig.data.bones[bone].matrix_local.inverted() @ rest)*factor
            error = ((evaluated.matrix_world @ mesh.vertices[index].co) - (rig.matrix_world @ posed)).length
            assert error < 2e-6, error
    finally:
        evaluated.to_mesh_clear()
# A float32 barycentric transform can put an exact corner outside the admission tolerance.
triangle = [(0.3108440935611725, -0.015848562121391296, 1.1760691404342651),
            (0.30041956901550293, -0.018298104405403137, 1.1816051006317139),
            (0.2994089126586914, -0.01226722914725542, 1.1807605028152466)]
precise_source = surface('CornerSource', triangle)
precise_target = surface('CornerTarget', [triangle[1], triangle[0], triangle[2]])
for value in (precise_source, precise_target):
    value.parent = None
    value.matrix_world = Matrix.Identity(4)
precise_source.modifiers.new('Skin', 'ARMATURE').object = rig
for index, name in enumerate(('A', 'B', 'C')):
    precise_source.vertex_groups.new(name=name).add([index], 1, 'REPLACE')
bpy.context.view_layer.update()
original_meshes = (precise_source.data, precise_target.data)
precise = edit('transfer_skin_weights', name='CornerTarget', source='CornerSource',
               new_name='CornerSkin', max_distance_m=1e-6, max_discarded_weight=0., max_influences=3)
precise_copy = bpy.data.objects[precise['name']]
for index, bone in enumerate(('B', 'A', 'C')):
    assert abs(precise_copy.vertex_groups[bone].weight(index)-1) < 1e-6
assert (precise_source.data, precise_target.data) == original_meshes
print('Native skin transfer: barycentric weights, exact corners, motion, originals and rejection budgets passed')
