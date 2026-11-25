"""Bounded mesh topology defects from numpy arrays, independent of Blender."""
import numpy as np

EXAMPLES = 32
# Metres after object rotation/scale and scene unit scale; Blender's Merge by Distance default.
COINCIDENT_DISTANCE_M = 1e-4
SLIVER_ANGLE_DEGREES = 1.0
MAX_COINCIDENT_CANDIDATES = 1_000_000
# Dimensionless barycentric margin for testing crossings through both triangle interiors.
CROSSING_EPSILON = 1e-6
CHUNK_PAIRS = 65536
_CELL_LIMIT = 2.0 ** 40
_HALF_SHELL = np.array([(0, 0, 0)] + [(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1)
                                      for z in (-1, 0, 1) if (x, y, z) > (0, 0, 0)], np.int64)


def _pairs(values):
    return np.asarray(values, np.int64).reshape(-1, 2)


def inconsistent_winding(loop_vertices, loop_edges, edge_count):
    """Edges with exactly two loops that start at the same vertex, so both faces run the same way."""
    loop_edges = np.asarray(loop_edges, np.int64)
    counts = np.bincount(loop_edges, minlength=edge_count)
    order = np.argsort(loop_edges, kind="stable")
    manifold = np.flatnonzero(counts == 2)
    first = (np.cumsum(counts) - counts)[manifold]
    starts = np.asarray(loop_vertices, np.int64)[order]
    edges = manifold[starts[first] == starts[first + 1]]
    return len(edges), edges[:EXAMPLES].tolist()


def _cell_keys(cells):
    return (cells[:, 0] * 73856093) ^ (cells[:, 1] * 19349663) ^ (cells[:, 2] * 83492791)


def _near_pairs(points, distance):
    """Sorted index pairs closer than distance, or None if the candidate limit is exceeded."""
    if len(points) < 2:
        return np.empty((0, 2), np.int64)
    cells = np.clip(np.floor(points / distance), -_CELL_LIMIT, _CELL_LIMIT).astype(np.int64)
    keys = _cell_keys(cells)
    order = np.argsort(keys, kind="stable")
    buckets, starts, sizes = np.unique(keys[order], return_index=True, return_counts=True)
    owners, firsts, counts = [], [], []
    for offset in _HALF_SHELL:
        probe = _cell_keys(cells + offset)
        slot = np.minimum(np.searchsorted(buckets, probe), len(buckets) - 1)
        hit = np.flatnonzero(buckets[slot] == probe)
        owners.append(hit)
        firsts.append(starts[slot[hit]])
        counts.append(sizes[slot[hit]])
    owners, firsts, counts = (np.concatenate(values) for values in (owners, firsts, counts))
    total = int(counts.sum())
    if total > MAX_COINCIDENT_CANDIDATES:
        return None
    run = np.repeat(np.arange(len(owners)), counts)
    local = np.arange(total) - np.repeat(np.cumsum(counts) - counts, counts)
    pairs = np.sort(np.stack([owners[run], order[firsts[run] + local]], 1), 1)
    gap = points[pairs[:, 0]] - points[pairs[:, 1]]
    keep = (pairs[:, 0] != pairs[:, 1]) & ((gap * gap).sum(1) < distance * distance)
    return np.unique(pairs[keep], axis=0)


