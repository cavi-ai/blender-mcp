"""Unwrap selected UV loops through a private native solver without changing host context."""
import math

import bpy

from .blender_bridge import _workspace, editable_mesh, info, number
from .blender_errors import preflight
from .blender_mesh_regions import mesh_digest
from .mesh_regions import fingerprint, indices
from .uv_regions import quality, region, reservation
from .uv_worker import solve


def geometry(value, faces):
    mesh = value.data
    polygons = [mesh.polygons[i] for i in faces]
    if sum(p.loop_total for p in polygons) > 60000 or len(mesh.vertices) > 200000:
        raise ValueError('Face unwrap is bounded to 60000 selected loops and 200000 source vertices')
    mesh.calc_loop_triangles()
    if len(mesh.loop_triangles) > 200000:
        raise ValueError('Face unwrap is bounded to 200000 source triangles')
    selected = set(faces)
    loops = [i for p in polygons for i in p.loop_indices]
    loop_map = {index: i for i, index in enumerate(loops)}
    vertex_ids = list(dict.fromkeys(v for p in polygons for v in p.vertices))
    vertex_map = {index: i for i, index in enumerate(vertex_ids)}
    matrix = value.matrix_world.to_3x3()
    units = bpy.context.scene.unit_settings
    unit_scale = 1. if units.system == 'NONE' else units.scale_length
    if not math.isfinite(unit_scale) or unit_scale <= 0:
        raise ValueError('Scene unit scale must be positive and finite')
    origin = mesh.vertices[vertex_ids[0]].co
    points = [list((matrix @ (mesh.vertices[i].co-origin))*unit_scale) for i in vertex_ids]
    if any(not math.isfinite(n) or abs(n) > 1e6 for point in points for n in point):
        raise ValueError('Selected world-linear geometry must be finite within +/-1000000 metres')
    triangles = [t for t in mesh.loop_triangles if t.polygon_index in selected]
    if not 1 <= len(triangles) <= 20000:
        raise ValueError('Unwrap 1..20000 selected source triangles')
    return loops, {'vertices': points, 'faces': [[vertex_map[v] for v in p.vertices] for p in polygons],
        'triangles': [[loop_map[i] for i in t.loops] for t in triangles],
        'triangle_vertices': [[vertex_map[i] for i in t.vertices] for t in triangles]}


def unwrap_faces(p):
    with preflight():
        value = editable_mesh(p['name'])
        mesh = value.data
        if bpy.context.mode != 'OBJECT' or value.mode != 'OBJECT' or not mesh.is_editable:
            raise ValueError('UV editing requires editable source mesh data in Object Mode')
        digest = mesh_digest(mesh)
        fingerprint(p.get('expected_mesh_sha256'), digest)
        faces = indices(p.get('face_indices'), len(mesh.polygons))
        spec = region(p.get('uv_region'))
        angle = number(p.get('angle_limit_degrees', 66), 1, 89, 'angle_limit_degrees')
        name = p.get('uv_layer')
        layer = mesh.uv_layers.get(name) if name is not None else (mesh.uv_layers[0] if mesh.uv_layers else None)
        if layer is None:
            raise ValueError('Requested existing UV layer is missing')
        loops, request = geometry(value, faces)
        before = [tuple(row.uv) for row in layer.data]
        if any(not math.isfinite(n) for row in before for n in row):
            raise ValueError('Source UVs must be finite before reserving a region')
        if not spec['allow_pinned'] and any(layer.data[i].pin_uv for i in loops):
            raise ValueError('Selected UVs are pinned; unlock them or set allow_pinned explicitly')
        selected = set(faces)
        reserved = reservation(([before[i] for i in t.loops] for t in mesh.loop_triangles
                                if t.polygon_index not in selected), spec)
        output = solve(bpy.app.binary_path, _workspace, {**request, 'region': spec, 'angle': angle})
        rows = output.get('uv')
        if not isinstance(rows, list) or len(rows) != len(loops):
            raise ValueError('UV worker returned a different loop count')
        rows, measured = quality(rows, request['triangles'], request['triangle_vertices'], spec)
        if not measured['passed']:
            raise ValueError('Native UVs do not satisfy the requested region and pixel padding')
        if (value.data != mesh or mesh_digest(mesh) != digest
                or [tuple(row.uv) for row in layer.data] != before):
            raise ValueError('Source geometry or UVs changed while solving; inspect before trying again')
    try:
        for index, uv in zip(loops, rows, strict=True):
            layer.data[index].uv = uv
        mesh.update()
        actual = [tuple(layer.data[i].uv) for i in loops]
        if any(tuple(expected) != observed for expected, observed in zip(rows, actual, strict=True)):
            raise RuntimeError('Native UV writeback differs from the verified coordinates')
        return {**info(value), 'uv_layer': layer.name, 'face_unwrap': {'faces': faces, 'loops': len(loops),
            'region': spec, 'quality': measured, 'reservation': reserved, 'mesh_sha256': digest,
            'geometry_scope': 'unevaluated_world_linear', 'scale': 'uniform_pixels',
            'scope': 'selected_source_faces', 'worker_version': output.get('blender')}}
    except Exception:
        for index in loops:
            layer.data[index].uv = before[index]
        mesh.update()
        raise
