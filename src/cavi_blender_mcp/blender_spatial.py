"""Read-only evaluated mesh surface intersections and sampled metre clearances."""
import math

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from .blender_bridge import obj
from .blender_errors import preflight
from .blender_scene_geometry import digest
from .spatial_query import (
    COPLANAR_NORMAL_TOLERANCE,
    COPLANAR_TOLERANCE_M,
    bounds,
    chunk_pairs,
    chunks,
    coplanar_overlap,
    intersects,
    require_native,
    samples,
    transformed,
    validate,
)


def native_points(points):
    for point in points:
        require_native(point)
    result = [tuple(Vector(p)) for p in points]
    if any(not all(math.isfinite(v) for v in p) for p in result):
        raise ValueError('World geometry exceeds native BVH numeric precision')
    return result


def snapshot(name, graph, unit, delta, remaining, remaining_vertices):
    value = obj(name, mesh=True)
    if name not in bpy.context.view_layer.objects:
        raise ValueError('Spatial objects must belong to the current view layer')
    evaluated = value.evaluated_get(graph)
    mesh = evaluated.to_mesh(preserve_all_data_layers=False, depsgraph=graph)
    try:
        if len(mesh.vertices) > remaining_vertices or len(mesh.loops) > 1500000:
            raise ValueError('Spatial query exceeds 500000 total vertices or 1500000 mesh loops')
        mesh.calc_loop_triangles()
        count = len(mesh.loop_triangles)
        if not count or count > remaining:
            raise ValueError('Spatial triangle budget exceeded or mesh has no triangles')
        matrix = evaluated.matrix_world
        current = native_points([tuple(c * unit for c in (matrix @ v.co)) for v in mesh.vertices])
        points = native_points(transformed(current, delta)) if delta is not None else current
        indices = [tuple(t.vertices) for t in mesh.loop_triangles]
        triangles = [tuple(points[i] for i in face) for face in indices]
        for a, b, c in triangles:
            cross = (Vector(b) - Vector(a)).cross(Vector(c) - Vector(a))
            if not math.isfinite(cross.length_squared) or cross.length_squared == 0:
                raise ValueError('Spatial queries require nondegenerate evaluated triangles')
        report = {'object': name, 'vertices': len(points), 'triangles': count,
                  'world_bounds_m': bounds(points),
                  'current_world_bounds_m': bounds(current),
                  'matrix_world': [list(row) for row in matrix],
                  'surface_sha256': digest({'points_m': current, 'triangles': indices})}
        metadata = [{'object': name, 'evaluated_triangle': t.index,
                     'evaluated_polygon': t.polygon_index} for t in mesh.loop_triangles]
        return report, triangles, metadata
    finally:
        evaluated.to_mesh_clear()


def tree(triangles):
    points = [p for triangle in triangles for p in triangle]
    faces = [(i, i + 1, i + 2) for i in range(0, len(points), 3)]
    return BVHTree.FromPolygons(points, faces, all_triangles=True, epsilon=0.)


def overlap(subjects, context, subject_meta, context_meta, spec):
    subject_chunks, context_chunks = chunks(subjects), chunks(context)
    subject_boxes = [bounds(triangle) for triangle in subjects]
    context_boxes = [bounds(triangle) for triangle in context]
    count, examples, calls, coplanar_added = 0, [], 0, 0
    for a, b in chunk_pairs(subject_chunks, context_chunks, spec['max_pair_tests']):
        for chunk, triangles in ((a, subjects), (b, context)):
            if 'tree' not in chunk:
                chunk['tree'] = tree([triangles[i] for i in chunk['indices']])
        pairs = set(a['tree'].overlap(b['tree']))
        native_count = len(pairs)
        for left, subject_index in enumerate(a['indices']):
            for right, context_index in enumerate(b['indices']):
                if ((left, right) not in pairs
                        and intersects(subject_boxes[subject_index], context_boxes[context_index])
                        and coplanar_overlap(subjects[subject_index], context[context_index])):
                    pairs.add((left, right))
        coplanar_added += len(pairs) - native_count
        calls += 1
        count += len(pairs)
        for left, right in sorted(pairs):
            if len(examples) == spec['max_results']:
                break
            examples.append({'subject': subject_meta[a['indices'][left]],
                             'context': context_meta[b['indices'][right]]})
    return {'method': 'native_float32_bvh_with_float64_coplanar_sat', 'triangle_pairs': count,
            'coplanar_pairs_added': coplanar_added,
            'coplanar_contact_tolerance_m': COPLANAR_TOLERANCE_M,
            'coplanar_normal_tolerance': COPLANAR_NORMAL_TOLERANCE,
            'examples': examples, 'examples_truncated': count > len(examples),
            'bvh_chunk_pairs_tested': calls}


