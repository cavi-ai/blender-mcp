"""Bounded spatial-query validation and sampling; numpy loads only for batched distances."""
import math
from heapq import heappop, heappush

DEFAULTS = {'proposed_world_delta': None, 'min_clearance_m': 0., 'samples_per_side': 256,
            'max_triangles': 100000, 'max_pair_tests': 1000000, 'max_results': 32}
IDENTITY = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))
FLOAT32_MAX = 3.4028234663852886e38
COPLANAR_TOLERANCE_M = 1e-6
COPLANAR_NORMAL_TOLERANCE = 1e-6
PROOF_LEAF_TRIANGLES = 16
PROOF_BATCH_PAIRS = 256


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def require_native(values):
    if any(not finite(v) or abs(v) > FLOAT32_MAX for v in values):
        raise ValueError('Spatial values must be finite and representable as native float32')


def matrix(value):
    if value is None:
        return IDENTITY
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(not isinstance(row, (list, tuple)) or len(row) != 4
                   or not all(finite(v) for v in row) for row in value)):
        raise ValueError('proposed_world_delta requires a finite numeric 4x4 matrix')
    if tuple(value[3]) != (0, 0, 0, 1):
        raise ValueError('proposed_world_delta must be affine')
    for row in value:
        require_native(row)
    a, b, c = (row[:3] for row in value[:3])
    determinant = (a[0] * (b[1]*c[2] - b[2]*c[1]) - a[1] * (b[0]*c[2] - b[2]*c[0])
                   + a[2] * (b[0]*c[1] - b[1]*c[0]))
    if not math.isfinite(determinant) or determinant == 0:
        raise ValueError('proposed_world_delta must have an invertible linear transform')
    return tuple(tuple(float(v) for v in row) for row in value)


def validate(value):
    if not isinstance(value, dict) or set(value) - {'subjects', 'context', *DEFAULTS}:
        raise ValueError('Unknown spatial query fields')
    result = {**DEFAULTS, **value}
    for key, maximum in (('subjects', 32), ('context', 128)):
        names = result.get(key)
        if (not isinstance(names, (list, tuple)) or not 1 <= len(names) <= maximum
                or any(not isinstance(n, str) or not 1 <= len(n.encode('utf-8')) <= 63
                       for n in names) or len(set(names)) != len(names)):
            raise ValueError(f'{key} requires 1–{maximum} unique mesh names')
    if set(result['subjects']) & set(result['context']):
        raise ValueError('subjects and context must be disjoint')
    for key, maximum in (('samples_per_side', 4096), ('max_triangles', 200000),
                         ('max_pair_tests', 2000000), ('max_results', 256)):
        if type(result[key]) is not int or not 1 <= result[key] <= maximum:
            raise ValueError(f'{key} must be an integer from 1 to {maximum}')
    if not finite(result['min_clearance_m']) or result['min_clearance_m'] < 0:
        raise ValueError('min_clearance_m must be finite and nonnegative')
    matrix(result['proposed_world_delta'])
    return result


def transformed(points, delta):
    rows = matrix(delta)
    result = [tuple(sum(row[i]*p[i] for i in range(3)) + row[3] for row in rows[:3])
              for p in points]
    if any(not all(finite(v) for v in p) for p in result):
        raise ValueError('Spatial transform produced nonfinite geometry')
    for point in result:
        require_native(point)
    return result


def bounds(points):
    return [list(map(min, zip(*points, strict=True))), list(map(max, zip(*points, strict=True)))]


def intersects(a, b):
    return all(a[0][i] <= b[1][i] and b[0][i] <= a[1][i] for i in range(3))


