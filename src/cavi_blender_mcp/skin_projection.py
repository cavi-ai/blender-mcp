"""Float64 barycentric coordinates for rest-surface interpolation."""

import numpy as np


def barycentric_factors(point, triangle):
    vertices = np.asarray(triangle, dtype=np.float64)
    point = np.asarray(point, dtype=np.float64)
    if (vertices.shape != (3, 3) or point.shape != (3,)
            or not np.isfinite(vertices).all() or not np.isfinite(point).all()):
        raise ValueError('Source surface produced invalid barycentric coordinates')
    try:
        factors, _, rank, _ = np.linalg.lstsq(
            (vertices[1:] - vertices[0]).T, point - vertices[0], rcond=None)
    except np.linalg.LinAlgError as exc:
        raise ValueError('Source surface produced invalid barycentric coordinates') from exc
    if rank != 2 or not np.isfinite(factors).all():
        raise ValueError('Source surface produced invalid barycentric coordinates')
    return (float(1 - factors.sum()), float(factors[0]), float(factors[1]))
