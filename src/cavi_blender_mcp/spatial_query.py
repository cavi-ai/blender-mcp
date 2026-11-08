"""Bounded spatial-query validation and sampling, without a native dependency."""
import math

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
