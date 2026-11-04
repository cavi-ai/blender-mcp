"""Measure declared bone-local contact markers against a world-Z ground plane."""

import math

import bpy
from mathutils import Vector


def contact_frames(rig, action, window):
    required = {'bone', 'point', 'start_frame', 'end_frame', 'max_drift_m', 'max_height_error_m', 'ground_z_m'}
    if not isinstance(window, dict) or not required <= set(window) or set(window) - required - {'samples'}:
        raise ValueError('Invalid contact window fields')
    start, end, count = window['start_frame'], window['end_frame'], window.get('samples', 9)
    if (type(start) is not int or type(end) is not int or not 1 <= start < end <= 1000000
            or start < action.frame_range[0] or end > action.frame_range[1]
            or type(count) is not int or not 2 <= count <= 32):
        raise ValueError('Contact windows need 2 to 32 samples within the action range')
    if window['bone'] not in rig.pose.bones:
        raise ValueError('Contact bone does not exist')
    point = window['point']
    numbers = [window[k] for k in ('max_drift_m', 'max_height_error_m', 'ground_z_m')]
    if (not isinstance(point, (list, tuple)) or len(point) != 3 or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
            for x in [*point, *numbers]) or min(numbers[:2]) < 0):
        raise ValueError('Contact points and budgets must be finite, with nonnegative tolerances')
    frames = [start+(end-start)*i/(count-1) for i in range(count)]
    return frames


def report(rig, action, windows):
    if not isinstance(windows, list) or not 1 <= len(windows) <= 16:
        raise ValueError('contacts must contain 1 to 16 declared windows')
    unit = bpy.context.scene.unit_settings.scale_length
    if not math.isfinite(unit) or unit <= 0:
        raise ValueError('Contact measurements need a finite positive metre scale')
    result = []
    for window in windows:
        frames = contact_frames(rig, action, window)
        point = window['point']
        positions = []
        for frame in frames:
            integer = math.floor(frame)
            bpy.context.scene.frame_set(integer, subframe=frame-integer)
            bpy.context.view_layer.update()
            evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
            positions.append((evaluated.matrix_world @ evaluated.pose.bones[window['bone']].matrix @ Vector(point))*unit)
        origin = positions[0]
        drift = [math.hypot(p.x-origin.x, p.y-origin.y) for p in positions]
        height = [abs(p.z-window['ground_z_m']) for p in positions]
        maximum_drift, maximum_height = max(drift), max(height)
        result.append({**window, 'sample_frames': frames, 'max_drift_m': maximum_drift,
            'max_height_error_m': maximum_height, 'drift_limit_m': window['max_drift_m'],
            'height_limit_m': window['max_height_error_m'],
            'worst_drift_frame': frames[drift.index(maximum_drift)],
            'worst_height_frame': frames[height.index(maximum_height)],
            'passed': maximum_drift <= window['max_drift_m'] and maximum_height <= window['max_height_error_m'],
            'scope': 'sampled_bone_marker_world_z_ground'})
    return result
