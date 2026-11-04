"""Rest-relative orientation transfer with target offsets and explicit root scaling."""

import math

import bpy
from mathutils import Euler, Matrix


def prepare(source, target, pairs, raw):
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {'root', 'root_translation_scale', 'alignment_degrees'}:
        raise ValueError('Invalid retarget calibration fields')
    root, scale = raw.get('root'), raw.get('root_translation_scale')
    angles = raw.get('alignment_degrees', [0, 0, 0])
    if root not in pairs or source.data.bones[root].parent or target.data.bones[pairs[root]].parent:
        raise ValueError('Calibration root must map two root bones')
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('root_translation_scale must be finite and positive')
    if not isinstance(angles, (list, tuple)) or len(angles) != 3 or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in angles):
        raise ValueError('alignment_degrees needs three finite numbers')
    animation = target.animation_data
    if animation and (animation.drivers or any(t.strips for t in animation.nla_tracks)):
        raise ValueError('Use a target copy without pose drivers or NLA strips for calibrated transfer')
    targets = set(pairs.values())
    for name in targets:
        bone = target.pose.bones[name]
        if bone.constraints:
            raise ValueError('Use a constraint-free target copy for calibrated transfer')
        if bone.parent and bone.parent.name not in targets:
            raise ValueError('Calibrated mapping must include target bone parents')
    for rig in (source, target):
        for bone in rig.data.bones:
            if any(not math.isfinite(x) for row in bone.matrix_local for x in row):
                raise ValueError('Calibration needs finite rest matrices')
    return {'root': root, 'target_root': pairs[root], 'root_translation_scale': scale,
            'alignment_degrees': list(angles),
            'alignment': Euler([math.radians(x) for x in angles], 'XYZ').to_quaternion()}


def apply(source, target, ordered, profile):
    alignment = profile['alignment']
    desired = {}
    for src, dst in ordered:
        source_bone, target_bone = source.pose.bones[src], target.pose.bones[dst]
        if any(not math.isfinite(x) for row in source_bone.matrix for x in row):
            raise ValueError('Source pose has nonfinite calibrated transforms')
        rest = target_bone.bone.matrix_local
        delta = source_bone.matrix.to_quaternion() @ source_bone.bone.matrix_local.to_quaternion().inverted()
        rotation = alignment @ delta @ alignment.inverted() @ rest.to_quaternion()
        parent = target_bone.parent
        location = ((parent.matrix @ parent.bone.matrix_local.inverted() @ rest).translation
                    if parent else rest.translation.copy())
        if src == profile['root']:
            location += (alignment @ (source_bone.matrix.translation - source_bone.bone.head_local)
                         * profile['root_translation_scale'])
        matrix = Matrix.LocRotScale(location, rotation, (1, 1, 1))
        target_bone.rotation_mode = 'QUATERNION'
        target_bone.matrix = matrix
        desired[dst] = matrix
        bpy.context.view_layer.update()
    for name, matrix in desired.items():
        actual = target.pose.bones[name].matrix
        if max(abs(actual[r][c]-matrix[r][c]) for r in range(4) for c in range(4)) > 1e-4:
            raise ValueError('Target inheritance cannot preserve calibrated pose matrices')