def nearest(subjects, context, subject_meta, context_meta, spec):
    trees = (tree(subjects), tree(context))
    best, witness = math.inf, None
    below, counts, available = 0, [], []
    for source, source_meta, target_meta, target_tree, reverse in (
            (subjects, subject_meta, context_meta, trees[1], False),
            (context, context_meta, subject_meta, trees[0], True)):
        probes = samples(source, spec['samples_per_side'])
        counts.append(len(probes))
        available.append(len(source) * 4)
        for index, point in probes:
            hit, _, triangle, gap = target_tree.find_nearest(Vector(point))
            if hit is None or not math.isfinite(gap):
                raise ValueError('Native nearest-surface query did not produce a finite witness')
            below += gap < spec['min_clearance_m']
            if gap < best:
                best = gap
                witness = {'subject': target_meta[triangle] if reverse else source_meta[index],
                           'context': source_meta[index] if reverse else target_meta[triangle],
                           'subject_position_m': list(hit) if reverse else list(point),
                           'context_position_m': list(point) if reverse else list(hit)}
    return {'method': 'bidirectional_vertex_and_triangle_centroid_samples',
            'distance_m': best, 'witness': witness, 'min_clearance_m': spec['min_clearance_m'],
            'samples_below_min_clearance': below, 'samples_per_side': counts,
            'available_samples_per_side': available, 'all_sample_points_tested': counts == available,
            'continuous_minimum_proven': False}


def inspect(params):
    with preflight():
        spec = validate(params)
        if bpy.context.mode != 'OBJECT':
            raise ValueError('Inspect spatial placement in Object Mode')
        bpy.context.view_layer.update()
        graph = bpy.context.evaluated_depsgraph_get()
        unit = bpy.context.scene.unit_settings.scale_length
        if not math.isfinite(unit) or unit <= 0:
            raise ValueError('Scene unit scale must be positive and finite')
        parts, geometry, metadata = {}, {}, {}
        remaining = spec['max_triangles']
        remaining_vertices = 500000
        for group in ('subjects', 'context'):
            parts[group], geometry[group], metadata[group] = [], [], []
            delta = spec['proposed_world_delta'] if group == 'subjects' else None
            for name in spec[group]:
                report, triangles, entries = snapshot(name, graph, unit, delta, remaining,
                                                      remaining_vertices)
                remaining -= len(triangles)
                remaining_vertices -= report['vertices']
                parts[group].append(report)
                geometry[group].extend(triangles)
                metadata[group].extend(entries)
        boxes = {key: bounds([p for triangle in rows for p in triangle])
                 for key, rows in geometry.items()}
        identity = {'scope': 'evaluated_named_meshes_current_view_layer',
                    'sha256': digest({key: [(p['object'], p['surface_sha256']) for p in rows]
                                      for key, rows in parts.items()}),
                    'triangles': spec['max_triangles'] - remaining}
        report = {**parts, 'geometry_identity': identity,
                  'query_sha256': digest({'geometry': identity, 'query': spec}),
                  'frame': bpy.context.scene.frame_current,
                  'frame_subframe': bpy.context.scene.frame_subframe, 'scene_unit_meters': unit,
                  'view_layer': bpy.context.view_layer.name,
                  'proposed_world_delta': spec['proposed_world_delta'],
                  'bounds_m': boxes, 'bounds_overlap': intersects(boxes['subjects'], boxes['context']),
                  'intersections': overlap(geometry['subjects'], geometry['context'],
                                           metadata['subjects'], metadata['context'], spec),
                  'nearest': nearest(geometry['subjects'], geometry['context'],
                                     metadata['subjects'], metadata['context'], spec),
                  'not_checked': ['solid_containment', 'continuous_surface_minimum',
                                  'render_only_modifier_differences', 'non_mesh_geometry',
                                  'shader_opacity', 'physics_collision_shapes']}
        return {'scope': 'scene_spatial_inspection', 'spatial': report}
