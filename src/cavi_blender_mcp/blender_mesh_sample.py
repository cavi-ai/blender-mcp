"""Finite evaluated mesh snapshots shared by read-only motion inspections."""

import numpy as np


def snapshot(value, depsgraph, triangles=False):
    evaluated = value.evaluated_get(depsgraph)
    try:
        mesh = evaluated.to_mesh()
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
        return points, faces
    finally:
        evaluated.to_mesh_clear()