def coplanar_overlap(a, b):
    """Float64 projected SAT includes containment and shared-edge/vertex contacts."""
    def normal(triangle):
        p, q, r = triangle
        u, v = (tuple(end[i] - p[i] for i in range(3)) for end in (q, r))
        cross = (u[1]*v[2] - u[2]*v[1], u[2]*v[0] - u[0]*v[2], u[0]*v[1] - u[1]*v[0])
        length = math.hypot(*cross)
        if not 0 < length < math.inf:
            raise ValueError('Coplanar narrowphase requires nondegenerate finite triangles')
        return tuple(c / length for c in cross)

    na, nb = normal(a), normal(b)
    cross = (na[1]*nb[2] - na[2]*nb[1], na[2]*nb[0] - na[0]*nb[2], na[0]*nb[1] - na[1]*nb[0])
    if math.hypot(*cross) > COPLANAR_NORMAL_TOLERANCE:
        return False
    for triangle, origin, direction in ((b, a[0], na), (a, b[0], nb)):
        if any(abs(sum(direction[i] * (p[i] - origin[i]) for i in range(3)))
               > COPLANAR_TOLERANCE_M for p in triangle):
            return False
    drop = max(range(3), key=lambda i: abs(na[i]))
    projected = [tuple(tuple(p[i] for i in range(3) if i != drop) for p in triangle)
                 for triangle in (a, b)]
    for triangle in projected:
        for i, p in enumerate(triangle):
            q = triangle[(i + 1) % 3]
            axis = (p[1] - q[1], q[0] - p[0])
            length = math.hypot(*axis)
            axis = (axis[0] / length, axis[1] / length)
            left, right = ([sum(x*y for x, y in zip(p, axis, strict=True)) for p in points]
                           for points in projected)
            if (max(left) < min(right) - COPLANAR_TOLERANCE_M
                    or max(right) < min(left) - COPLANAR_TOLERANCE_M):
                return False
    return True


def chunks(triangles):
    """Spatial leaves cap each native overlap result at 128 squared pairs."""
    result = []
    pending = [list(range(len(triangles)))]
    while pending:
        indices = pending.pop()
        box = bounds([p for i in indices for p in triangles[i]])
        if len(indices) <= 128:
            result.append({'indices': indices, 'bounds': box})
            continue
        axis = max(range(3), key=lambda i: box[1][i] - box[0][i])
        indices.sort(key=lambda i: sum(p[axis] for p in triangles[i]))
        middle = len(indices) // 2
        pending.extend((indices[middle:], indices[:middle]))
    return result


def chunk_pairs(subjects, context, budget):
    work = 0
    for a in subjects:
        for b in context:
            overlap = intersects(a['bounds'], b['bounds'])
            work += len(a['indices']) * len(b['indices']) if overlap else 1
            if work > budget:
                raise ValueError('Spatial pair budget exceeded; select a smaller context')
            if overlap:
                yield a, b


def _sub(a, b):
    return tuple(a[i] - b[i] for i in range(3))


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0])


def _add(a, b):
    return tuple(a[i] + b[i] for i in range(3))


def _scale(a, factor):
    return tuple(v * factor for v in a)


def _dist(a, b):
    return math.dist(a, b)


def _clamp(value):
    return 0. if value < 0 else 1. if value > 1 else value


def point_triangle_distance(point, triangle):
    """Distance to a triangle using a plane projection and edge tests."""
    a, b, c = triangle
    normal = _cross(_sub(b, a), _sub(c, a))
    length = math.hypot(*normal)
    if length:
        normal = _scale(normal, 1 / length)
        height = _dot(_sub(point, a), normal)
        projected = _sub(point, _scale(normal, height))
        if all(_dot(_cross(_sub(triangle[(i + 1) % 3], triangle[i]),
                           _sub(projected, triangle[i])), normal) >= 0 for i in range(3)):
            return abs(height)
    distances = []
    for i in range(3):
        start, end = triangle[i], triangle[(i + 1) % 3]
        edge = _sub(end, start)
        size = _dot(edge, edge)
        t = _clamp(_dot(_sub(point, start), edge) / size) if size else 0.
        distances.append(_dist(point, _add(start, _scale(edge, t))))
    return min(distances)


def segment_distance(p1, q1, p2, q2):
    """Distance between two segments."""
    d1, d2 = _sub(q1, p1), _sub(q2, p2)
    r = _sub(p1, p2)
    a, e, f = _dot(d1, d1), _dot(d2, d2), _dot(d2, r)
    b, c = _dot(d1, d2), _dot(d1, r)
    cross = _cross(d1, d2)
    denom = _dot(cross, cross)
    s = _clamp(_dot(_cross(d2, r), cross) / denom) if denom > 0 else 0.
    if e == 0:
        t = 0.
        s = _clamp(-c / a) if a > 0 else 0.
    else:
        t = (b * s + f) / e
        if t < 0:
            t = 0.
            s = _clamp(-c / a) if a > 0 else 0.
        elif t > 1:
            t = 1.
            s = _clamp((b - c) / a) if a > 0 else 0.
    return _dist(_add(p1, _scale(d1, s)), _add(p2, _scale(d2, t)))