def coincident_vertices(points, distance=COINCIDENT_DISTANCE_M):
    """Vertex pairs closer than distance; exact duplicates are counted without enumerating them."""
    finite = np.flatnonzero(np.isfinite(points).all(1))
    unique, inverse, sizes = np.unique(points[finite], axis=0, return_inverse=True,
                                       return_counts=True)
    near = _near_pairs(unique, distance)
    if near is None:
        return None, []
    count = int((sizes * (sizes - 1) // 2).sum() + (sizes[near[:, 0]] * sizes[near[:, 1]]).sum())
    if not count:
        return 0, []
    members = finite[np.argsort(inverse.reshape(-1), kind="stable")]
    starts = np.cumsum(sizes) - sizes
    lowest = members[starts]
    groups = np.flatnonzero(sizes > 1)
    # Groups and near group pairs own disjoint vertex pairs, so the first EXAMPLES pairs
    # come from the EXAMPLES sources with the lowest first pair.
    keys = np.concatenate([np.stack([lowest[groups], members[starts[groups] + 1]], 1),
                           np.sort(lowest[near], 1)])
    found = []
    for source in np.lexsort((keys[:, 1], keys[:, 0]))[:EXAMPLES]:
        if source < len(groups):
            group = groups[source]
            head = members[starts[group]:starts[group] + min(sizes[group], EXAMPLES + 1)]
            left, right = np.triu_indices(len(head), 1)
            found.append(np.stack([head[left], head[right]], 1))
        else:
            heads = [members[starts[g]:starts[g] + min(sizes[g], EXAMPLES)]
                     for g in near[source - len(groups)]]
            found.append(np.sort(np.stack(np.meshgrid(*heads, indexing="ij"), -1).reshape(-1, 2), 1))
    found = np.concatenate(found)
    return count, found[np.lexsort((found[:, 1], found[:, 0]))][:EXAMPLES].tolist()


def sliver_triangles(points, triangles, triangle_faces, excluded_faces,
                     degrees=SLIVER_ANGLE_DEGREES):
    """Triangles whose smallest interior angle is below degrees, outside excluded faces."""
    corners = points[triangles]
    smallest = np.full(len(triangles), np.inf)
    for k in range(3):
        first = corners[:, (k + 1) % 3] - corners[:, k]
        second = corners[:, (k + 2) % 3] - corners[:, k]
        angle = np.arctan2(np.linalg.norm(np.cross(first, second), axis=1),
                           (first * second).sum(1))
        smallest = np.minimum(smallest, angle)
    found = np.flatnonzero((smallest < np.radians(degrees)) & ~excluded_faces[triangle_faces])
    return len(found), np.stack([found, triangle_faces[found]], 1)[:EXAMPLES].tolist()


def _plane_interval(corners, origin, normal, axis):
    """Project the section of an inset triangle cut by a plane onto their intersection axis."""
    e = CROSSING_EPSILON
    inner = (1 - 3 * e) * corners + e * corners.sum(axis=1, keepdims=True)
    distance = np.einsum("nki,ni->nk", inner - origin[:, None, :], normal)
    next_distance = np.roll(distance, -1, axis=1)
    delta = distance - next_distance
    cut = (delta != 0) & (np.minimum(distance, next_distance) <= 0) & (
        np.maximum(distance, next_distance) >= 0)
    weight = np.divide(distance, delta, out=np.zeros_like(distance), where=cut)
    projected = np.einsum("nki,ni->nk", inner, axis)
    hits = projected + weight * (np.roll(projected, -1, axis=1) - projected)
    return np.where(cut, hits, np.inf).min(axis=1), np.where(cut, hits, -np.inf).max(axis=1)


def _crosses(left, right):
    """Nonparallel triangles whose plane sections overlap through both interiors."""
    origin = left[:, :1, :]
    left, right = left - origin, right - origin
    left_normal = np.cross(left[:, 1], left[:, 2])
    right_normal = np.cross(right[:, 1] - right[:, 0], right[:, 2] - right[:, 0])
    axis = np.cross(left_normal, right_normal)
    length = np.linalg.norm(axis, axis=1)
    scale = np.linalg.norm(left_normal, axis=1) * np.linalg.norm(right_normal, axis=1)
    nonparallel = length > 1e-12 * scale
    axis /= np.where(nonparallel, length, 1.)[:, None]
    left_min, left_max = _plane_interval(left, right[:, 0], right_normal, axis)
    right_min, right_max = _plane_interval(right, left[:, 0], left_normal, axis)
    return nonparallel & (np.maximum(left_min, right_min) < np.minimum(left_max, right_max))


def _share_vertex(face_pairs, loop_vertices, loop_starts, loop_totals):
    # Cache vertices per face so a large n-gon is stored once regardless of its crossing count.
    vertices = {face: set(loop_vertices[loop_starts[face]:loop_starts[face] + loop_totals[face]])
                for face in np.unique(face_pairs)}
    return np.fromiter((not vertices[a].isdisjoint(vertices[b]) for a, b in face_pairs),
                       bool, count=len(face_pairs))


def self_intersections(points, triangles, triangle_faces, loop_vertices, loop_starts,
                       loop_totals, candidates):
    """Face pairs without a shared vertex whose triangles cross through their interiors.

    candidates contains potential intersections, or None when the search exceeded its budget.
    """
    if candidates is None:
        return None, []
    pairs = _pairs(candidates)
    faces = triangle_faces[pairs]
    pairs = pairs[faces[:, 0] != faces[:, 1]]
    found = [np.empty((0, 2), np.int64)]
    for begin in range(0, len(pairs), CHUNK_PAIRS):
        part = pairs[begin:begin + CHUNK_PAIRS]
        left, right = points[triangles[part[:, 0]]], points[triangles[part[:, 1]]]
        found.append(part[_crosses(left, right)])
    crossed = np.unique(np.sort(triangle_faces[np.concatenate(found)].reshape(-1, 2), 1), axis=0)
    crossed = crossed[~_share_vertex(crossed, loop_vertices, loop_starts, loop_totals)]
    return len(crossed), crossed[:EXAMPLES].tolist()


def report(points, loop_vertices, loop_edges, loop_starts, loop_totals, edge_count, triangles,
           triangle_faces, zero_area_faces, candidates):
    """Topology defect counts with at most EXAMPLES ascending examples each.

    points are metres; triangles index points and map to faces through triangle_faces;
    candidates are triangle index pairs that may intersect, or None for an incomplete search.
    """
    points = np.asarray(points, np.float64).reshape(-1, 3)
    loop_vertices = np.asarray(loop_vertices, np.int64)
    loop_starts = np.asarray(loop_starts, np.int64)
    loop_totals = np.asarray(loop_totals, np.int64)
    triangles = np.asarray(triangles, np.int64).reshape(-1, 3)
    triangle_faces = np.asarray(triangle_faces, np.int64)
    winding = inconsistent_winding(loop_vertices, loop_edges, edge_count)
    coincident = coincident_vertices(points)
    slivers = sliver_triangles(points, triangles, triangle_faces,
                               np.asarray(zero_area_faces, bool))
    crossings = self_intersections(points, triangles, triangle_faces, loop_vertices, loop_starts,
                                   loop_totals, candidates)
    return {"inconsistent_winding_edges": winding[0],
            "inconsistent_winding_edge_examples": winding[1],
            "coincident_vertex_pairs": coincident[0],
            "coincident_vertex_pairs_complete": coincident[0] is not None,
            "coincident_vertex_pair_examples": coincident[1],
            "coincident_distance_m": COINCIDENT_DISTANCE_M,
            "sliver_triangles": slivers[0],
            "sliver_triangle_examples": slivers[1],
            "sliver_angle_degrees": SLIVER_ANGLE_DEGREES,
            "self_intersecting_face_pairs": crossings[0],
            "self_intersecting_face_pairs_complete": crossings[0] is not None,
            "self_intersecting_face_pair_examples": crossings[1]}
