"""Bounded analytic UV intersections and chart clearance; no application dependency."""
import math
from bisect import bisect_right
from heapq import heappop, heappush

import numpy as np

MAX_TRIANGLES = 20000
MAX_COMPARISONS = 1000000
COMPARISONS_PER_TRIANGLE = MAX_COMPARISONS // MAX_TRIANGLES
AREA_EPSILON = 1e-8  # Pixel squared, also the degenerate-area threshold.
DISTANCE_EPSILON = 1e-6  # Pixels; only used for the requested padding comparison.
EXAMPLES = 32


def default_budget(triangles):
    """Candidate comparisons grow with the inspected triangles, up to the analysis maximum."""
    return max(1, min(MAX_COMPARISONS, COMPARISONS_PER_TRIANGLE * triangles))


def _cross(a, b):
    return float(a[0] * b[1] - a[1] * b[0])


def _area(poly):
    if len(poly) < 3:
        return 0.
    return abs(sum(_cross(poly[i] - poly[0], poly[i + 1] - poly[0])
                   for i in range(1, len(poly) - 1))) / 2


def triangle_intersection_area(a, b):
    """Sutherland-Hodgman clipping of two triangles, independent of winding."""
    poly = list(a)
    sign = 1 if _cross(b[1] - b[0], b[2] - b[0]) > 0 else -1
    for i in range(3):
        if not poly:
            break
        p, q = b[i], b[(i + 1) % 3]
        output = []
        start = poly[-1]
        ds = sign * _cross(q - p, start - p)
        for end in poly:
            de = sign * _cross(q - p, end - p)
            if (ds >= 0) != (de >= 0):
                output.append(start + (end - start) * (ds / (ds - de)))
            if de >= 0:
                output.append(end)
            start, ds = end, de
        poly = output
    return _area(poly)


def _distance(a, b):
    """Distance of disjoint triangles; overlapping interiors are handled by clipping."""
    best = math.inf
    for points, edges in ((a, b), (b, a)):
        for p in points:
            for i in range(3):
                v, w = edges[i], edges[(i + 1) % 3]
                edge = w - v
                length2 = float(edge @ edge)
                t = float((p - v) @ edge) / length2 if length2 else 0
                delta = p - (v + min(1., max(0., t)) * edge)
                best = min(best, float(delta @ delta))
    return math.sqrt(best)


