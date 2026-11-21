"""Bounded spatial-query validation and sampling, without a native dependency."""
import math
from heapq import heappop, heappush

DEFAULTS = {'proposed_world_delta': None, 'min_clearance_m': 0., 'samples_per_side': 256,
            'max_triangles': 100000, 'max_pair_tests': 1000000, 'max_results': 32}
IDENTITY = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))
FLOAT32_MAX = 3.4028234663852886e38
COPLANAR_TOLERANCE_M = 1e-6
COPLANAR_NORMAL_TOLERANCE = 1e-6


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
    """Distance from a point to a triangle, including its boundary."""
    a, b, c = triangle
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(point, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return _dist(point, a)
    bp = _sub(point, b)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return _dist(point, b)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        return _dist(point, _add(a, _scale(ab, d1 / (d1 - d3))))
    cp = _sub(point, c)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return _dist(point, c)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        return _dist(point, _add(a, _scale(ac, d2 / (d2 - d6))))
    va = d3 * d6 - d5 * d4
    if va <= 0 and d4 - d3 >= 0 and d5 - d6 >= 0:
        return _dist(point, _add(b, _scale(_sub(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6)))))
    denom = va + vb + vc
    if denom == 0:
        return min(_dist(point, a), _dist(point, b), _dist(point, c))
    closest = _add(a, _add(_scale(ab, vb / denom), _scale(ac, vc / denom)))
    return _dist(point, closest)


def segment_distance(p1, q1, p2, q2):
    """Distance between two segments."""
    d1, d2 = _sub(q1, p1), _sub(q2, p2)
    r = _sub(p1, p2)
    a, e, f = _dot(d1, d1), _dot(d2, d2), _dot(d2, r)
    b, c = _dot(d1, d2), _dot(d1, r)
    cross = _cross(d1, d2)
    denom = _dot(cross, cross)
    s = _clamp((b * f - c * e) / denom) if denom > 0 else 0.
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


def _split(triangles, indices):
    box = _group_bounds(triangles, indices)
    axis = max(range(3), key=lambda i: box[1][i] - box[0][i])
    ordered = sorted(indices, key=lambda i: sum(point[axis] for point in triangles[i]))
    middle = max(1, len(ordered) // 2)
    return ordered[:middle], ordered[middle:]


def prove_distance(subjects, context, upper, budget):
    """Branch-and-bound triangle distance.

    ``upper`` is a known distance, such as a sample. A finished search reports
    the exact minimum. An exhausted budget reports a lower bound that must not
    be treated as the minimum.
    """
    if type(budget) is not int or budget < 0:
        raise ValueError('Distance proof budget must be a nonnegative integer')
    if not subjects or not context:
        raise ValueError('Distance proof requires both surfaces')
    if not math.isfinite(upper) or upper < 0:
        raise ValueError('Distance upper bound must be finite and nonnegative')
    best = float(upper)
    work = 0
    counter = 0
    pending = []
    heappush(pending, (_gap(_group_bounds(subjects, range(len(subjects))),
                            _group_bounds(context, range(len(context)))),
                       counter, tuple(range(len(subjects))), tuple(range(len(context)))))
    stopped = None
    while pending:
        gap, _, left, right = heappop(pending)
        if gap >= best:
            continue
        if work >= budget:
            stopped = gap
            break
        work += 1
        if len(left) > 1 or len(right) > 1:
            if len(left) >= len(right) and len(left) > 1:
                parts, other, left_side = _split(subjects, left), right, True
            else:
                parts, other, left_side = _split(context, right), left, False
            for part in parts:
                if not part:
                    continue
                pair = (part, other) if left_side else (other, part)
                counter += 1
                heappush(pending, (_gap(_group_bounds(subjects, pair[0]),
                                        _group_bounds(context, pair[1])),
                                   counter, tuple(pair[0]), tuple(pair[1])))
            continue
        best = min(best, triangle_distance(subjects[left[0]], context[right[0]]))
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
