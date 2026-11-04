"""Read-only sampled world-space comparison of an authored rig and a baked/exported copy."""

import math

import bpy
import numpy as np
from mathutils.kdtree import KDTree


def set_frame(frame):
    integer = math.floor(frame)
    bpy.context.scene.frame_set(integer, subframe=frame - integer)
    bpy.context.view_layer.update()


def world_points(value, depsgraph):
    from .blender_mesh_sample import snapshot

    return snapshot(value, depsgraph)[0]


def aligned(points, matrix, meters):
    return (points @ matrix[:3, :3].T + matrix[:3, 3]) * meters


def nearest(left, right):
    origin = left[0]
    left, right = left - origin, right - origin
    tree = KDTree(len(right))
    for i, point in enumerate(right):
        tree.insert(point, i)
    tree.balance()
    return np.asarray([tree.find(point)[2] for point in left], np.float64)


def compare(p, find_object):
    if bpy.context.mode != 'OBJECT':
        raise ValueError('Compare rigs in Object Mode')
    source, candidate = find_object(p['source']), find_object(p['candidate'])
    if any(rig.type != 'ARMATURE' for rig in (source, candidate)):
        raise ValueError('source and candidate must name armatures')
    pairs = p['meshes']
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 8:
        raise ValueError('Provide 1..8 source/candidate skin pairs')
    if any(set(pair) != {'source', 'candidate'} for pair in pairs):
        raise ValueError('Skin pairs declare source and candidate')
    if any(len({pair[key] for pair in pairs}) != len(pairs) for key in ('source', 'candidate')):
        raise ValueError('Skin pair names must be unique')
    meshes = []
    for pair in pairs:
        values = [find_object(pair[key], mesh=True) for key in ('source', 'candidate')]
        for value, rig in zip(values, (source, candidate), strict=True):
            modifiers = [m for m in value.modifiers if m.type == 'ARMATURE']
            if len(modifiers) != 1 or modifiers[0].object != rig or not modifiers[0].show_viewport:
                raise ValueError('Each skin must have an enabled modifier bound to its declared rig')
        meshes.append(values)
    samples = p.get('samples', 9)
    start, end = p['start_frame'], p['end_frame']
    offset = p.get('candidate_frame_offset', 0)
    tolerance = p['max_error_m']
    space = p.get('space', 'world')
    matching = p.get('vertex_match', 'index')
    if (type(samples) is not int or not 2 <= samples <= 32 or type(start) is not int
            or type(end) is not int or not 1 <= start < end <= 1000000
            or isinstance(offset, bool) or not math.isfinite(offset) or abs(offset) > 1000000
            or isinstance(tolerance, bool) or not math.isfinite(tolerance) or tolerance < 0
            or space not in ('world', 'start_root') or matching not in ('index', 'point_set')):
        raise ValueError('Invalid comparison frames, samples, space, matching or metre tolerance')
    source_bones, candidate_bones = set(source.pose.bones.keys()), set(candidate.pose.bones.keys())
    if not source_bones or not candidate_bones or max(len(source_bones), len(candidate_bones)) > 512:
        raise ValueError('Comparison requires 1..512 bones per rig')
    shared = sorted(source_bones & candidate_bones)
    frames = np.linspace(start, end, samples).tolist()
    scene = bpy.context.scene
    prior_frame, prior_subframe = scene.frame_current, scene.frame_subframe
    meters = scene.unit_settings.scale_length
    if not math.isfinite(meters) or meters <= 0:
        raise ValueError('Scene metre scale must be positive and finite')
    reports = [{**pair, 'max_error_m': 0., 'rms_error_m': 0., 'worst_source_frame': None,
                'source_motion_m': 0., 'candidate_motion_m': 0.} for pair in pairs]
    squares, counts = [0.] * len(pairs), [0] * len(pairs)
    first = [None, None]
    anchors = [None, None]
    bone_error = 0.
    work = 0
    try:
        for frame in frames:
            poses, bones = [], []
            for side, (rig, time) in enumerate(((source, frame), (candidate, frame + offset))):
                set_frame(time)
                depsgraph = bpy.context.evaluated_depsgraph_get()
                evaluated = rig.evaluated_get(depsgraph)
                if anchors[side] is None:
                    anchors[side] = np.asarray(evaluated.matrix_world.inverted(), np.float64) if space == 'start_root' else np.eye(4)
                points = []
                for values in meshes:
                    value = world_points(values[side], depsgraph)
                    work += len(value)
                    if work > 4000000:
                        raise ValueError('Comparison exceeds four million evaluated vertex samples')
                    points.append(aligned(value, anchors[side], meters))
                world = evaluated.matrix_world
                endpoints = np.asarray([tuple(world @ point) for name in shared
                    for point in (evaluated.pose.bones[name].head,)], np.float64).reshape(-1, 3)
                if not np.isfinite(endpoints).all():
                    raise ValueError('Compared bone endpoints must be finite')
                bones.append(aligned(endpoints, anchors[side], meters))
                poses.append(points)
                if first[side] is None:
                    first[side] = [value.copy() for value in points]
            if shared:
                bone_error = max(bone_error, float(np.linalg.norm(bones[0] - bones[1], axis=1).max()))
            for i, (left, right) in enumerate(zip(*poses, strict=True)):
                if matching == 'index':
                    if left.shape != right.shape:
                        raise ValueError('Index matching requires equal evaluated vertex counts')
                    distances = np.linalg.norm(left - right, axis=1)
                else:
                    distances = np.concatenate((nearest(left, right), nearest(right, left)))
                maximum = float(distances.max())
                report = reports[i]
                report['source_vertices'], report['candidate_vertices'] = len(left), len(right)
                if maximum > report['max_error_m']:
                    report['max_error_m'], report['worst_source_frame'] = maximum, frame
                squares[i] += float(distances @ distances)
                counts[i] += len(distances)
                for side, points in enumerate((left, right)):
                    if points.shape != first[side][i].shape:
                        raise ValueError('Evaluated topology changes during the comparison')
                    key = 'source_motion_m' if side == 0 else 'candidate_motion_m'
                    report[key] = max(report[key], float(np.linalg.norm(points - first[side][i], axis=1).max()))
        for i, report in enumerate(reports):
            report['rms_error_m'] = math.sqrt(squares[i] / counts[i])
    finally:
        scene.frame_set(prior_frame, subframe=prior_subframe)
    missing = sorted(source_bones - candidate_bones)
    extra = sorted(candidate_bones - source_bones)
    maximum = max([bone_error, *(report['max_error_m'] for report in reports)])
    return {'scope': 'sampled_evaluated_rig_motion', 'source': source.name, 'candidate': candidate.name,
            'frames': frames, 'candidate_frame_offset': offset, 'space': space, 'vertex_match': matching,
            'max_error_m': maximum, 'tolerance_m': tolerance, 'passed': not missing and not extra and maximum <= tolerance,
            'bone_head_error_m': bone_error, 'missing_bones': missing, 'extra_bones': extra,
            'meshes': reports, 'scene_unit_meters': meters,
            'not_checked': ['unsampled times', 'bone roll and tail reconstruction', 'normal/tangent deformation', 'foot contact', 'Unity import']}
