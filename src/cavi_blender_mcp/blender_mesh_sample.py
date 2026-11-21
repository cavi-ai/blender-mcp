"""Finite evaluated mesh snapshots shared by read-only motion inspections."""

import numpy as np


def snapshot(value, depsgraph, triangles=False, region_attribute=None):
    evaluated = value.evaluated_get(depsgraph)
    try:
        mesh = (evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
                if region_attribute is not None else evaluated.to_mesh())
        if not 1 <= len(mesh.vertices) <= 100000:
            raise ValueError('Sampled meshes need 1..100000 evaluated vertices')
        coordinates = np.empty(len(mesh.vertices)*3, np.float64)
        mesh.vertices.foreach_get('co', coordinates)
        matrix = np.asarray(evaluated.matrix_world, np.float64)
        points = coordinates.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
        if not np.isfinite(points).all():
            raise ValueError('Sampled meshes need finite evaluated vertices')
        faces = None
        if triangles:
            mesh.calc_loop_triangles()
            if len(mesh.loop_triangles) > 200000:
                raise ValueError('Sampled meshes exceed 200000 triangles')
            faces = np.empty(len(mesh.loop_triangles)*3, np.int32)
            mesh.loop_triangles.foreach_get('vertices', faces)
            faces = faces.reshape(-1, 3)
        if region_attribute is None:
            return points, faces
        attribute = mesh.attributes.get(region_attribute)
        if attribute is None or attribute.domain != 'FACE' or attribute.data_type != 'INT':
            raise ValueError(f'Garment {value.name!r} requires FACE INT attribute {region_attribute!r}')
        if len(mesh.loops) > 600000:
            raise ValueError('Region sampling exceeds 600000 polygon corners')
        region_ids = np.empty(len(mesh.polygons), np.int32)
        attribute.data.foreach_get('value', region_ids)
        vertex_regions = [set() for _ in mesh.vertices]
        for polygon in mesh.polygons:
            region = int(region_ids[polygon.index])
            for index in polygon.vertices:
                vertex_regions[index].add(region)
                if len(vertex_regions[index]) > 64:
                    raise ValueError('A garment vertex exceeds 64 incident region IDs')
        buckets = [tuple(sorted(regions)) for regions in vertex_regions]
        if triangles:
            buckets.extend((int(region_ids[triangle.polygon_index]),) for triangle in mesh.loop_triangles)
        return points, faces, buckets
    finally:
        evaluated.to_mesh_clear()
