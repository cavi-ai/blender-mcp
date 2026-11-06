"""Inspect and translate source vertices while retaining all shape-key offsets."""
import bpy

from .blender_bridge import editable_mesh, info
from .blender_errors import preflight
from .blender_mesh_regions import mesh_digest, page_source
from .mesh_regions import selection
from .vertex_edit import geodesic_weights, radius_m, translated


def inspect(p):
    value, limit, offset = page_source(p)
    mesh = value.data
    return {'name': value.name, 'type': 'MESH', 'mesh': mesh.name, 'scope': 'source_mesh_vertices',
        'mesh_sha256': mesh_digest(mesh), 'total': len(mesh.vertices), 'offset': offset, 'limit': limit,
        'vertices': [{'index': v.index, 'position_local': list(v.co), 'normal_local': list(v.normal),
                      'selected': v.select} for v in mesh.vertices[offset:offset+limit]]}


def move(p):
    with preflight():
        value = editable_mesh(p['name'])
        mesh, keys = value.data, value.data.shape_keys
        if bpy.context.mode != 'OBJECT' or value.mode != 'OBJECT' or not mesh.is_editable:
            raise ValueError('Vertex editing requires editable source mesh data in Object Mode')
        if keys is not None and (not keys.is_editable or keys.users > 1):
            raise ValueError('Vertex editing requires independent editable shape-key data')
        radius = radius_m(p['amount']) if p.get('amount') is not None else None
        if radius is not None:
            bpy.context.view_layer.update()
        digest = mesh_digest(mesh)
        selected, offset = selection(p.get('vertex_indices'), p.get('offset'), len(mesh.vertices),
            p.get('expected_mesh_sha256'), digest, field='vertex_indices')
        falloff, weights = None, None
        if radius is not None:
            linear = [list(row) for row in value.matrix_world.to_3x3()]
            unit = bpy.context.scene.unit_settings.scale_length
            seeds = selected
            affected = geodesic_weights([tuple(v.co) for v in mesh.vertices],
                (tuple(e.vertices) for e in mesh.edges),seeds,radius,linear=linear,unit_m=unit)
            selected,weights = [i for i,_ in affected],[w for _,w in affected]
            falloff = {'mode':'source_edge_geodesic_smoothstep','radius_m':radius,
                'seed_indices':seeds,'scene_unit_meters':unit,'world_linear':linear,
                'weight_samples':[{'index':i,'weight':w} for i,w in affected[:64]],
                'weights_truncated':len(affected) > 64}
        blocks = list(keys.key_blocks) if keys else []
        if len(selected)*(len(blocks)+1) > 1000000:
            raise ValueError('Vertex edit exceeds 1000000 mesh and shape-key points; use smaller selections')
        layers = [mesh.vertices, *(block.data for block in blocks)]
        if any(len(layer) != len(mesh.vertices) for layer in layers):
            raise ValueError('Shape-key topology does not match the mesh')
        before = [[tuple(layer[i].co) for i in selected] for layer in layers]
        targets = [translated(rows, offset,weights=weights) for rows in before]

    def update():
        mesh.update()
        if keys is not None:
            keys.update_tag()

    try:
        for layer, rows in zip(layers, targets, strict=True):
            for index, point in zip(selected, rows, strict=True):
                layer[index].co = point
        update()
        actual = [[tuple(layer[i].co) for i in selected] for layer in layers]
        if actual != targets:
            raise RuntimeError('Native vertex readback differs from the requested translation')
        references = {block.as_pointer(): i+1 for i,block in enumerate(blocks)}
        delta_error = 0.
        for i,block in enumerate(blocks,1):
            reference = references[(block.relative_key if keys.use_relative else keys.reference_key).as_pointer()]
            for a,b,c,d in zip(actual[i], actual[reference], before[i], before[reference], strict=True):
                delta_error = max(delta_error, *(abs((x-y)-(z-w)) for x,y,z,w in zip(a,b,c,d,strict=True)))
        report = {'vertex_indices': selected, 'offset_local': offset,
            'changed_vertices': sum(a != b for a,b in zip(before[0],actual[0],strict=True)),
            'shape_key_blocks': len(blocks), 'shape_key_policy': 'translate_all_key_points',
            'max_shape_delta_error_local': delta_error,
            'mesh_sha256_before': digest, 'mesh_sha256_after': mesh_digest(mesh)}
        if falloff is not None:
            report['falloff'] = falloff
        return {**info(value), 'vertex_edit':report}
    except Exception:
        for layer, rows in zip(layers, before, strict=True):
            for index, point in zip(selected, rows, strict=True):
                layer[index].co = point
        update()
        raise
