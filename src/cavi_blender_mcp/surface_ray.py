"""Convert world rays into a source mesh's native coordinate and distance frame."""
import math

import numpy as np


def local_ray(origin, direction, max_distance_m, matrix, unit_m):
    origin, direction, matrix = (np.asarray(v,dtype=np.float64) for v in (origin,direction,matrix))
    if (origin.shape != (3,) or direction.shape != (3,) or matrix.shape != (4,4)
            or not all(np.isfinite(v).all() for v in (origin,direction,matrix))
            or not np.array_equal(matrix[3],[0,0,0,1])
            or type(unit_m) not in (int,float) or not math.isfinite(unit_m) or unit_m <= 0
            or type(max_distance_m) not in (int,float) or not math.isfinite(max_distance_m) or max_distance_m <= 0):
        raise ValueError('Surface ray requires finite vectors, an affine transform and positive metre units/range')
    length = math.hypot(*direction)
    if not 0 < length < math.inf:
        raise ValueError('Surface ray direction must be nonzero and finite')
    try:
        inverse = np.linalg.inv(matrix[:3,:3])
    except np.linalg.LinAlgError as exc:
        raise ValueError('Surface ray requires a nonsingular world transform') from exc
    start = inverse @ (origin-matrix[:3,3])
    vector = inverse @ (direction/length)
    scale = math.hypot(*vector)
    distance = max_distance_m/unit_m*scale
    if (not 0 < scale < math.inf or not 0 < distance <= np.finfo(np.float32).max
            or not np.isfinite(start).all() or np.max(np.abs(start)) > np.finfo(np.float32).max):
        raise ValueError('Surface ray exceeds finite native coordinate/range storage')
    return start.tolist(), (vector/scale).tolist(), float(distance)
