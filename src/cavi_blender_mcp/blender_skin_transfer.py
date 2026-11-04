"""Interpolate rest-surface skin weights onto an independent mesh copy."""

import math

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

from .blender_bridge import info, new_name, obj
from .blender_errors import preflight
from .blender_rig import weights
from .blender_rigging import MAX_ASSIGNMENTS, label


def world_vertices(value, origin):
    if not 1 <= len(value.data.vertices) <= 100000:
        raise ValueError('Skin transfer requires 1..100000 base vertices per mesh')
    coordinates = np.empty(len(value.data.vertices) * 3, dtype=np.float64)
    value.data.vertices.foreach_get('co', coordinates)
    matrix = np.asarray(value.matrix_world, dtype=np.float64)
    points = coordinates.reshape(-1, 3) @ matrix[:3, :3].T + (matrix[:3, 3] - origin)
    if not np.isfinite(points).all() or np.linalg.det(matrix[:3, :3]) == 0:
        raise ValueError('Transfer needs finite, invertible rest-object transforms')
    vectors = [Vector(point) for point in points]
    if any(not math.isfinite(coordinate) for point in vectors for coordinate in point):
        raise ValueError('Rest coordinates exceed native geometry precision')
    return vectors


def transfer(p):
    with preflight():
        if bpy.context.mode != 'OBJECT':
            raise ValueError('Transfer weights in Object Mode')
        source, target = obj(p['source'], mesh=True), obj(p['name'], mesh=True)
        name = new_name(p['new_name'])
        shape_names = p.get('shape_names', [])
        if not isinstance(shape_names, list) or len(shape_names) > 64:
            raise ValueError('shape_names must list up to 64 unique source shapes')
        for shape_name in shape_names:
            label(shape_name, 'shape name')
        if len(set(shape_names)) != len(shape_names):
            raise ValueError('shape_names must be unique')
        projection = []
        distance, loss, limit = p['max_distance_m'], p['max_discarded_weight'], p.get('max_influences', 4)
        if (isinstance(distance, bool) or not isinstance(distance, (int, float))
                or not math.isfinite(distance) or distance <= 0
                or isinstance(loss, bool) or not isinstance(loss, (int, float))
                or not math.isfinite(loss) or not 0 <= loss <= 1
                or type(limit) is not int or not 1 <= limit <= 32):
            raise ValueError('Declare a positive metre distance, loss fraction in 0..1 and 1..32 influences')
        modifiers = [m for m in source.modifiers if m.type == 'ARMATURE']
        if (len(modifiers) != 1 or modifiers[0].object is None or not modifiers[0].show_viewport
                or not modifiers[0].use_vertex_groups or modifiers[0].use_bone_envelopes):
            raise ValueError('Source needs one enabled vertex-group armature modifier without envelopes')
        rig = modifiers[0].object
        if rig.type != 'ARMATURE':
            raise ValueError('Source modifier must bind an armature')
        deform = {bone.name for bone in rig.data.bones if bone.use_deform}
        if not deform or len(deform) > 512:
            raise ValueError('Source needs 1..512 deform bones')
        if len(target.data.vertices)*limit > MAX_ASSIGNMENTS:
            raise ValueError('Transfer exceeds one million target weight assignments')
        group_names = {group.index: group.name for group in source.vertex_groups if group.name in deform}
        if sum(item.group in group_names for vertex in source.data.vertices for item in vertex.groups) > MAX_ASSIGNMENTS:
            raise ValueError('Source exceeds one million deform weight assignments')
        source_quality = weights(source, deform, 32)
        if any(source_quality[key] for key in ('unweighted_vertices', 'unnormalized_vertices',
                                             'invalid_vertices')):
            raise ValueError('Source deform weights must be finite, weighted and normalized')
        meters = bpy.context.scene.unit_settings.scale_length
        if not math.isfinite(meters) or meters <= 0:
            raise ValueError('Scene metre scale must be positive and finite')
        origin = np.asarray(source.matrix_world.translation, dtype=np.float64)
        source_points, target_points = world_vertices(source, origin), world_vertices(target, origin)
        source.data.calc_loop_triangles()
        if not 1 <= len(source.data.loop_triangles) <= 200000:
            raise ValueError('Source surface needs 1..200000 triangles')
        triangles = [tuple(triangle.vertices) for triangle in source.data.loop_triangles
                     if (source_points[triangle.vertices[1]] - source_points[triangle.vertices[0]]).cross(
                         source_points[triangle.vertices[2]] - source_points[triangle.vertices[0]]).length_squared > 0]
        if not triangles:
            raise ValueError('Source has no nondegenerate rest-surface triangles')
        tree = BVHTree.FromPolygons(source_points, triangles, all_triangles=True)
        donors = [{group_names[item.group]: item.weight for item in vertex.groups
                   if item.group in group_names and item.weight > 0} for vertex in source.data.vertices]
        projected, maximum_distance, maximum_loss = [], 0., 0.
        outside, excessive = [], []
        basis = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
        for index, point in enumerate(target_points):
            nearest, _, triangle_index, gap = tree.find_nearest(point)
            if nearest is None or not math.isfinite(gap):
                raise ValueError('No finite source surface found for a target vertex')
            gap *= meters
            maximum_distance = max(maximum_distance, gap)
            if gap > distance:
                outside.append(index)
            triangle = triangles[triangle_index]
            factors = barycentric_transform(nearest, *(source_points[i] for i in triangle), *basis)
            if any(not math.isfinite(value) or value < -1e-5 or value > 1+1e-5 for value in factors):
                raise ValueError('Source surface produced invalid barycentric coordinates')
            factors = [min(1., max(0., value)) for value in factors]
            total_factor = sum(factors)
            if shape_names:
                projection.append((triangle, [value/total_factor for value in factors]))
            contributions = {}
            for vertex, factor in zip(triangle, factors, strict=True):
                for bone, weight in donors[vertex].items():
                    contributions[bone] = contributions.get(bone, 0.) + weight * factor / total_factor
            ordered = sorted(((bone, weight) for bone, weight in contributions.items() if weight > 0),
                             key=lambda item: (-item[1], item[0]))
            total = sum(weight for _, weight in ordered)
            kept = ordered[:limit]
            retained = sum(weight for _, weight in kept)
            if not math.isfinite(total) or retained <= 0:
                raise ValueError('Transferred vertex has no finite deform weights')
            discarded = max(0., 1-retained/total)
            maximum_loss = max(maximum_loss, discarded)
            if discarded > loss + 1e-7:
                excessive.append(index)
            projected.append([(bone, weight/retained) for bone, weight in kept])
        if outside or excessive:
            raise ValueError(f'Skin transfer rejected before edits: distance_vertices={len(outside)}, '
                             f'max_distance_m={maximum_distance:.9g}; loss_vertices={len(excessive)}, '
                             f'max_discarded_weight={maximum_loss:.9g}')
        from .blender_morph_transfer import prepare

        morphs = prepare(source, target, shape_names, projection)
    copy, mesh = None, None
    try:
        copy = target.copy()
        mesh = target.data.copy()
        copy.data = mesh
        copy.name = name
        copy.animation_data_clear()
        for constraint in list(copy.constraints):
            copy.constraints.remove(constraint)
        for modifier in list(copy.modifiers):
            if modifier.type == 'ARMATURE':
                copy.modifiers.remove(modifier)
        for group in list(copy.vertex_groups):
            if group.name in deform:
                copy.vertex_groups.remove(group)
        used = sorted({bone for vertex in projected for bone, _ in vertex})
        created = {bone: copy.vertex_groups.new(name=bone) for bone in used}
        for index, assignments in enumerate(projected):
            for bone, weight in assignments:
                created[bone].add([index], weight, 'REPLACE')
        from .blender_morph_transfer import apply

        transferred_shapes = apply(copy, source, morphs, meters)
        world = target.matrix_world.copy()
        copy.parent = source
        copy.parent_type = 'OBJECT'
        copy.parent_bone = ''
        copy.matrix_parent_inverse = source.matrix_world.inverted()
        copy.matrix_basis = Matrix.Identity(4)
        bpy.context.scene.collection.objects.link(copy)
        copy.matrix_world = world
        modifier = copy.modifiers.new('Transferred Skin', 'ARMATURE')
        modifier.object = rig
        modifier.use_deform_preserve_volume = modifiers[0].use_deform_preserve_volume
        bpy.context.view_layer.update()
        quality = weights(copy, deform, limit)
        if any(quality[key] for key in ('unweighted_vertices', 'unnormalized_vertices',
                                       'invalid_vertices', 'over_limit_vertices')):
            raise RuntimeError('Stored transfer weights failed verification')
        return {**info(copy), 'source': source.name, 'target': target.name, 'armature': rig.name,
                'scope': 'rest_base_surface_weight_transfer', 'projection': 'triangle_barycentric',
                'source_vertices': len(source_points), 'source_triangles': len(triangles),
                'degenerate_triangles_ignored': len(source.data.loop_triangles)-len(triangles),
                'max_distance_m': maximum_distance, 'distance_limit_m': distance,
                'max_discarded_weight': maximum_loss, 'discarded_weight_limit': loss,
                'morphs': transferred_shapes, 'weights': quality, 'frame': bpy.context.scene.frame_current,
                'not_checked': ['anatomical correspondence', 'cloth collision', 'animation deformation',
                                'normal/tangent deformation', 'Unity import']}
    except Exception:
        if copy is not None:
            bpy.data.objects.remove(copy, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise
