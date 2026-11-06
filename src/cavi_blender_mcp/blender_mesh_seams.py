"""Read source edges and edit only explicitly selected native seam flags."""
import hashlib

import bpy

from .blender_bridge import editable_mesh, info
from .blender_errors import preflight
from .blender_mesh_regions import mesh_digest, page_source
from .mesh_regions import fingerprint, indices


def seam_digest(mesh):
    return hashlib.sha256(bytes(edge.use_seam for edge in mesh.edges)).hexdigest()


def inspect_edges(p):
    value, limit, offset = page_source(p)
    mesh = value.data
    edges = mesh.edges[offset:offset+limit]
    links = {edge.index: [] for edge in edges}
    counts = dict.fromkeys(links, 0)
    for face in mesh.polygons:
        for index in {mesh.loops[i].edge_index for i in face.loop_indices} & links.keys():
            counts[index] += 1
            if len(links[index]) < 32:
                links[index].append(face.index)
    rows = []
    for edge in edges:
        a, b = (mesh.vertices[i].co for i in edge.vertices)
        rows.append({'index': edge.index, 'vertices': list(edge.vertices),
            'endpoints_local': [list(a), list(b)], 'center_local': list((a+b)*.5),
            'length_local': (b-a).length, 'seam': edge.use_seam,
            'faces': links[edge.index], 'face_count': counts[edge.index],
            'faces_truncated': counts[edge.index] > len(links[edge.index])})
    return {'name': value.name, 'type': 'MESH', 'mesh': mesh.name, 'scope': 'source_mesh_edges',
        'mesh_sha256': mesh_digest(mesh), 'seams_sha256': seam_digest(mesh),
        'total': len(mesh.edges), 'offset': offset, 'limit': limit, 'edges': rows}


def set_seams(p):
    with preflight():
        value = editable_mesh(p['name'])
        mesh = value.data
        if bpy.context.mode != 'OBJECT' or value.mode != 'OBJECT' or not mesh.is_editable:
            raise ValueError('Seam editing requires editable source mesh data in Object Mode')
        digest = mesh_digest(mesh)
        fingerprint(p.get('expected_mesh_sha256'), digest)
        selected = indices(p.get('edge_indices'), len(mesh.edges), 'edge_indices')
        enabled = p.get('seam')
        if type(enabled) is not bool:
            raise ValueError('seam must be an explicit boolean')
        previous = [mesh.edges[i].use_seam for i in selected]
        before = seam_digest(mesh)
    try:
        for index in selected:
            mesh.edges[index].use_seam = enabled
        mesh.update()
        if any(mesh.edges[index].use_seam != enabled for index in selected):
            raise RuntimeError('Native seam writeback differs from the requested state')
        return {**info(value), 'seam_edit': {'edge_indices': selected, 'seam': enabled,
            'changed': sum(v != enabled for v in previous), 'mesh_sha256': digest,
            'seams_sha256_before': before, 'seams_sha256_after': seam_digest(mesh)}}
    except Exception:
        for index, old in zip(selected, previous, strict=True):
            mesh.edges[index].use_seam = old
        mesh.update()
        raise