def _segment_intersects_triangle(p, q, triangle):
    a, b, c = triangle
    direction, edge1, edge2 = _sub(q, p), _sub(b, a), _sub(c, a)
    h = _cross(direction, edge2)
    det = _dot(edge1, h)
    if det == 0:
        return False
    offset = _sub(p, a)
    u = _dot(offset, h) / det
    cross = _cross(offset, edge1)
    v = _dot(direction, cross) / det
    t = _dot(edge2, cross) / det
    return 0 <= u <= 1 and 0 <= v and u + v <= 1 and 0 <= t <= 1


def triangle_distance(a, b):
    """Exact distance between two triangles. Intersection and contact are zero."""
    if any(_segment_intersects_triangle(tri[i], tri[(i + 1) % 3], other)
           for tri, other in ((a, b), (b, a)) for i in range(3)):
        return 0.
    best = min(point_triangle_distance(point, b) for point in a)
    best = min(best, min(point_triangle_distance(point, a) for point in b))
    for i in range(3):
        for j in range(3):
            best = min(best, segment_distance(a[i], a[(i + 1) % 3], b[j], b[(j + 1) % 3]))
    return best


# Batched float64 twins of the scalar functions above. Each repeats the scalar operation
# order and branches; only the final Euclidean norms may differ by a few ulp.
def _numpy():
    import numpy

    return numpy


_NEXT = [1, 2, 0]


def _vdot(a, b):
    return a[..., 0] * b[..., 0] + a[..., 1] * b[..., 1] + a[..., 2] * b[..., 2]


def _vcross(np, a, b):
    return np.stack((a[..., 1]*b[..., 2] - a[..., 2]*b[..., 1],
                     a[..., 2]*b[..., 0] - a[..., 0]*b[..., 2],
                     a[..., 0]*b[..., 1] - a[..., 1]*b[..., 0]), axis=-1)


def _vclamp(np, value):
    return np.where(value < 0, 0., np.where(value > 1, 1., value))


def _vdist(np, a, b):
    delta = a - b
    return np.hypot(np.hypot(delta[..., 0], delta[..., 1]), delta[..., 2])


def _unit_normals(np, triangles):
    """Unit normals scaled by ``1 / math.hypot`` as point_triangle_distance does."""
    cross = _vcross(np, triangles[..., 1, :] - triangles[..., 0, :],
                    triangles[..., 2, :] - triangles[..., 0, :])
    flat = cross.reshape(-1, 3).T.tolist()
    length = np.array(list(map(math.hypot, *flat)), dtype=np.float64).reshape(cross.shape[:-1])
    valid = length != 0
    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        scale = np.where(valid, 1 / np.where(valid, length, 1.), 0.)
        return cross * scale[..., None], valid


def _point_triangle(np, points, triangles, normals, valid):
    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        height = _vdot(points - triangles[..., 0, :], normals)
        projected = points - normals * height[..., None]
        inside, best = valid, None
        for i in range(3):
            start, end = triangles[..., i, :], triangles[..., _NEXT[i], :]
            inside = inside & (_vdot(_vcross(np, end - start, projected - start), normals) >= 0)
            edge = end - start
            size = _vdot(edge, edge)
            t = np.where(size != 0, _vclamp(np, _vdot(points - start, edge) / size), 0.)
            gap = _vdist(np, points, start + edge * t[..., None])
            best = gap if best is None else np.minimum(best, gap)
        return np.where(inside, np.abs(height), best)


def _segment_distances(np, p1, q1, p2, q2):
    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        d1, d2 = q1 - p1, q2 - p2
        r = p1 - p2
        a, e, f = _vdot(d1, d1), _vdot(d2, d2), _vdot(d2, r)
        b, c = _vdot(d1, d2), _vdot(d1, r)
        cross = _vcross(np, d1, d2)
        denom = _vdot(cross, cross)
        s = np.where(denom > 0, _vclamp(np, _vdot(_vcross(np, d2, r), cross) / denom), 0.)
        low_s = np.where(a > 0, _vclamp(np, -c / a), 0.)
        high_s = np.where(a > 0, _vclamp(np, (b - c) / a), 0.)
        t = (b * s + f) / e
        low = (e == 0) | (t < 0)
        high = (e != 0) & (t > 1)
        s = np.where(low, low_s, np.where(high, high_s, s))
        t = np.where(low, 0., np.where(high, 1., t))
        return _vdist(np, p1 + d1 * s[..., None], p2 + d2 * t[..., None])


