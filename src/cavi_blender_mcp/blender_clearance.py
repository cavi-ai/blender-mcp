"""Sample signed garment clearance against closed evaluated body components."""

import math
from collections import defaultdict

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from .blender_frame_map import bounded_samples
from .blender_mesh_sample import snapshot
from .blender_motion_compare import set_frame
from .clearance_frames import validate_sample_frames

DIRECTIONS = [Vector(value).normalized() for value in
              ((1, .371, .529), (-.277, 1, .413), (.193, -.317, 1))]
EPSILON = 2**-20


class QueryBudgetReached(Exception):
    pass


class Budget:
    def __init__(self, maximum):
        self.used, self.maximum = 0, maximum

    def use(self):
        if self.used >= self.maximum:
            raise QueryBudgetReached
        self.used += 1


def vectors(points):
    values = [Vector(point) for point in points]
    if any(not math.isfinite(coordinate) for point in values for coordinate in point):
        raise ValueError('Sample coordinates exceed native geometry precision')
    return values


def components(points, faces):
    edges = defaultdict(list)
    parents = list(range(len(faces)))
    degenerate = 0
    for index, (a, b, c) in enumerate(faces):
        if (points[b]-points[a]).cross(points[c]-points[a]).length_squared == 0:
            degenerate += 1
        for left, right in ((a, b), (b, c), (c, a)):
            edges[tuple(sorted((left, right)))].append(index)
    status = {'boundary_edges': sum(len(owners)==1 for owners in edges.values()),
              'nonmanifold_edges': sum(len(owners)>2 for owners in edges.values()),
              'degenerate_triangles': degenerate, 'components': 0}
    if not len(faces) or any(status[key] for key in status):
        return [], status, []
    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index
    for owners in edges.values():
        parents[find(owners[1])] = find(owners[0])
    groups = defaultdict(list)
    for index, triangle in enumerate(faces):
        groups[find(index)].append((index, tuple(int(v) for v in triangle)))
    result = []
    face_owners = [None] * len(faces)
    for entries in groups.values():
        for face_index, _ in entries:
            face_owners[face_index] = len(result)
        triangles = [triangle for _, triangle in entries]
        indices = sorted({vertex for triangle in triangles for vertex in triangle})
        mapping = {vertex: index for index, vertex in enumerate(indices)}
        coordinates = [points[index] for index in indices]
        array = np.asarray(coordinates, np.float64)
        tree = BVHTree.FromPolygons(coordinates,
            [tuple(mapping[index] for index in triangle) for triangle in triangles], all_triangles=True)
        result.append((tree, array.min(axis=0), array.max(axis=0)))
    status['components'] = len(result)
    return result, status, face_owners


def inside_component(point, component, budget, reasons=None):
    budget.use()
    tree, lower, upper = component
    if np.any(np.asarray(point) < lower-EPSILON) or np.any(np.asarray(point) > upper+EPSILON):
        return False
    parities = []
    for direction in DIRECTIONS:
        origin, hits = point.copy(), 0
        seen = set()
        while True:
            budget.use()
            hit, _, face, distance = tree.ray_cast(origin, direction, 4.)
            if hit is None:
                break
            if face not in seen:
                if distance <= EPSILON/4:
                    if reasons is not None:
                        reasons.add('ray_hit_too_close')
                    return None
                seen.add(face)
                hits += 1
            advanced = hit + direction*(2*EPSILON)
            progress = (advanced-origin).dot(direction)
            if not math.isfinite(progress) or progress <= 0:
                if reasons is not None:
                    reasons.add('ray_no_progress')
                return None
            origin = advanced
        parities.append(hits % 2 == 1)
    if len(set(parities)) == 1:
        return parities[0]
    if reasons is not None:
        reasons.add('ray_parity_disagreement')
    return None


