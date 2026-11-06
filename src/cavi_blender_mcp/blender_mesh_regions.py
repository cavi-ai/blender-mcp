"""Source-face inspection and detached BMesh region extrusion."""
import hashlib
import math
import struct
import sys
from array import array

import bmesh
import bpy
from mathutils import Vector

from .blender_bridge import info, obj
from .blender_errors import preflight
from .blender_geometry import MAX_TRIANGLES, source, swap
from .mesh_regions import selection


def mesh_digest(mesh):
    digest = hashlib.sha256(b'cavi-source-faces-v1\0')
    for items, attribute, width, kind in ((mesh.vertices, 'co', 3, 'f'),
            (mesh.edges, 'vertices', 2, 'i'), (mesh.polygons, 'loop_total', 1, 'i'),
            (mesh.loops, 'vertex_index', 1, 'i'), (mesh.polygons, 'material_index', 1, 'i')):
        values = array(kind, [0]) * (len(items) * width)
        items.foreach_get(attribute, values)
        if kind == 'f' and any(not math.isfinite(v) for v in values):
            raise ValueError('Source mesh positions must be finite')
        if sys.byteorder != 'little':
            values.byteswap()
        digest.update(struct.pack('<Q', len(items)))
        digest.update(values.tobytes())
    return digest.hexdigest()


def page_source(p):
    value = obj(p.get('name'), mesh=True)
    mesh = value.data
    limit, offset = p.get('limit', 200), p.get('offset', 0)
    if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
        raise ValueError('Mesh pagination requires limit 1..1000 and a nonnegative offset')
    if bpy.context.mode != 'OBJECT':
        raise ValueError('Inspect source topology in Object Mode')
    if len(mesh.vertices) > MAX_TRIANGLES or sum(max(0, len(f.vertices)-2) for f in mesh.polygons) > MAX_TRIANGLES:
        raise ValueError(f'Inspect at most {MAX_TRIANGLES} vertices and source triangles')
    if len(mesh.edges) > 3*MAX_TRIANGLES:
        raise ValueError(f'Inspect at most {3*MAX_TRIANGLES} source edges')
    return value, limit, offset


def inspect_faces(p):
    value, limit, offset = page_source(p)
    mesh = value.data
    page = mesh.polygons[offset:offset+limit]
    result = {'name': value.name, 'type': 'MESH', 'mesh': mesh.name, 'scope': 'source_mesh_faces',
            'mesh_sha256': mesh_digest(mesh), 'total': len(mesh.polygons), 'offset': offset, 'limit': limit,
            'faces': [{'index': f.index, 'center_local': list(f.center), 'normal_local': list(f.normal),
                       'area_local': f.area, 'vertices': list(f.vertices), 'material_index': f.material_index,
                       'smooth': f.use_smooth} for f in page]}
    if p.get('uv_layer') is not None:
        from .blender_uv_charts import face_page

        result['uv'], rows = face_page(mesh, p['uv_layer'], page)
        for face in result['faces']:
            face['uv'] = rows[face['index']]
    return result


def region_boundaries(faces):
    remaining = set(faces)
    while remaining:
        component, pending = set(), [remaining.pop()]
        while pending:
            face = pending.pop()
            component.add(face)
            for edge in face.edges:
                if len(edge.link_faces) > 2:
                    raise ValueError('Selected faces touch a non-manifold edge')
                for neighbor in set(edge.link_faces) & remaining:
                    remaining.remove(neighbor)
                    pending.append(neighbor)
        if not any(sum(f in component for f in e.link_faces) == 1 for f in component for e in f.edges):
            raise ValueError('Each selected face region needs a boundary; use transform for a closed shell')


def extrude_faces(p):
    bm, candidate = None, None
    try:
        with preflight():
            value, before_triangles = source(p.get('name'))
            original = value.data
            if len(original.vertices) > MAX_TRIANGLES:
                raise ValueError(f'Extrude at most {MAX_TRIANGLES} source vertices')
            if original.has_custom_normals:
                raise ValueError('Clear custom split normals on a working copy before changing its topology')
            before_hash = mesh_digest(original)
            indices, offset = selection(p.get('face_indices'), p.get('offset'), len(original.polygons),
                                        p.get('expected_mesh_sha256'), before_hash)
            bm = bmesh.new()
            bm.from_mesh(original)
            bm.faces.ensure_lookup_table()
            faces = [bm.faces[i] for i in indices]
            region_boundaries(faces)
            previous_faces = set(bm.faces)
            previous_vertices = len(bm.verts)
            edges = {e for f in faces for e in f.edges}
            geometry = bmesh.ops.extrude_face_region(bm, geom=[*faces, *edges], use_keep_orig=False)['geom']
            vertices = {e for e in geometry if isinstance(e, bmesh.types.BMVert)}
            if not vertices:
                raise ValueError('The selected region produced no extruded vertices')
            bmesh.ops.translate(bm, verts=list(vertices), vec=Vector(offset))
            bm.normal_update()
            added = set(bm.faces) - previous_faces
            if any(f.calc_area() <= 1e-14 for f in added):
                raise ValueError('Extrusion would create degenerate faces; choose a different offset')
            if any(len(e.link_faces) > 2 for f in added for e in f.edges):
                raise ValueError('Extrusion would create non-manifold edges')
            after_triangles = sum(len(f.verts)-2 for f in bm.faces)
            if after_triangles > MAX_TRIANGLES or len(bm.verts) > MAX_TRIANGLES:
                raise ValueError(f'Extruded mesh exceeds {MAX_TRIANGLES} vertices or triangles')
            bm.faces.index_update()
            caps = sorted(f.index for f in added if all(v in vertices for v in f.verts))
            cap_set = set(caps)
            sides = sorted(f.index for f in added if f.index not in cap_set)
            summary = {'source_faces': sorted(indices), 'cap_faces': caps, 'side_faces': sides,
                       'offset_local': offset, 'vertices_added': len(bm.verts)-previous_vertices,
                       'triangles_before': before_triangles, 'triangles_after': after_triangles,
                       'mesh_sha256_before': before_hash,
                       'uv_status': 'new_side_faces_require_layout' if original.uv_layers else 'no_uv_layers'}
        # Only a fully validated detached mesh reaches application data.
        candidate = original.copy()
        bm.to_mesh(candidate)
        if original.uv_layers:
            candidate.uv_layers.active_index = original.uv_layers.active_index
            for layer in original.uv_layers:
                candidate.uv_layers[layer.name].active_render = layer.active_render
        candidate.update()
        if value.data != original or mesh_digest(original) != before_hash:
            raise RuntimeError('Source mesh changed before commit; inspect the object')
        summary['mesh_sha256_after'] = mesh_digest(candidate)
        swap(value, candidate)
        candidate = None
        bpy.context.view_layer.update()
        return {**info(value), 'extrusion': summary}
    finally:
        if bm is not None:
            bm.free()
        if candidate is not None and candidate.users == 0:
            bpy.data.meshes.remove(candidate)