def _segment_hits(np, p, q, triangles):
    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        a = triangles[..., 0, :]
        direction, edge1, edge2 = q - p, triangles[..., 1, :] - a, triangles[..., 2, :] - a
        h = _vcross(np, direction, edge2)
        det = _vdot(edge1, h)
        offset = p - a
        u = _vdot(offset, h) / det
        cross = _vcross(np, offset, edge1)
        v = _vdot(direction, cross) / det
        t = _vdot(edge2, cross) / det
        return ((det != 0) & (0 <= u) & (u <= 1) & (0 <= v) & (u + v <= 1)
                & (0 <= t) & (t <= 1))


def _triangle_pairs(np, a, b, normals_a, valid_a, normals_b, valid_b):
    starts = np.stack((a, b), axis=1)
    ends = starts[:, :, _NEXT]
    others = np.stack((b, a), axis=1)[:, :, None]
    hits = _segment_hits(np, starts, ends, others).any(axis=(1, 2))
    normals = np.stack((normals_b, normals_a), axis=1)[:, :, None]
    valid = np.stack((valid_b, valid_a), axis=1)[:, :, None]
    points = _point_triangle(np, starts, others, normals, valid).reshape(len(a), 6)
    segments = _segment_distances(np, a[:, :, None], a[:, _NEXT, None],
                                  b[:, None, :], b[:, None, _NEXT]).reshape(len(a), 9)
    return np.where(hits, 0., np.minimum(points.min(axis=1, initial=math.inf),
                                         segments.min(axis=1, initial=math.inf)))


def _triangle_array(np, values):
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        array = array.reshape(0, 3, 3)
    if array.ndim != 3 or array.shape[1:] != (3, 3):
        raise ValueError('Batched distances require (n, 3, 3) triangle arrays')
    return array


def point_triangle_distances(points, triangles):
    """``point_triangle_distance`` over matching (n, 3) points and (n, 3, 3) triangles."""
    np = _numpy()
    triangles = _triangle_array(np, triangles)
    points = np.asarray(points, dtype=np.float64)
    if points.size == 0:
        points = points.reshape(0, 3)
    if points.shape != (len(triangles), 3):
        raise ValueError('Batched distances require one (x, y, z) point per triangle')
    return _point_triangle(np, points, triangles, *_unit_normals(np, triangles))


def triangle_distances(a, b):
    """``triangle_distance`` over matching (n, 3, 3) triangle arrays."""
    np = _numpy()
    a, b = _triangle_array(np, a), _triangle_array(np, b)
    if a.shape != b.shape:
        raise ValueError('Batched distances require the same number of triangles per side')
    return _triangle_pairs(np, a, b, *_unit_normals(np, a), *_unit_normals(np, b))


def _group_bounds(triangles, indices):
    return bounds([point for index in indices for point in triangles[index]])


def _gap(a, b):
    total = 0.
    for i in range(3):
        if a[1][i] < b[0][i]:
            delta = b[0][i] - a[1][i]
        elif b[1][i] < a[0][i]:
            delta = a[0][i] - b[1][i]
        else:
            delta = 0.
        total += delta * delta
    return math.sqrt(total)


def _box_gaps(np, low_a, high_a, low_b, high_b):
    """Batched ``_gap`` with the same per-axis branches and summation order."""
    total = 0.
    for i in range(3):
        delta = np.where(high_a[..., i] < low_b[..., i], low_b[..., i] - high_a[..., i],
                         np.where(high_b[..., i] < low_a[..., i], low_a[..., i] - high_b[..., i],
                                  0.))
        total = total + delta * delta
    return np.sqrt(total)


class _Surface:
    def __init__(self, np, triangles):
        self.np = np
        self.vertices = _triangle_array(np, triangles)
        self.lows, self.highs = self.vertices.min(axis=1), self.vertices.max(axis=1)
        self.keys = self.vertices[:, 0] + self.vertices[:, 1] + self.vertices[:, 2]
        self.normals, self.valid = _unit_normals(np, self.vertices)


class _Node:
    __slots__ = ('box', 'children', 'high', 'indices', 'low', 'surface')

    def __init__(self, surface, indices):
        self.surface, self.indices = surface, indices
        self.low = surface.lows[indices].min(axis=0)
        self.high = surface.highs[indices].max(axis=0)
        self.box = [self.low.tolist(), self.high.tolist()]
        self.children = None

    def split(self):
        if self.children is None:
            axis = max(range(3), key=lambda i: self.box[1][i] - self.box[0][i])
            keys = self.surface.keys[self.indices, axis]
            ordered = self.indices[self.surface.np.argsort(keys, kind='stable')]
            middle = len(ordered) // 2
            self.children = (_Node(self.surface, ordered[:middle]),
                             _Node(self.surface, ordered[middle:]))
        return self.children