def _charts(triangles, vertices, valid):
    """Join only shared source edges whose two loop UVs agree exactly."""
    parent = list(range(len(triangles)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    edges = {}
    for i in valid:
        corners = [(int(vertex), float(uv[0]), float(uv[1]))
                   for vertex, uv in zip(vertices[i], triangles[i])]
        for j in range(3):
            edge = tuple(sorted((corners[j], corners[(j + 1) % 3])))
            if edge in edges:
                parent[root(i)] = root(edges[edge])
            else:
                edges[edge] = i
    return [root(i) for i in range(len(triangles))]


def face_charts(triangles, vertices, faces):
    """Map each source face to the smallest face index in its UV-connected chart."""
    tri, ids = np.asarray(triangles, dtype=float), np.asarray(vertices)
    if (tri.ndim != 3 or tri.shape[1:] != (3, 2) or not 1 <= len(tri) <= MAX_TRIANGLES
            or ids.shape != (len(tri), 3) or ids.dtype.kind not in 'iu' or (ids < 0).any()
            or len(faces) != len(tri) or any(type(f) is not int or f < 0 for f in faces)
            or not np.isfinite(tri).all() or (np.abs(tri) > 1e6).any()):
        raise ValueError('Chart inspection needs finite source UV triangles, vertex IDs and face indices')
    labels = _charts(tri, ids, range(len(tri)))
    smallest = {}
    for label, face in zip(labels, faces, strict=True):
        smallest[label] = min(smallest.get(label, face), face)
    result = {}
    for label, face in zip(labels, faces, strict=True):
        chart = smallest[label]
        if face in result and result[face] != chart:
            raise ValueError('Source polygon triangulation has disconnected UV components')
        result[face] = chart
    return result


def _candidate_pairs(lo, hi, padding):
    """Sweep X and query active Y intervals before spending a comparison.

    A fixed tree over sorted Y starts stores the maximum active padded Y end.
    Empty subtrees and intervals outside either axis are pruned without emitting
    pairs; the heap expires X intervals. Both indexes use linear storage.
    """
    count = len(lo)
    if not count:
        return
    by_y = sorted(range(count), key=lambda i: (lo[i, 1], i))
    starts = [lo[i, 1] for i in by_y]
    ranks = [0] * count
    for rank, index in enumerate(by_y):
        ranks[index] = rank
    size = 1
    while size < count:
        size *= 2
    maxima = [-math.inf] * (2 * size)

    def update(index, value):
        node = size + ranks[index]
        maxima[node] = value
        while node > 1:
            node //= 2
            maxima[node] = max(maxima[2 * node], maxima[2 * node + 1])

    expires = []
    for current in sorted(range(count), key=lambda i: (lo[i, 0], i)):
        while expires and expires[0][0] < lo[current, 0]:
            _, expired = heappop(expires)
            update(expired, -math.inf)
        stop = bisect_right(starts, hi[current, 1] + padding)
        pending = [(1, 0, size)]
        while pending:
            node, start, end = pending.pop()
            if start >= stop or maxima[node] < lo[current, 1]:
                continue
            if end - start == 1:
                yield by_y[start], current
            else:
                middle = (start + end) // 2
                pending.extend(((2 * node + 1, middle, end), (2 * node, start, middle)))
        update(current, hi[current, 1] + padding)
        heappush(expires, (hi[current, 0] + padding, current))


def overlapping(triangles, resolution=4096):
    """Triangles whose UV interior overlaps another's, by the rule analyze counts at this resolution.

    The search stops after the default comparison budget, so a pathological stack returns a subset.
    """
    tri = np.asarray(triangles, dtype=np.float64)
    if tri.ndim != 3 or tri.shape[1:] != (3, 2):
        raise ValueError('Provide UV triangles as three (u, v) corners')
    finite = np.isfinite(tri).all(axis=(1, 2))
    pixels = tri * resolution
    valid = np.array([i for i in np.flatnonzero(finite) if _area(pixels[i]) > AREA_EPSILON], dtype=int)
    if not len(valid):
        return []
    lo, hi = pixels[valid].min(axis=1), pixels[valid].max(axis=1)
    found, budget = set(), default_budget(len(tri))
    for comparisons, (x, y) in enumerate(_candidate_pairs(lo, hi, 0.)):
        if comparisons == budget:
            break
        i, j = int(valid[x]), int(valid[y])
        if triangle_intersection_area(pixels[i], pixels[j]) > AREA_EPSILON:
            found.update((i, j))
    return sorted(found)


def analyze(triangles, vertices, resolution, padding_pixels, comparison_budget=None):
    """Treat all input triangles as one texture set in a unique 0..1 tile.

    Source vertex IDs must be disjoint across objects. Pairwise intersection area
    is a sum over pairs, not the union area or an occupancy percentage. Work is
    bounded even when two-dimensional broadphase boxes overlap but their triangles do not.
    """
    if (len(resolution) != 2 or any(type(x) is not int or not 1 <= x <= 16384
                                    for x in resolution)):
        raise ValueError('Texture dimensions must be integers from 1 to 16384')
    if (isinstance(padding_pixels, bool) or not math.isfinite(padding_pixels)
            or not 0 <= padding_pixels <= 256):
        raise ValueError('Padding must be finite, from 0 to 256 pixels')
    if comparison_budget is None:
        comparison_budget = default_budget(len(triangles))
    if type(comparison_budget) is not int or not 1 <= comparison_budget <= MAX_COMPARISONS:
        raise ValueError('Comparison budget must be an integer from 1 to 1000000')
    tri = np.asarray(triangles, dtype=np.float64)
    ids = np.asarray(vertices)
    if (tri.ndim != 3 or tri.shape[1:] != (3, 2) or not 1 <= len(tri) <= MAX_TRIANGLES
            or ids.shape != (len(tri), 3) or ids.dtype.kind not in 'iu' or (ids < 0).any()):
        raise ValueError(f'Provide 1..{MAX_TRIANGLES} UV triangles and matching vertex IDs')
    finite = np.isfinite(tri).all(axis=(1, 2))
    if np.any(np.abs(tri[finite]) > 1e6):
        raise ValueError('UV coordinate magnitude must not exceed 1000000')
    pixels = tri * resolution
    areas = np.zeros(len(tri))
    for i in np.flatnonzero(finite):
        areas[i] = _area(pixels[i])
    degenerate = finite & (areas <= AREA_EPSILON)
    outside = finite & ((tri < 0) | (tri > 1)).any(axis=(1, 2))
    valid = np.flatnonzero(finite & ~degenerate)
    charts = _charts(tri, ids, valid)
    chart_count = len({charts[i] for i in valid})
    # Signed border clearance also identifies triangles beyond the unique tile.
    border = [float(min(pixels[i].min(),
                        np.min(np.asarray(resolution) - pixels[i]))) for i in valid]
    border_bad = sum(value + DISTANCE_EPSILON < padding_pixels for value in border)
    lo, hi = pixels[valid].min(axis=1), pixels[valid].max(axis=1)
    overlaps, padding_hits, comparisons, total_area = 0, 0, 0, 0.
    overlap_examples, padding_examples = [], []
    complete = True
    for x, y in _candidate_pairs(lo, hi, padding_pixels):
        if comparisons == comparison_budget:
            complete = False
            break
        comparisons += 1
        i, j = int(valid[x]), int(valid[y])
        area = triangle_intersection_area(pixels[i], pixels[j])
        if area > AREA_EPSILON:
            overlaps += 1
            total_area += area
            if len(overlap_examples) < EXAMPLES:
                overlap_examples.append({'triangles': [i, j], 'area_pixels2': area})
        if charts[i] != charts[j] and padding_pixels > 0:
            distance = 0. if area > 0 else _distance(pixels[i], pixels[j])
            if distance + DISTANCE_EPSILON < padding_pixels:
                padding_hits += 1
                if len(padding_examples) < EXAMPLES:
                    padding_examples.append({'triangles': [i, j], 'distance_pixels': distance})
    invalid = int((~finite).sum()) + int(degenerate.sum()) + int(outside.sum())
    return {
        'complete': complete, 'comparison_budget': comparison_budget,
        'comparisons': comparisons, 'triangles': len(tri), 'charts': chart_count,
        'texture_resolution': list(resolution),
        'area_epsilon_pixels2': AREA_EPSILON, 'distance_epsilon_pixels': DISTANCE_EPSILON,
        'nonfinite_triangles': int((~finite).sum()),
        'degenerate_triangles': int(degenerate.sum()),
        'outside_tile_triangles': int(outside.sum()),
        'overlap': {'triangle_pairs': overlaps, 'pairwise_area_pixels2': total_area,
                    'examples': overlap_examples},
        'padding': {'requested_pixels': float(padding_pixels),
                    'triangle_pairs_below_requested': padding_hits,
                    'border_triangles_below_requested': border_bad,
                    'minimum_border_pixels': min(border) if border else None,
                    'examples': padding_examples},
        'unique_tile_ready': bool(complete and len(valid) and not (
            invalid or overlaps or padding_hits or border_bad)),
    }
