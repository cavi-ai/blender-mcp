"""Native morph deltas, masks, relative chains, transforms and live channel bindings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_skin_transfer import (
    Matrix,
    Vector,
    bpy,
    edit,
    expected,
    options,
    rig,
    scene,
    source,
    surface,
    transform,
)

# Reuse the tested source surface, but give the target a different mirrored scale.
for bone in rig.pose.bones:
    bone.location = (0, 0, 0)
    bone.rotation_mode = 'XYZ'
    bone.rotation_euler = (0, 0, 0)
source.shape_key_add(name='Basis')
fit = source.shape_key_add(name='Fit')
for index, value in enumerate(fit.data):
    value.co.z += (.01, .03, .05)[index]
fit.vertex_group = 'BodyMask'
fit.slider_min, fit.slider_max = -1, 2
for frame, value in ((1, 0), (25, 1)):
    fit.value = value
    fit.keyframe_insert('value', frame=frame)
corrective = source.shape_key_add(name='Corrective')
corrective.relative_key = fit
for point, reference in zip(corrective.data, fit.data, strict=True):
    point.co = reference.co + Vector((0, .006, 0))
corrective.value = .3
scale = Matrix.Diagonal((.5, 2, -1.3, 1))
inverse = scale.inverted()
morph_target = surface('MorphTarget', [inverse @ Vector(value) for value in
                       [(.25, .25, .01), (.6, .1, .01), (.1, .6, .01)]])
morph_target.matrix_basis = transform @ scale
morph_target.shape_key_add(name='Basis')
existing = morph_target.shape_key_add(name='Existing')
for point in existing.data:
    point.co.x += .001
existing.value = .2
bpy.context.view_layer.update()
args = {**options, 'name': 'MorphTarget', 'shape_names': ['Fit', 'Corrective']}
for changes in ({'shape_names': ['Missing']}, {'shape_names': ['Fit', 'Fit']},
                {'shape_names': ['Basis']}):
    before = set(bpy.data.objects), set(bpy.data.meshes), set(bpy.data.shape_keys)
    try:
        edit('transfer_skin_weights', **{**args, **changes}, new_name='RejectedMorphs')
    except ValueError:
        pass
    else:
        raise AssertionError('Invalid morph selection accepted')
    assert before == (set(bpy.data.objects), set(bpy.data.meshes), set(bpy.data.shape_keys))
result = edit('transfer_skin_weights', **args, new_name='MorphSkin')
copy = bpy.data.objects[result['name']]
keys = copy.data.shape_keys
assert [item['name'] for item in result['morphs']] == ['Fit', 'Corrective']
assert keys != morph_target.data.shape_keys
assert set(morph_target.data.shape_keys.key_blocks.keys()) == {'Basis', 'Existing'}
assert keys.key_blocks['Existing'].value == existing.value
assert keys.key_blocks['Fit'].slider_min == -1 and keys.key_blocks['Fit'].slider_max == 2
for index, factors in enumerate(expected):
    z = sum(weight*delta for weight, delta in zip(factors, (.01, .03, .05), strict=True))*.314159
    expected_delta = inverse.to_3x3() @ Vector((0, 0, z))
    actual = keys.key_blocks['Fit'].data[index].co - keys.key_blocks[0].data[index].co
    assert (actual-expected_delta).length < 1e-7, (actual, expected_delta)
    actual = keys.key_blocks['Corrective'].data[index].co - keys.key_blocks[0].data[index].co
    assert (actual - inverse.to_3x3() @ Vector((0, .006, 0))).length < 1e-7
for frame, expected_value in ((1, 0), (25, 1)):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    evaluated = keys.evaluated_get(bpy.context.evaluated_depsgraph_get())
    assert abs(evaluated.key_blocks['Fit'].value-expected_value) < 1e-6
fit.mute = True
source.data.shape_keys.update_tag()
bpy.context.view_layer.update()
evaluated = keys.evaluated_get(bpy.context.evaluated_depsgraph_get())
assert evaluated.key_blocks['Fit'].value == 0
print('Native morph transfer: masked deltas, relative chains, mirrored transforms and live weights/mute passed')