def _leaf_work(left, right):
    """Most budget units one leaf pair can spend in ``_near_pairs``."""
    k, m = len(left.indices), len(right.indices)
    return k * m if k == 1 or m == 1 else k + m + k * m


def _near_pairs(np, left, right, best):
    """Triangle pairs whose boxes are closer than ``best``, and the budget units spent."""
    a, b = left.surface, right.surface
    rows, cols = left.indices, right.indices
    work = 0
    if len(rows) > 1 and len(cols) > 1:
        work = len(rows) + len(cols)
        rows = rows[_box_gaps(np, a.lows[rows], a.highs[rows], right.low, right.high) < best]
        cols = cols[_box_gaps(np, left.low, left.high, b.lows[cols], b.highs[cols]) < best]
    near = _box_gaps(np, a.lows[rows][:, None], a.highs[rows][:, None],
                     b.lows[cols][None], b.highs[cols][None]) < best
    i, j = np.nonzero(near)
    return rows[i], cols[j], work + len(i)


def prove_distance(subjects, context, upper, budget):
    """Branch-and-bound triangle distance.

    ``upper`` is a known distance, such as a sample. A finished search reports
    the exact minimum. An exhausted budget reports a lower bound that must not
    be treated as the minimum.

    Budget units: one per node-pair split and one per exact triangle-pair distance.
    A leaf pair of at most ``PROOF_LEAF_TRIANGLES`` triangles a side, both sides
    with two or more, also costs one per triangle box tested against the other
    leaf's box. ``tests`` reports the units spent and never exceeds ``budget``.
    """
    if type(budget) is not int or budget < 0:
        raise ValueError('Distance proof budget must be a nonnegative integer')
    if not subjects or not context:
        raise ValueError('Distance proof requires both surfaces')
    if not math.isfinite(upper) or upper < 0:
        raise ValueError('Distance upper bound must be finite and nonnegative')
    np = _numpy()
    a, b = _Surface(np, subjects), _Surface(np, context)
    best, work, counter = float(upper), 0, 0
    queued, queued_pairs = [], 0

    def flush(best):
        nonlocal queued_pairs
        i = np.concatenate([rows for rows, _ in queued])
        j = np.concatenate([cols for _, cols in queued])
        queued.clear()
        queued_pairs = 0
        if not len(i):
            return best
        distances = _triangle_pairs(np, a.vertices[i], b.vertices[j], a.normals[i], a.valid[i],
                                    b.normals[j], b.valid[j])
        return min(best, float(np.fmin.reduce(distances)))

    left, right = _Node(a, np.arange(len(a.vertices))), _Node(b, np.arange(len(b.vertices)))
    pending = [(_gap(left.box, right.box), len(left.indices) * len(right.indices), counter, left, right)]
    stopped = None
    while pending:
        gap, _, _, left, right = heappop(pending)
        if gap >= best:
            continue
        if work >= budget:
            if queued:
                best = flush(best)
                if gap >= best:
                    continue
            stopped = gap
            break
        leaf = max(len(left.indices), len(right.indices)) <= PROOF_LEAF_TRIANGLES
        if leaf and _leaf_work(left, right) <= budget - work:
            rows, cols, spent = _near_pairs(np, left, right, best)
            work += spent
            if len(rows):
                queued.append((rows, cols))
                queued_pairs += len(rows)
            if queued_pairs >= PROOF_BATCH_PAIRS:
                best = flush(best)
            continue
        work += 1
        split_left = len(left.indices) >= len(right.indices) and len(left.indices) > 1
        for child in (left if split_left else right).split():
            l, r = (child, right) if split_left else (left, child)
            counter += 1
            heappush(pending, (_gap(l.box, r.box), len(l.indices) * len(r.indices), counter, l, r))
    if queued:
        best = flush(best)
    if stopped is None:
        return {'proven': True, 'lower_m': best, 'upper_m': best, 'tests': work}
    lower = min(stopped, pending[0][0]) if pending else stopped
    return {'proven': False, 'lower_m': lower, 'upper_m': best, 'tests': work}


def samples(triangles, maximum):
    total = len(triangles) * 4
    result = []
    for i in range(min(total, maximum)):
        index = i * total // min(total, maximum)
        triangle, corner = divmod(index, 4)
        points = triangles[triangle]
        point = points[corner] if corner < 3 else tuple(sum(p[a] for p in points)/3 for a in range(3))
        result.append((triangle, point))
    return result