def rest_rig(name, body, garments):
    rig = bpy.data.objects.get(name)
    if rig is None or rig.type != 'ARMATURE':
        raise ValueError('rest_armature must name an armature')
    if sum(obj.type == 'ARMATURE' and obj.data == rig.data for obj in bpy.data.objects) != 1:
        raise ValueError('rest_armature data must not be shared by multiple armatures')
    for obj in (body, *garments):
        if not any(mod.type == 'ARMATURE' and mod.object == rig and mod.show_viewport
                   for mod in obj.modifiers):
            raise ValueError(f'{obj.name!r} must have an active modifier for rest_armature')
    return rig


def support_witness(nearest, face_index, faces, position, origin, scale):
    if (nearest is None or type(face_index) is not int or not 0 <= face_index < len(faces)
            or not all(math.isfinite(value) for value in nearest)):
        raise ValueError('Invalid nearest body triangle hit')
    return {'body_triangle_index': face_index,
            'garment_point_world': position.tolist(),
            'body_point_world': (np.asarray(nearest)*scale+origin).tolist()}


def inspect(p, find_object):
    if bpy.context.mode != 'OBJECT':
        raise ValueError('Inspect clearance in Object Mode')
    body = find_object(p['body'], mesh=True)
    names = p['garments']
    if not isinstance(names, list) or not 1 <= len(names) <= 8 or len(set(names)) != len(names) or body.name in names:
        raise ValueError('Declare 1..8 distinct garments separate from the body')
    garments = [find_object(name, mesh=True) for name in names]
    start, end, threshold = p['start_frame'], p['end_frame'], p['min_clearance_m']
    samples, maximum = p.get('samples', 9), p.get('max_queries', 1000000)
    mode = p.get('surface_samples', 'vertices_and_centres')
    region_attribute = p.get('region_attribute')
    include_patches = p.get('include_violation_patches', False)
    if type(include_patches) is not bool:
        raise ValueError('include_violation_patches must be boolean')
    include_worst_support = p.get('include_worst_support', False)
    if type(include_worst_support) is not bool:
        raise ValueError('include_worst_support must be boolean')
    if (type(start) is not int or type(end) is not int or not 1 <= start < end <= 1000000
            or type(samples) is not int or not 2 <= samples <= 32
            or isinstance(threshold, bool) or not math.isfinite(threshold) or threshold < 0
            or type(maximum) is not int or not 1 <= maximum <= 1000000
            or mode not in ('vertices', 'vertices_and_centres')):
        raise ValueError('Invalid clearance frames, threshold or query budget')
    if region_attribute is not None and (type(region_attribute) is not str or not 1 <= len(region_attribute) <= 63):
        raise ValueError('region_attribute must be a name of 1..63 characters')
    explicit = p.get('sample_frames')
    if explicit is None:
        schedule, covered = bounded_samples(start, end, samples)
    else:
        schedule = validate_sample_frames(explicit, start, end)
        covered = sum(frame == int(frame) for frame in schedule) == end - start + 1
        samples = len(schedule)
    if include_patches and (explicit is None or len(schedule) != 1):
        raise ValueError("include_violation_patches requires exactly one explicit sample frame")
    rest_name = p.get("rest_armature")
    if rest_name is not None and (not isinstance(rest_name, str) or not rest_name or explicit is None or len(schedule) != 1):
        raise ValueError("rest_armature requires exactly one explicit sample frame")
    rig = rest_rig(rest_name, body, garments) if rest_name is not None else None
    scene = bpy.context.scene
    prior = scene.frame_current, scene.frame_subframe
    prior_pose = rig.data.pose_position if rig is not None else None
    from .blender_geometry import unit_scale

    meters = unit_scale()
    reports = [{'name': name, 'min_clearance_m': None, 'worst_frame': None,
                'inside_samples': 0, 'violating_samples': 0, 'ambiguous_samples': 0,
                'samples_checked': 0, 'worst_probe': None, 'violation_examples': []} for name in names]
    if include_worst_support:
        for report in reports:
            report['worst_support'] = None
            report['ambiguity_examples'] = []
    region_reports = [{} for _ in names]
    patch_state = [{'vertices': {}, 'triangles': (), 'evaluated': None, 'processed': 0} for _ in names]
    seen_regions = [set() for _ in names]
    frames, topology, issues, work = [], [], [], 0
    budget, precision = Budget(maximum), 0.
    try:
        for frame in schedule:
            set_frame(frame)
            if rig is not None:
                rig.data.pose_position = "REST"
                bpy.context.view_layer.update()
            depsgraph = bpy.context.evaluated_depsgraph_get()
            body_points, faces = snapshot(body, depsgraph, triangles=True)
            work += len(body_points)
            origin = body_points[0]
            scale = float(np.linalg.norm(np.ptp(body_points, axis=0)))
            if not math.isfinite(scale) or scale <= 0:
                issues.append('body_has_zero_or_invalid_extent')
                break
            body_vectors = vectors((body_points-origin)/scale)
            parts, status, face_owners = components(body_vectors, faces)
            topology.append({'frame': frame, **status})
            frames.append(frame)
            if not parts:
                issues.append('body_requires_closed_nondegenerate_components')
                break
            tree = BVHTree.FromPolygons(body_vectors, faces.tolist(), all_triangles=True)
            precision = max(precision, EPSILON*scale*meters)
            for value, report, buckets, seen, patches in zip(garments, reports, region_reports, seen_regions, patch_state, strict=True):
                if region_attribute is None:
                    positions, triangles = snapshot(value, depsgraph, triangles=mode=='vertices_and_centres' or include_patches)
                    regions = None
                else:
                    positions, triangles, regions = snapshot(value, depsgraph,
                        triangles=mode=='vertices_and_centres' or include_patches, region_attribute=region_attribute)
                    seen.update(regions if mode == 'vertices_and_centres' else regions[:len(positions)])
                    if len(seen) > 64:
                        raise ValueError(f'Garment {value.name!r} exceeds 64 distinct region buckets')
                vertex_count = len(positions)
                if include_patches:
                    patches['triangles'], patches['evaluated'] = triangles, vertex_count
                if mode == 'vertices_and_centres' and len(triangles):
                    positions = np.vstack((positions, positions[triangles].mean(axis=1)))
                work += len(positions)
                if work > 4000000:
                    issues.append('surface_sample_budget_exhausted')
                    raise QueryBudgetReached
                for index, point in enumerate(vectors((positions-origin)/scale)):
                    budget.use()
                    nearest, _, face_index, distance = tree.find_nearest(point)
                    if distance is None or not math.isfinite(distance):
                        raise ValueError('No finite body surface distance')
                    inside, uncertain = False, distance <= EPSILON
                    reasons = set() if include_worst_support and len(report['ambiguity_examples']) < 16 else None
                    if uncertain and reasons is not None:
                        reasons.add('near_surface')
                    if not uncertain:
                        for part in parts:
                            state = inside_component(point, part, budget, reasons)
                            if state is True:
                                inside, uncertain = True, False
                                break
                            uncertain = uncertain or state is None
                    if inside and len(parts) > 1:
                        if nearest is None or type(face_index) is not int or not 0 <= face_index < len(face_owners):
                            raise ValueError('Invalid nearest body triangle hit')
                        nearest_array = np.asarray(nearest)
                        for part_index, part in enumerate(parts):
                            if part_index == face_owners[face_index]:
                                continue
                            budget.use()
                            _, lower, upper = part
                            if np.any(nearest_array < lower-EPSILON) or np.any(nearest_array > upper+EPSILON):
                                continue
                            budget.use()
                            _, _, _, proximity = part[0].find_nearest(nearest)
                            if proximity is None or proximity <= EPSILON or inside_component(nearest, part, budget) is not False:
                                uncertain = True
                                if reasons is not None:
                                    # A confirmed inside classification has resolved any earlier ray ambiguity.
                                    reasons = {'union_boundary_unresolved'}
                                if 'union_boundary_unresolved' not in issues:
                                    issues.append('union_boundary_unresolved')
                                break
                    report['samples_checked'] += 1
                    if include_patches and index < vertex_count:
                        patches['processed'] += 1
                    bucket = None
                    if regions is not None:
                        ids = regions[index]
                        bucket = buckets.get(ids)
                        if bucket is None:
                            bucket = {'region_ids': list(ids), 'samples_checked': 0,
                                'inside_samples': 0, 'violating_samples': 0, 'ambiguous_samples': 0,
                                'min_clearance_m': None, 'worst_frame': None, 'worst_probe': None}
                            if include_worst_support:
                                bucket['worst_support'] = None
                            buckets[ids] = bucket
                        bucket['samples_checked'] += 1
                    if uncertain:
                        report['ambiguous_samples'] += 1
                        if bucket is not None:
                            bucket['ambiguous_samples'] += 1
                        if reasons is not None:
                            example = {'frame': frame,
                                'kind': 'vertex' if index < vertex_count else 'triangle_centre',
                                'index': index if index < vertex_count else index-vertex_count,
                                'unsigned_distance_m': distance*scale*meters, 'causes': sorted(reasons),
                                **support_witness(nearest, face_index, faces, positions[index], origin, scale)}
                            if regions is not None:
                                example['region_ids'] = list(regions[index])
                            report['ambiguity_examples'].append(example)
                        continue
                    gap = distance*scale*meters*(-1 if inside else 1)
                    if include_patches and index < vertex_count and gap < threshold:
                        patches['vertices'][index] = (gap, regions[index] if regions is not None else ())
                    report['inside_samples'] += int(inside)
                    report['violating_samples'] += int(gap < threshold)
                    probe = {'kind': 'vertex' if index < vertex_count else 'triangle_centre',
                             'index': index if index < vertex_count else index-vertex_count}
                    garment_worst = report['min_clearance_m'] is None or gap < report['min_clearance_m']
                    region_worst = bucket is not None and (
                        bucket['min_clearance_m'] is None or gap < bucket['min_clearance_m'])
                    witness = None
                    if include_worst_support and (garment_worst or region_worst):
                        witness = support_witness(nearest, face_index, faces, positions[index], origin, scale)
                    if bucket is not None:
                        bucket['inside_samples'] += int(inside)
                        bucket['violating_samples'] += int(gap < threshold)
                        if region_worst:
                            bucket['min_clearance_m'], bucket['worst_frame'], bucket['worst_probe'] = gap, frame, probe
                            if include_worst_support:
                                bucket['worst_support'] = witness
                    if gap < threshold and len(report['violation_examples']) < 16:
                        report['violation_examples'].append({'frame': frame, **probe, 'clearance_m': gap})
                    if garment_worst:
                        report['min_clearance_m'], report['worst_frame'] = gap, frame
                        report['worst_probe'] = probe
                        if include_worst_support:
                            report['worst_support'] = witness
    except QueryBudgetReached:
        if not issues:
            issues.append('query_budget_exhausted')
    finally:
        if rig is not None:
            rig.data.pose_position = prior_pose
        scene.frame_set(prior[0], subframe=prior[1])
        bpy.context.view_layer.update()
    if region_attribute is not None:
        for report, buckets in zip(reports, region_reports, strict=True):
            report['regions'] = [buckets[key] for key in sorted(buckets)]
    if include_patches:
        from .blender_clearance_patches import summarize
        for report, patches in zip(reports, patch_state, strict=True):
            report['violation_patches'] = summarize(patches['vertices'], patches['triangles'],
                patches['evaluated'], patches['processed'])
    complete = not issues and all(report['ambiguous_samples']==0 for report in reports)
    covered = covered and complete
    return {**({'rest_armature': rest_name} if rest_name is not None else {}),
            'scope': 'sampled_garment_clearance', 'body': body.name, 'garments': reports,
            'complete': complete, 'passed': complete and all(report['violating_samples']==0 for report in reports),
            'frames': frames, 'requested_samples': samples, 'all_frames_tested': covered,
            'surface_samples': mode,
            'minimum_required_m': threshold, 'numerical_resolution_m': precision,
            'body_topology': topology, 'issues': issues, 'queries': budget.used,
            'query_budget': maximum, 'scene_unit_meters': meters,
            'not_checked': [*(() if covered else ('unsampled times',)), 'unsampled surface locations',
                            'continuous triangle collision',
                            'body self-intersections', 'cloth simulation', 'Unity import']}
