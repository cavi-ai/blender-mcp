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


def pixel_ray(pixel, image_size, projection, camera_world, kind, near, far):
    """Unproject top-left pixel indices at their centers; return a near-to-far ray."""
    if (len(pixel) != 2 or len(image_size) != 2
            or any(type(s) is not int or s < 1 for s in image_size)
            or any(type(p) not in (int,float) or not math.isfinite(p) or not 0 <= p <= s-1
                   for p,s in zip(pixel,image_size,strict=True))
            or kind not in ('PERSP','ORTHO')
            or any(type(v) not in (int,float) or not math.isfinite(v) for v in (near,far))
            or not 0 < near < far):
        raise ValueError('Camera ray requires an in-image pixel, perspective/orthographic view and valid clips')
    projection,world=(np.asarray(v,dtype=np.float64) for v in (projection,camera_world))
    if (projection.shape != (4,4) or world.shape != (4,4)
            or not np.isfinite(projection).all() or not np.isfinite(world).all()
            or not np.array_equal(world[3],[0,0,0,1])):
        raise ValueError('Camera matrices must be finite 4x4 transforms')
    ndc=np.array([2*(pixel[0]+.5)/image_size[0]-1,1-2*(pixel[1]+.5)/image_size[1],-1,1])
    try:
        point=np.linalg.solve(projection,ndc)
        if np.linalg.det(world[:3,:3]) == 0 or point[3] == 0:
            raise ValueError('Camera matrices must be nonsingular')
    except np.linalg.LinAlgError as exc:
        raise ValueError('Camera matrices must be nonsingular') from exc
    start=point[:3]/point[3]
    if not np.isfinite(start).all() or start[2] >= 0:
        raise ValueError('Camera projection did not produce a finite forward near point')
    if kind == 'PERSP':
        start *= near/-start[2]
        end=start*(far/near)
    else:
        start[2]=-near
        end=np.array([start[0],start[1],-far])
    start_world=world[:3,:3]@start+world[:3,3]
    end_world=world[:3,:3]@end+world[:3,3]
    delta=end_world-start_world
    span=math.hypot(*delta)
    if not np.isfinite(start_world).all() or not 0 < span < math.inf:
        raise ValueError('Camera ray exceeds finite world geometry')
    return start_world.tolist(),(delta/span).tolist(),span
