"""Bounded indexed geometry validation shared by native and transport tests."""

import math


def validate_mesh(vertices, faces):
    if not isinstance(vertices, (list, tuple)) or not 3 <= len(vertices) <= 10000:
        raise ValueError("Provide between 3 and 10000 vertices")
    if not isinstance(faces, (list, tuple)) or not 1 <= len(faces) <= 20000:
        raise ValueError("Provide between 1 and 20000 faces")
    for vertex in vertices:
        if not isinstance(vertex, (list, tuple)) or len(vertex) != 3:
            raise ValueError("Each vertex needs three coordinates")
        if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e6 for v in vertex):
            raise ValueError("Coordinates must be bounded finite numbers")
    indices = 0
    for face in faces:
        if not isinstance(face, (list, tuple)) or not 3 <= len(face) <= 64:
            raise ValueError("Each face needs between 3 and 64 indices")
        if any(type(i) is not int or not 0 <= i < len(vertices) for i in face):
            raise ValueError("Face indices must be integers referring to supplied vertices")
        if len(set(face)) != len(face):
            raise ValueError("A face cannot repeat a vertex")
        indices += len(face)
        if indices > 100000:
            raise ValueError("Mesh exceeds 100000 face indices")
        # Newell's area handles n-gons without assuming the first three points form a triangle.
        points = [vertices[i] for i in face]
        normal = [0.0, 0.0, 0.0]
        for a, b in zip(points, points[1:] + points[:1]):
            for axis in range(3):
                j, k = (axis + 1) % 3, (axis + 2) % 3
                normal[axis] += (a[j] - b[j]) * (a[k] + b[k])
        if sum(v * v for v in normal) <= 1e-24:
            raise ValueError("Face has zero area")
    return vertices, faces
