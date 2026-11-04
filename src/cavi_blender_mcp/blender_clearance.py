"""Sample signed garment clearance against closed evaluated body components."""

import math
from collections import defaultdict

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from .blender_mesh_sample import snapshot
from .blender_motion_compare import set_frame

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
        return [], status
    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index
    for owners in edges.values():
        parents[find(owners[1])] = find(owners[0])
    groups = defaultdict(list)
    for index, triangle in enumerate(faces):
        groups[find(index)].append(tuple(int(v) for v in triangle))
    result = []
    for triangles in groups.values():
        indices = sorted({vertex for triangle in triangles for vertex in triangle})
        mapping = {vertex: index for index, vertex in enumerate(indices)}
        coordinates = [points[index] for index in indices]
        array = np.asarray(coordinates, np.float64)
        tree = BVHTree.FromPolygons(coordinates,
            [tuple(mapping[index] for index in triangle) for triangle in triangles], all_triangles=True)
        result.append((tree, array.min(axis=0), array.max(axis=0)))
    status['components'] = len(result)
    return result, status


def inside_component(point, component, budget):
    budget.use()
    tree, lower, upper = component
    if np.any(np.asarray(point) < lower-EPSILON) or np.any(np.asarray(point) > upper+EPSILON):
        return False
    parities = []
    for direction in DIRECTIONS:
        origin, hits = point.copy(), 0
        while True:
            budget.use()
            hit, _, _, distance = tree.ray_cast(origin, direction, 4.)
            if hit is None:
                break
            if distance <= EPSILON/4:
                return None
            hits += 1
            origin = hit + direction*(2*EPSILON)
        parities.append(hits % 2 == 1)
    return parities[0] if len(set(parities)) == 1 else None


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
    if (type(start) is not int or type(end) is not int or not 1 <= start < end <= 1000000
            or type(samples) is not int or not 2 <= samples <= 32
            or isinstance(threshold, bool) or not math.isfinite(threshold) or threshold < 0
            or type(maximum) is not int or not 1 <= maximum <= 1000000
            or mode not in ('vertices', 'vertices_and_centres')):
        raise ValueError('Invalid clearance frames, threshold or query budget')
    scene = bpy.context.scene
    prior = scene.frame_current, scene.frame_subframe
    meters = scene.unit_settings.scale_length
    if not math.isfinite(meters) or meters <= 0:
        raise ValueError('Scene metre scale must be positive and finite')
    reports = [{'name': name, 'min_clearance_m': None, 'worst_frame': None,
                'inside_samples': 0, 'violating_samples': 0, 'ambiguous_samples': 0,
                'samples_checked': 0, 'worst_probe': None, 'violation_examples': []} for name in names]
    frames, topology, issues, work = [], [], [], 0
    budget, precision = Budget(maximum), 0.
    try:
        for frame in np.linspace(start, end, samples).tolist():
            set_frame(frame)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            body_points, faces = snapshot(body, depsgraph, triangles=True)
            work += len(body_points)
            origin = body_points[0]
            scale = float(np.linalg.norm(np.ptp(body_points, axis=0)))
            if not math.isfinite(scale) or scale <= 0:
                issues.append('body_has_zero_or_invalid_extent')
                break
            body_vectors = vectors((body_points-origin)/scale)
            parts, status = components(body_vectors, faces)
            topology.append({'frame': frame, **status})
            frames.append(frame)
            if not parts:
                issues.append('body_requires_closed_nondegenerate_components')
                break
            tree = BVHTree.FromPolygons(body_vectors, faces.tolist(), all_triangles=True)
            precision = max(precision, EPSILON*scale*meters)
            for value, report in zip(garments, reports, strict=True):
                positions, triangles = snapshot(value, depsgraph, triangles=mode=='vertices_and_centres')
                vertex_count = len(positions)
                if mode == 'vertices_and_centres' and len(triangles):
                    positions = np.vstack((positions, positions[triangles].mean(axis=1)))
                work += len(positions)
                if work > 4000000:
                    issues.append('surface_sample_budget_exhausted')
                    raise QueryBudgetReached
                for index, point in enumerate(vectors((positions-origin)/scale)):
                    budget.use()
                    _, _, _, distance = tree.find_nearest(point)
                    if distance is None or not math.isfinite(distance):
                        raise ValueError('No finite body surface distance')
                    inside, uncertain = False, distance <= EPSILON
                    if not uncertain:
                        for part in parts:
                            state = inside_component(point, part, budget)
                            if state is True:
                                inside, uncertain = True, False
                                break
                            uncertain = uncertain or state is None
                    report['samples_checked'] += 1
                    if uncertain:
                        report['ambiguous_samples'] += 1
                        continue
                    gap = distance*scale*meters*(-1 if inside else 1)
                    report['inside_samples'] += int(inside)
                    report['violating_samples'] += int(gap < threshold)
                    probe = {'kind': 'vertex' if index < vertex_count else 'triangle_centre',
                             'index': index if index < vertex_count else index-vertex_count}
                    if gap < threshold and len(report['violation_examples']) < 16:
                        report['violation_examples'].append({'frame': frame, **probe, 'clearance_m': gap})
                    if report['min_clearance_m'] is None or gap < report['min_clearance_m']:
                        report['min_clearance_m'], report['worst_frame'] = gap, frame
                        report['worst_probe'] = probe
    except QueryBudgetReached:
        if not issues:
            issues.append('query_budget_exhausted')
    finally:
        scene.frame_set(prior[0], subframe=prior[1])
        bpy.context.view_layer.update()
    complete = not issues and all(report['ambiguous_samples']==0 for report in reports)
    return {'scope': 'sampled_garment_clearance', 'body': body.name, 'garments': reports,
            'complete': complete, 'passed': complete and all(report['violating_samples']==0 for report in reports),
            'frames': frames, 'requested_samples': samples, 'surface_samples': mode,
            'minimum_required_m': threshold, 'numerical_resolution_m': precision,
            'body_topology': topology, 'issues': issues, 'queries': budget.used,
            'query_budget': maximum, 'scene_unit_meters': meters,
            'not_checked': ['unsampled times and surface locations', 'continuous triangle collision',
                            'body self-intersections', 'cloth simulation', 'Unity import']}
