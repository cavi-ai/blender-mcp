"""Measure declared bone-local contact markers against a world-Z ground plane."""

import math

import bpy
from mathutils import Vector

from .blender_frame_map import mapped_frames


def contact_frames(rig, action, window, frame_offset=0, frame_scale=1):
    required = {'bone', 'point', 'start_frame', 'end_frame', 'max_drift_m', 'max_height_error_m', 'ground_z_m'}
    if not isinstance(window, dict) or not required <= set(window) or set(window) - required - {'samples'}:
        raise ValueError('Invalid contact window fields')
    start, end, count = window['start_frame'], window['end_frame'], window.get('samples', 9)
    if (type(start) is not int or type(end) is not int or not 1 <= start < end <= 1000000
            or type(count) is not int or not 2 <= count <= 32):
        raise ValueError('Contact windows need 2 to 32 samples within the action range')
    mapped = mapped_frames([start, end], frame_scale, frame_offset)
    if (mapped[0] < action.frame_range[0]-1e-4 or mapped[1] > action.frame_range[1]+1e-4):
        raise ValueError('Contact windows need 2 to 32 samples within the action range')
    if window['bone'] not in rig.pose.bones:
        raise ValueError('Contact bone does not exist')
    point = window['point']
    numbers = [window[k] for k in ('max_drift_m', 'max_height_error_m', 'ground_z_m')]
    if (not isinstance(point, (list, tuple)) or len(point) != 3 or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
            for x in [*point, *numbers]) or min(numbers[:2]) < 0):
        raise ValueError('Contact points and budgets must be finite, with nonnegative tolerances')
    return mapped_frames([start+(end-start)*i/(count-1) for i in range(count)], frame_scale, frame_offset)


def report(rig, action, windows, reference=None, frame_offset=0, frame_scale=1):
    if not isinstance(windows, list) or not 1 <= len(windows) <= 16:
        raise ValueError('contacts must contain 1 to 16 declared windows')
    unit = bpy.context.scene.unit_settings.scale_length
    if not math.isfinite(unit) or unit <= 0:
        raise ValueError('Contact measurements need a finite positive metre scale')
    result = []
    for window in windows:
        frames = contact_frames(rig, action, window, frame_offset, frame_scale)
        point = Vector(window['point'])
        conversion = None
        basis_error = 0.0
        positions = []
        for frame in frames:
            if reference is not None:
                ref_rig, _ = reference
                source_frame = (frame-frame_offset)/frame_scale
                integer = math.floor(source_frame)
                bpy.context.scene.frame_set(integer, subframe=source_frame-integer)
                bpy.context.view_layer.update()
                source = ref_rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
                source_basis = (source.matrix_world.to_3x3()
                                @ ref_rig.data.bones[window['bone']].matrix_local.to_3x3())
            integer = math.floor(frame)
            bpy.context.scene.frame_set(integer, subframe=frame-integer)
            bpy.context.view_layer.update()
            evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
            if reference is not None:
                candidate_basis = (evaluated.matrix_world.to_3x3()
                                   @ rig.data.bones[window['bone']].matrix_local.to_3x3())
                try:
                    inverse = candidate_basis.inverted()
                    source_basis.inverted()
                except ValueError as exc:
                    raise ValueError('Contact reference needs invertible source and candidate bases') from exc
                observed = inverse @ source_basis
                if any(not math.isfinite(x) for row in observed for x in row):
                    raise ValueError('Contact reference has nonfinite axes')
                if conversion is None:
                    conversion = observed.copy()
                    point = conversion @ Vector(window['point'])
                basis_error = max(basis_error, max(abs(observed[r][c]-conversion[r][c])
                                                   for r in range(3) for c in range(3)))
            position = (evaluated.matrix_world @ evaluated.pose.bones[window['bone']].matrix @ point)*unit
            if any(not math.isfinite(x) for x in position):
                raise ValueError('Contact marker has nonfinite world coordinates')
            positions.append(position)
        origin = positions[0]
        drift = [math.hypot(p.x-origin.x, p.y-origin.y) for p in positions]
        height = [abs(p.z-window['ground_z_m']) for p in positions]
        maximum_drift, maximum_height = max(drift), max(height)
        measured = {**window, 'sample_frames': frames, 'max_drift_m': maximum_drift,
            'max_height_error_m': maximum_height, 'drift_limit_m': window['max_drift_m'],
            'height_limit_m': window['max_height_error_m'],
            'worst_drift_frame': frames[drift.index(maximum_drift)],
            'worst_height_frame': frames[height.index(maximum_height)],
            'passed': maximum_drift <= window['max_drift_m'] and maximum_height <= window['max_height_error_m'] and basis_error <= 1e-5,
            'scope': 'sampled_bone_marker_world_z_ground'}
        if reference is not None:
            measured.update(contact_reference={'armature': reference[0].name, 'action': reference[1].name},
                            mapped_point=list(point), reference_basis_stable=basis_error <= 1e-5,
                            reference_basis_max_error=basis_error)
        if frame_offset != 0 or reference is not None or frame_scale != 1:
            measured.update(candidate_frame_offset=frame_offset,
                            reference_sample_frames=[(frame-frame_offset)/frame_scale for frame in frames])
        if frame_scale != 1:
            measured['candidate_frame_scale'] = frame_scale
        result.append(measured)
    return result
