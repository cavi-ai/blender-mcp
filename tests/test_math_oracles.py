"""Pure math modules checked against independent scipy and numpy oracles."""
import math
import unittest
from fractions import Fraction

import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.linalg import lstsq, svdvals
from scipy.ndimage import uniform_filter1d
from scipy.optimize import linprog, minimize
from scipy.sparse.csgraph import csgraph_from_dense, dijkstra
from scipy.spatial import ConvexHull, Delaunay, HalfspaceIntersection, QhullError

from cavi_blender_mcp import (
    geometry,
    mapping,
    skin_projection,
    spatial_query,
    surface_ray,
    terrain_field,
    udim_coverage,
    uv_layout,
    uvmath,
    vertex_edit,
)


def hull_area(points):
    """2D polygon area from qhull; zero for collinear input."""
    try:
        return float(ConvexHull(np.asarray(points, float)).volume)
    except QhullError:
        return 0.0


def convex_intersection_area(*polygons):
    """Area of the intersection of convex polygons from qhull halfspaces."""
    points = np.concatenate([np.asarray(p, float) for p in polygons])
    center = points.mean(axis=0)
    scale = float(np.abs(points - center).max()) or 1.0
    halfspaces = []
    for polygon in polygons:
        try:
            halfspaces.append(ConvexHull((np.asarray(polygon, float) - center) / scale).equations)
        except QhullError:
            return 0.0
    halfspaces = np.concatenate(halfspaces)
    normals, offsets = halfspaces[:, :2], halfspaces[:, 2]
    norms = np.linalg.norm(normals, axis=1)
    center_lp = linprog([0, 0, -1], A_ub=np.column_stack([normals, norms]), b_ub=-offsets,
                        bounds=[(None, None), (None, None), (0, None)])
    if not center_lp.success or center_lp.x[2] <= 1e-9:
        return 0.0
    corners = HalfspaceIntersection(halfspaces, center_lp.x[:2]).intersections
    return hull_area(corners) * scale * scale


def scaled(points, center, scale):
    return [tuple((np.asarray(p, float) - center) / scale) for p in points]


def slsqp_min(objective, gradient, starts, simplices, segments=0):
    """Smallest SLSQP minimum over starts; each simplex block is (w1, w2) with w1 + w2 <= 1."""
    constraints = []
    for block in range(simplices):
        row = np.zeros(2 * simplices + segments)
        row[2 * block:2 * block + 2] = -1

        def ineq(x, row=row):
            return 1 + row @ x
        constraints.append({'type': 'ineq', 'fun': ineq, 'jac': lambda x, row=row: row})
    best = math.inf
    for start in starts:
        result = minimize(objective, np.asarray(start, float), jac=gradient, method='SLSQP',
                          bounds=[(0, 1)] * len(start), constraints=constraints,
                          options={'ftol': 1e-16, 'maxiter': 1000})
        best = min(best, float(result.fun))
    return math.sqrt(max(best, 0.0))


SIMPLEX_STARTS = [(1 / 3, 1 / 3), (0, 0), (1, 0), (0, 1), (0.5, 0.5)]


def point_triangle_oracle(point, triangle):
    points = np.asarray([point, *triangle], float)
    center, scale = points.mean(axis=0), float(np.abs(points - points.mean(axis=0)).max()) or 1.0
    p, a, b, c = (np.asarray(v, float) for v in scaled(points, center, scale))
    edges = np.column_stack([b - a, c - a])

    def objective(w):
        delta = a + edges @ w - p
        return delta @ delta

    def gradient(w):
        return 2 * edges.T @ (a + edges @ w - p)
    return slsqp_min(objective, gradient, SIMPLEX_STARTS, 1) * scale


def segment_oracle(p1, q1, p2, q2):
    points = np.asarray([p1, q1, p2, q2], float)
    center, scale = points.mean(axis=0), float(np.abs(points - points.mean(axis=0)).max()) or 1.0
    p1, q1, p2, q2 = (np.asarray(v, float) for v in scaled(points, center, scale))
    basis = np.column_stack([q1 - p1, -(q2 - p2)])

    def objective(x):
        delta = p1 - p2 + basis @ x
        return delta @ delta

    def gradient(x):
        return 2 * basis.T @ (p1 - p2 + basis @ x)
    starts = [(s, t) for s in (0, 0.5, 1) for t in (0, 0.5, 1)]
    return slsqp_min(objective, gradient, starts, 0, segments=2) * scale


def triangle_oracle(first, second):
    points = np.asarray([*first, *second], float)
    center, scale = points.mean(axis=0), float(np.abs(points - points.mean(axis=0)).max()) or 1.0
    a0, a1, a2, b0, b1, b2 = (np.asarray(v, float) for v in scaled(points, center, scale))
    basis = np.column_stack([a1 - a0, a2 - a0, -(b1 - b0), -(b2 - b0)])

    def objective(x):
        delta = a0 - b0 + basis @ x
        return delta @ delta

    def gradient(x):
        return 2 * basis.T @ (a0 - b0 + basis @ x)
    corners = [(1 / 3, 1 / 3), (0, 0), (1, 0), (0, 1)]
    starts = [(*u, *v) for u in corners for v in corners[:2]] + [(*u, 1 / 3, 1 / 3) for u in corners]
    return slsqp_min(objective, gradient, starts, 2) * scale


def as_tuples(triangle):
    return tuple(tuple(float(v) for v in point) for point in triangle)


class TriangleIntersectionOracle(unittest.TestCase):
    def test_random_pairs_match_halfspace_intersection(self):
        rng = np.random.default_rng(101)
        for scale in (1e-4, 1.0, 1e4, 1e10):
            for _ in range(150):
                a = rng.uniform(-1, 1, (3, 2)) * scale + 3 * scale
                b = rng.uniform(-1, 1, (3, 2)) * scale + 3 * scale
                expected = convex_intersection_area(a, b)
                with self.subTest(scale=scale, a=a.tolist(), b=b.tolist()):
                    self.assertAlmostEqual(uv_layout.triangle_intersection_area(a, b), expected,
                                           delta=1e-8 * scale * scale)

    def test_containment_identity_and_winding(self):
        outer = np.array([[0., 0.], [4., 0.], [0., 4.]])
        inner = np.array([[0.5, 0.5], [1.5, 0.5], [0.5, 1.5]])
        for a, b in ((outer, inner), (inner, outer), (outer[::-1], inner), (inner, outer[::-1])):
            self.assertAlmostEqual(uv_layout.triangle_intersection_area(a, b), hull_area(inner))
        self.assertAlmostEqual(uv_layout.triangle_intersection_area(outer, outer[::-1]),
                               hull_area(outer))

    def test_disjoint_touching_and_degenerate_have_zero_area(self):
        base = np.array([[0., 0.], [1., 0.], [0., 1.]])
        cases = {
            'disjoint': np.array([[2., 2.], [3., 2.], [2., 3.]]),
            'shared_edge': np.array([[1., 0.], [0., 1.], [1., 1.]]),
            'shared_vertex': np.array([[1., 0.], [2., 0.], [2., 1.]]),
            'collinear_inside': np.array([[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]),
            'point_inside': np.array([[0.2, 0.2], [0.2, 0.2], [0.2, 0.2]]),
        }
        for name, other in cases.items():
            for a, b in ((base, other), (other, base)):
                with self.subTest(name):
                    self.assertEqual(convex_intersection_area(a, b), 0.0)
                    self.assertEqual(uv_layout.triangle_intersection_area(a, b), 0.0)

    def test_random_shared_edges_have_exactly_zero_area(self):
        rng = np.random.default_rng(102)
        for _ in range(500):
            a, b, c = rng.uniform(-1, 1, (3, 2))
            # The other triangle lies on the opposite side of the shared edge.
            d = a + b - c
            self.assertEqual(uv_layout.triangle_intersection_area(
                np.array([a, b, c]), np.array([b, a, d])), 0.0)


class UvRasterOracle(unittest.TestCase):
    @staticmethod
    def raster(triangles, resolution):
        ix, iy = np.meshgrid(np.arange(resolution), np.arange(resolution))
        centers = np.column_stack([ix.ravel(), iy.ravel()]) + 0.5
        counts = np.zeros(resolution * resolution, np.int64)
        for triangle in np.asarray(triangles, float) * resolution:
            try:
                counts += Delaunay(triangle).find_simplex(centers) >= 0
            except QhullError:
                continue
        return counts.reshape(resolution, resolution)

    def assert_overlap_report(self, triangles, resolution, expected_counts):
        report = uvmath.overlap(triangles, resolution)
        covered = int((expected_counts > 0).sum())
        overlapped = int((expected_counts > 1).sum())
        self.assertEqual(report['covered_cells'], covered)
        self.assertEqual(report['overlapping_cells'], overlapped)
        self.assertEqual(report['coverage_ratio'], covered / resolution ** 2)
        self.assertEqual(report['overlap_ratio'], overlapped / covered if covered else 0.0)

    def test_random_triangles_match_delaunay_containment(self):
        rng = np.random.default_rng(201)
        for resolution, count, size in ((17, 40, 0.4), (64, 60, 0.3), (256, 12, 0.6), (5, 30, 0.8)):
            centers = rng.uniform(-0.1, 1.1, (count, 1, 2))
            triangles = centers + rng.uniform(-size, size, (count, 3, 2))
            expected = self.raster(triangles, resolution)
            with self.subTest(resolution=resolution):
                np.testing.assert_array_equal(uvmath.coverage(triangles, resolution), expected)
                self.assert_overlap_report(triangles, resolution, expected)

    def test_large_triangle_banded_path(self):
        triangles = np.array([[[0.01317, 0.02093], [1.3113, 0.07111], [0.18147, 0.97731]],
                              [[0.90071, 0.95013], [0.41117, 0.33071], [0.97013, 0.12093]]])
        expected = self.raster(triangles, 1500)
        np.testing.assert_array_equal(uvmath.coverage(triangles, 1500), expected)

    def test_tiny_and_degenerate_triangles(self):
        triangles = np.array([
            [[0.5, 0.5], [0.5, 0.5], [0.5, 0.5]],
            [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]],
            [[0.3001, 0.3002], [0.3004, 0.3001], [0.3002, 0.3005]],
            [[0.1874, 0.1874], [0.1876, 0.1874], [0.1875, 0.1877]],
        ])
        expected = self.raster(triangles, 8)
        self.assertEqual(int(expected.sum()), 1)
        np.testing.assert_array_equal(uvmath.coverage(triangles, 8), expected)

    def test_shared_edges_and_vertices_through_centers_cover_once(self):
        resolution = 8
        # Fan of eight triangles around a cell center; all spokes pass through cell centers.
        hub = np.array([3.5, 4.5]) / resolution
        rim = np.array([[1.2, 2.2], [3.5, 2.2], [5.8, 2.2], [5.8, 4.5], [5.8, 6.8], [3.5, 6.8],
                        [1.2, 6.8], [1.2, 4.5]]) / resolution
        fan = [[hub, rim[i], rim[(i + 1) % 8]] for i in range(8)]
        square = np.array([[0., 0.], [1., 0.], [1., 1.], [0., 1.]])
        diagonal = [square[[0, 1, 2]], square[[0, 2, 3]]]
        for name, triangles, union in (('fan', fan, rim[[0, 2, 4, 6]]),
                                       ('diagonal', diagonal, square)):
            union_hull = Delaunay(np.asarray(union) * resolution)
            ix, iy = np.meshgrid(np.arange(resolution), np.arange(resolution))
            centers = np.column_stack([ix.ravel(), iy.ravel()]) + 0.5
            expected = (union_hull.find_simplex(centers) >= 0).reshape(resolution, resolution)
            with self.subTest(name):
                np.testing.assert_array_equal(uvmath.coverage(np.asarray(triangles), resolution),
                                              expected.astype(np.int32))
                reversed_winding = np.asarray(triangles)[:, ::-1]
                np.testing.assert_array_equal(uvmath.coverage(reversed_winding, resolution),
                                              expected.astype(np.int32))

    def test_density_matches_gram_and_hull_areas(self):
        rng = np.random.default_rng(202)
        for scale in (1e-3, 1.0, 1e3):
            points = rng.normal(size=(30, 3, 3)) * scale
            uvs = rng.uniform(0, 1, (30, 3, 2))
            points[3, 1:] = points[3, 0]
            uvs[4, 2] = uvs[4, 0]
            world = np.array([0.5 * math.sqrt(max(np.linalg.det(e.T @ e), 0)) for e in
                              (np.column_stack([t[1] - t[0], t[2] - t[0]]) for t in points)])
            uv_area = np.array([hull_area(t) for t in uvs])
            valid = (world > 1e-12) & (uv_area > 1e-12)
            self.assertEqual(int((~valid).sum()), 2)
            expected = math.sqrt(2048 * 512 * uv_area[valid].sum() / world[valid].sum())
            with self.subTest(scale=scale):
                self.assertAlmostEqual(uvmath.density(points, uvs, (2048, 512)) / expected, 1,
                                       places=6)
        self.assertIsNone(uvmath.density(np.zeros((1, 3, 3)), np.zeros((1, 3, 2)), (8, 8)))


class MappingOracle(unittest.TestCase):
    @staticmethod
    def jacobian_singular_values(points, uv, resolution):
        points, uv = np.asarray(points, float), np.asarray(uv, float)
        world_edges = np.column_stack([points[1] - points[0], points[2] - points[0]])
        tangent, _ = np.linalg.qr(world_edges)
        local = tangent.T @ world_edges
        pixel = (np.column_stack([uv[1] - uv[0], uv[2] - uv[0]]).T * np.asarray(resolution)).T
        jacobian_t, *_ = lstsq(local.T, pixel.T)
        return svdvals(jacobian_t.T)

    def test_random_triangles_match_jacobian_svd(self):
        rng = np.random.default_rng(301)
        for scale in (1e-4, 1.0, 1e5):
            for _ in range(100):
                points = rng.normal(size=(3, 3)) * scale
                uv = rng.uniform(-1, 2, (3, 2))
                resolution = tuple(int(v) for v in rng.integers(1, 16385, 2))
                result = mapping.measure_triangle(points.tolist(), uv.tolist(), resolution)
                largest, smallest = self.jacobian_singular_values(points, uv, resolution)
                with self.subTest(scale=scale, points=points.tolist(), uv=uv.tolist()):
                    self.assertAlmostEqual(result['density'] / math.sqrt(largest * smallest), 1,
                                           places=9)
                    self.assertAlmostEqual(result['anisotropy'] / (largest / smallest), 1,
                                           places=6)
                    self.assertAlmostEqual(result['uv_area'] / hull_area(uv), 1, places=9)

    def test_isotropic_stretched_and_degenerate_cases(self):
        rotation = np.linalg.qr(np.random.default_rng(302).normal(size=(3, 3)))[0]
        flat = np.array([[0., 0., 0.], [2., 0., 0.], [0.5, 1.5, 0.]])
        points = flat @ rotation.T + [1e5, -1e5, 3e4]
        uv = flat[:, :2] / 4
        result = mapping.measure_triangle(points.tolist(), uv.tolist(), (1024, 1024))
        largest, smallest = self.jacobian_singular_values(points, uv, (1024, 1024))
        self.assertAlmostEqual(largest / smallest, 1, places=6)
        self.assertAlmostEqual(result['density'], 256, places=4)
        self.assertAlmostEqual(result['anisotropy'], 1, places=6)
        stretched = uv * [8, 0.125]
        result = mapping.measure_triangle(points.tolist(), stretched.tolist(), (1024, 1024))
        largest, smallest = self.jacobian_singular_values(points, stretched, (1024, 1024))
        self.assertAlmostEqual(result['anisotropy'] / (largest / smallest), 1, places=6)
        self.assertAlmostEqual(result['anisotropy'], 64, places=4)
        collinear = [[0, 0, 0], [1, 1, 1], [2, 2, 2]]
        self.assertIsNone(mapping.measure_triangle(collinear, uv.tolist(), (64, 64))['density'])
        self.assertIsNone(mapping.measure_triangle(points.tolist(), [[0, 0], [1, 1], [2, 2]],
                                                   (64, 64))['density'])

    def test_summary_matches_numpy_weighted_statistics(self):
        rng = np.random.default_rng(303)
        samples = []
        for _ in range(400):
            points = rng.normal(size=(3, 3)) * rng.uniform(0.01, 3)
            uv = rng.uniform(0, 1, (3, 2))
            samples.append(mapping.measure_triangle(points.tolist(), uv.tolist(), (512, 2048)))
        samples.append(mapping.measure_triangle([[0, 0, 0], [1, 0, 0], [0, 1, 0]], None, (8, 8)))
        samples.append(mapping.measure_triangle([[0, 0, 0], [1, 0, 0], [2, 0, 0]],
                                                [[0, 0], [1, 0], [0, 1]], (8, 8)))
        valid = [s for s in samples if s['density'] is not None]
        density = np.array([s['density'] for s in valid])
        weight = np.array([s['world_area_m2'] for s in valid])
        summary = mapping.summarize(samples)
        for key, fraction in (('density_p10', 0.1), ('density_p90', 0.9)):
            self.assertEqual(summary[key], float(np.quantile(density, fraction, weights=weight,
                                                             method='inverted_cdf')))
        self.assertAlmostEqual(summary['density_area_weighted'] /
                               math.sqrt(np.average(density ** 2, weights=weight)), 1, places=12)
        self.assertEqual(summary['density_min'], density.min())
        self.assertEqual(summary['density_max'], density.max())
        self.assertEqual(summary['uv_missing_triangles'], 1)
        self.assertEqual(summary['world_degenerate_triangles'], 1)
        self.assertAlmostEqual(summary['mapping_coverage'],
                               weight.sum() / sum(s['world_area_m2'] for s in samples))


class SpatialDistanceOracle(unittest.TestCase):
    def test_point_triangle_distance_matches_slsqp(self):
        rng = np.random.default_rng(401)
        triangle = ((0., 0., 0.), (2., 0., 0.), (0., 1., 0.))
        fixed = [((0.3, 0.3, 1.5), 1.5), ((3., 0., 0.), 1.), ((-1., -1., 0.), math.sqrt(2)),
                 ((1., 0.5, 0.), 0.), ((0.5, -2., 0.), 2.)]
        for point, expected in fixed:
            self.assertAlmostEqual(spatial_query.point_triangle_distance(point, triangle), expected)
            self.assertAlmostEqual(point_triangle_oracle(point, triangle), expected, places=7)
        for scale in (1e-3, 1.0, 1e3):
            for _ in range(80):
                triangle = as_tuples(rng.normal(size=(3, 3)) * scale)
                point = tuple(float(v) for v in rng.normal(size=3) * scale * 1.5)
                with self.subTest(scale=scale, point=point, triangle=triangle):
                    self.assertAlmostEqual(spatial_query.point_triangle_distance(point, triangle),
                                           point_triangle_oracle(point, triangle),
                                           delta=1e-6 * scale)
        degenerate = ((0., 0., 0.), (1., 1., 0.), (2., 2., 0.))
        self.assertAlmostEqual(spatial_query.point_triangle_distance((0., 1., 0.), degenerate),
                               math.sqrt(0.5))

    def test_segment_distance_matches_slsqp(self):
        rng = np.random.default_rng(402)
        fixed = [
            (((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)), 1.0),
            (((0, 0, 0), (2, 0, 0), (1, 0, 0), (3, 0, 0)), 0.0),
            (((0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)), 1.0),
            (((0, 0, 0), (2, 0, 0), (1, -1, 1), (1, 1, 1)), 1.0),
            (((0, 0, 0), (2, 0, 0), (1, -1, 0), (1, 1, 0)), 0.0),
            (((0, 0, 0), (0, 0, 0), (1, -1, 1), (1, 1, 1)), math.sqrt(2)),
            (((0, 0, 0), (0, 0, 0), (3, 4, 0), (3, 4, 0)), 5.0),
            (((0, 0, 0), (1, 0, 0), (2, 1, 0), (4, 1, 0)), math.sqrt(2)),
        ]
        for points, expected in fixed:
            points = [tuple(float(v) for v in p) for p in points]
            with self.subTest(points=points):
                self.assertAlmostEqual(spatial_query.segment_distance(*points), expected)
                self.assertAlmostEqual(segment_oracle(*points), expected, places=7)
        for scale in (1e-3, 1.0, 1e3):
            for _ in range(80):
                points = [tuple(float(v) for v in p) for p in rng.normal(size=(4, 3)) * scale]
                if rng.random() < 0.3:
                    # Nearly parallel second segment.
                    direction = np.subtract(points[1], points[0])
                    points[3] = tuple(np.add(points[2], direction * rng.uniform(-2, 2)
                                             + rng.normal(size=3) * 1e-7 * scale))
                with self.subTest(scale=scale, points=points):
                    self.assertAlmostEqual(spatial_query.segment_distance(*points),
                                           segment_oracle(*points), delta=1e-6 * scale)

    def test_triangle_distance_matches_slsqp(self):
        rng = np.random.default_rng(403)
        base = ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.))
        fixed = {
            'piercing': (((0.2, 0.2, -1.), (0.3, 0.2, 1.), (0.2, 0.3, 1.)), 0.0),
            'coplanar_overlap': (((0.1, 0.1, 0.), (2., 0.1, 0.), (0.1, 2., 0.)), 0.0),
            'coplanar_contained': (((0.1, 0.1, 0.), (0.2, 0.1, 0.), (0.1, 0.2, 0.)), 0.0),
            'shared_vertex': (((1., 0., 0.), (2., 0., 1.), (2., 1., 0.)), 0.0),
            'parallel_above': (((0., 0., 2.), (1., 0., 2.), (0., 1., 2.)), 2.0),
            'edge_edge': (((0.5, 0.5, 1.), (0.5, 0.5, 3.), (2., 2., 1.)), 1.0),
            'coplanar_apart': (((2., 0., 0.), (3., 0., 0.), (2., 1., 0.)), 1.0),
            'degenerate_piercing': (((0.2, 0.2, -1.), (0.2, 0.2, 1.), (0.2, 0.2, 0.5)), 0.0),
            'degenerate_above': (((0.2, 0.2, 1.), (0.2, 0.2, 2.), (0.2, 0.2, 3.)), 1.0),
        }
        for name, (other, expected) in fixed.items():
            with self.subTest(name):
                self.assertAlmostEqual(spatial_query.triangle_distance(base, other), expected)
                self.assertAlmostEqual(spatial_query.triangle_distance(other, base), expected)
                self.assertAlmostEqual(triangle_oracle(base, other), expected, places=6)
        for scale, offset in ((1e-3, 0.), (1.0, 0.), (1e3, 0.), (1.0, 1e5)):
            for _ in range(40):
                first = as_tuples(rng.normal(size=(3, 3)) * scale + offset)
                second = as_tuples(rng.normal(size=(3, 3)) * scale + rng.normal(size=3) * scale
                                   + offset)
                with self.subTest(scale=scale, first=first, second=second):
                    self.assertAlmostEqual(spatial_query.triangle_distance(first, second),
                                           triangle_oracle(first, second), delta=1e-6 * scale)

    def test_prove_distance_matches_brute_force(self):
        rng = np.random.default_rng(404)
        for case in range(3):
            subjects = [as_tuples(rng.normal(size=(3, 3)) * 0.3 + rng.normal(size=3))
                        for _ in range(6)]
            context = [as_tuples(rng.normal(size=(3, 3)) * 0.3 + rng.normal(size=3)
                                 + [2.5, 0, 0]) for _ in range(6)]
            truth = min(triangle_oracle(a, b) for a in subjects for b in context)
            upper = math.dist(subjects[0][0], context[0][0])
            result = spatial_query.prove_distance(subjects, context, upper, 10000)
            with self.subTest(case=case):
                self.assertTrue(result['proven'])
                self.assertAlmostEqual(result['lower_m'], truth, delta=1e-6)
                self.assertEqual(result['lower_m'], result['upper_m'])
                for budget in (0, 1, 2, 3, 5, 8):
                    partial = spatial_query.prove_distance(subjects, context, upper, budget)
                    if partial['proven']:
                        self.assertAlmostEqual(partial['lower_m'], truth, delta=1e-6)
                    else:
                        self.assertLessEqual(partial['lower_m'], truth + 1e-9)
                        self.assertGreaterEqual(partial['upper_m'], truth - 1e-6)


class VertexEditOracle(unittest.TestCase):
    def test_geodesic_weights_match_csgraph_dijkstra(self):
        rng = np.random.default_rng(501)
        linears = [((1, 0, 0), (0, 1, 0), (0, 0, 1)), ((2, 0.7, 0), (0, 0.5, -0.3), (0.1, 0, 3)),
                   tuple(map(tuple, rng.normal(size=(3, 3)).tolist()))]
        for linear, unit in zip(linears, (1.0, 0.01, 3.0), strict=True):
            for _ in range(4):
                count = 120
                vertices = rng.uniform(-1, 1, (count, 3))
                pairs = {tuple(sorted(int(v) for v in rng.choice(count, 2, replace=False)))
                         for _ in range(400)}
                edges = sorted(pairs)
                world = vertices @ np.asarray(linear, float).T * unit
                dense = np.full((count, count), np.inf)
                for a, b in edges:
                    dense[a, b] = dense[b, a] = np.linalg.norm(world[b] - world[a])
                seeds = [int(v) for v in rng.choice(count, 3, replace=False)]
                radius = float(np.median([dense[a, b] for a, b in edges]) * 2.5)
                distance = dijkstra(csgraph_from_dense(dense, null_value=np.inf), directed=False,
                                    indices=seeds, limit=radius, min_only=True)
                inside = np.flatnonzero(distance < radius)
                t = distance[inside] / radius
                expected = list(zip(inside.tolist(), ((1 - t) ** 2 * (1 + 2 * t)).tolist()))
                result = vertex_edit.geodesic_weights(vertices.tolist(), edges, seeds, radius,
                                                      linear=linear, unit_m=unit)
                with self.subTest(linear=linear):
                    self.assertEqual([i for i, _ in result], [i for i, _ in expected])
                    np.testing.assert_allclose([w for _, w in result], [w for _, w in expected],
                                               rtol=1e-12, atol=1e-12)

    def test_plane_scale_matches_inverse_row_distance(self):
        rng = np.random.default_rng(502)
        linears = [np.diag([2., 3., 0.5]), np.array([[1., 0.8, 0.], [0., 1., 0.], [0., 0., 1.]]),
                   np.array([[1e3, 0., 0.], [0.4e3, 1e-3, 0.], [0., 0.2, 1.]])]
        linears += [rng.normal(size=(3, 3)) for _ in range(20)]
        for linear in linears:
            inverse = np.linalg.inv(linear)
            for dimension in range(3):
                for unit in (0.01, 1.0, 100.0):
                    expected = unit / np.linalg.norm(inverse[dimension])
                    local = rng.normal(size=3)
                    world = unit * linear @ local
                    plane_normal = inverse[dimension] / np.linalg.norm(inverse[dimension])
                    measured = abs(world @ plane_normal) / abs(local[dimension])
                    with self.subTest(linear=linear.tolist(), dimension=dimension, unit=unit):
                        scale = vertex_edit._plane_scale(linear.tolist(), dimension, unit)
                        self.assertAlmostEqual(scale / expected, 1, places=10)
                        self.assertAlmostEqual(scale / measured, 1, places=8)


class TerrainFieldOracle(unittest.TestCase):
    def test_prefilter_matches_uniform_filter_mirror(self):
        rng = np.random.default_rng(601)
        for shape, resolution, scale in (((257, 129), 9, 1.0), ((65, 300), 5, 1e6), ((7, 9), 2, 1e-6),
                                         ((33, 33), 33, 1.0), ((101, 51), 3, 1.0), ((1, 40), 4, 1.0),
                                         ((2, 2), 2, 1.0)):
            grid = rng.normal(size=shape) * scale
            expected = grid
            for axis in (0, 1):
                half = (shape[axis] - 1) // (resolution - 1) // 2
                if half:
                    expected = uniform_filter1d(expected, 2 * half + 1, axis=axis, mode='mirror')
            with self.subTest(shape=shape, resolution=resolution):
                np.testing.assert_allclose(terrain_field.prefilter(grid, resolution), expected,
                                           rtol=1e-9, atol=1e-9 * scale)

    def test_linear_sample_matches_regular_grid_interpolator(self):
        rng = np.random.default_rng(602)
        for shape, resolution in (((5, 9), 17), ((33, 12), 7), ((2, 2), 2), ((4, 4), 101)):
            grid = rng.normal(size=shape)
            height, width = shape
            interpolator = RegularGridInterpolator((np.arange(height), np.arange(width)), grid)
            y, x = np.meshgrid(np.linspace(0, height - 1, resolution),
                               np.linspace(0, width - 1, resolution), indexing='ij')
            expected = interpolator(np.stack([y, x], axis=-1))
            with self.subTest(shape=shape, resolution=resolution):
                np.testing.assert_allclose(terrain_field.sample(grid, resolution, ease=lambda t: t),
                                           expected, rtol=1e-12, atol=1e-12)


def perspective(left, right, bottom, top, near, far):
    return np.array([[2 * near / (right - left), 0, (right + left) / (right - left), 0],
                     [0, 2 * near / (top - bottom), (top + bottom) / (top - bottom), 0],
                     [0, 0, -(far + near) / (far - near), -2 * far * near / (far - near)],
                     [0, 0, -1, 0]])


def orthographic(left, right, bottom, top, near, far):
    return np.array([[2 / (right - left), 0, 0, -(right + left) / (right - left)],
                     [0, 2 / (top - bottom), 0, -(top + bottom) / (top - bottom)],
                     [0, 0, -2 / (far - near), -(far + near) / (far - near)],
                     [0, 0, 0, 1]])


class SurfaceRayOracle(unittest.TestCase):
    def test_local_ray_matches_homogeneous_solve(self):
        rng = np.random.default_rng(701)
        for scale in (1e-3, 1.0, 1e3):
            for _ in range(60):
                matrix = np.eye(4)
                matrix[:3, :3] = rng.normal(size=(3, 3)) * scale
                matrix[:3, 3] = rng.normal(size=3) * 10
                origin, direction = rng.normal(size=3) * 5, rng.normal(size=3) * rng.uniform(0.1, 9)
                unit, reach = float(rng.uniform(0.01, 10)), float(rng.uniform(0.1, 100))
                world_end = origin + direction / np.linalg.norm(direction) * reach / unit
                start = np.linalg.solve(matrix, [*origin, 1])[:3]
                end = np.linalg.solve(matrix, [*world_end, 1])[:3]
                local_start, local_direction, distance = surface_ray.local_ray(
                    origin.tolist(), direction.tolist(), reach, matrix.tolist(), unit)
                with self.subTest(scale=scale):
                    np.testing.assert_allclose(local_start, start, rtol=1e-9, atol=1e-9)
                    self.assertAlmostEqual(distance / np.linalg.norm(end - start), 1, places=9)
                    np.testing.assert_allclose(local_direction, (end - start) / np.linalg.norm(end - start),
                                               atol=1e-9)
                    back = matrix @ [*(np.asarray(local_start) + np.asarray(local_direction) * distance), 1]
                    np.testing.assert_allclose(back[:3], world_end, rtol=1e-9, atol=1e-9 * (1 + reach / unit))

    def test_pixel_ray_reprojects_to_pixel_center_and_clip_planes(self):
        rng = np.random.default_rng(702)
        for kind in ('PERSP', 'ORTHO'):
            for _ in range(40):
                near, far = float(rng.uniform(0.01, 1)), float(rng.uniform(5, 1000))
                left, right = -rng.uniform(0.1, 2), rng.uniform(0.1, 2)
                bottom, top = -rng.uniform(0.1, 2), rng.uniform(0.1, 2)
                build = perspective if kind == 'PERSP' else orthographic
                projection = build(left * near, right * near, bottom * near, top * near, near, far)
                rotation = np.linalg.qr(rng.normal(size=(3, 3)))[0]
                world = np.eye(4)
                world[:3, :3], world[:3, 3] = rotation, rng.normal(size=3) * 20
                size = [int(v) for v in rng.integers(1, 4000, 2)]
                pixel = [float(rng.uniform(0, s - 1)) for s in size]
                start, direction, span = surface_ray.pixel_ray(pixel, size, projection.tolist(),
                                                               world.tolist(), kind, near, far)
                end = np.asarray(start) + np.asarray(direction) * span
                expected_ndc = [2 * (pixel[0] + 0.5) / size[0] - 1, 1 - 2 * (pixel[1] + 0.5) / size[1]]
                inverse_world = np.linalg.inv(world)
                with self.subTest(kind=kind, pixel=pixel, size=size):
                    self.assertAlmostEqual(np.linalg.norm(direction), 1, places=12)
                    for point, depth in ((start, near), (end, far)):
                        camera = inverse_world @ [*point, 1]
                        self.assertAlmostEqual(camera[2] / -depth, 1, places=9)
                        clip = projection @ camera
                        np.testing.assert_allclose(clip[:2] / clip[3], expected_ndc, atol=1e-8)

    def test_bounds_intersect_matches_dense_sampling(self):
        rng = np.random.default_rng(703)
        samples = np.linspace(0, 1, 4001)
        checked = 0
        for _ in range(600):
            corners = rng.uniform(-1, 1, (8, 3))
            low, high = corners.min(axis=0), corners.max(axis=0)
            origin = rng.uniform(-3, 3, 3)
            direction = rng.normal(size=3)
            direction[rng.random(3) < 0.2] = 0.0
            if not direction.any():
                direction[0] = 1.0
            direction /= np.linalg.norm(direction)
            distance = float(rng.uniform(0.5, 8))
            points = origin + np.outer(samples * distance, direction)
            margin = distance / 4000
            loose = ((points >= low - margin) & (points <= high + margin)).all(axis=1).any()
            strict = ((points > low + margin) & (points < high - margin)).all(axis=1).any()
            result = surface_ray.bounds_intersect(origin.tolist(), direction.tolist(), distance,
                                                  corners.tolist())
            if strict or not loose:
                checked += 1
                self.assertEqual(result, bool(strict), (origin, direction, distance, low, high))
        self.assertGreater(checked, 550)
        box = [[0, 0, 0], [1, 1, 1]]
        self.assertTrue(surface_ray.bounds_intersect([0., 0.5, -1.], [0., 0., 1.], 2., box))
        self.assertTrue(surface_ray.bounds_intersect([-1., 1., 1.], [1., 0., 0.], 1., box))
        self.assertFalse(surface_ray.bounds_intersect([-1., 1.0001, 0.5], [1., 0., 0.], 5., box))
        self.assertFalse(surface_ray.bounds_intersect([-2., 0.5, 0.5], [1., 0., 0.], 0.99, box))
        self.assertFalse(surface_ray.bounds_intersect([2., 0.5, 0.5], [1., 0., 0.], 5., box))


class BarycentricAndGeometryOracle(unittest.TestCase):
    def test_barycentric_factors_match_normal_augmented_lstsq(self):
        rng = np.random.default_rng(801)
        for scale in (1e-5, 1.0, 1e5):
            for _ in range(100):
                triangle = rng.normal(size=(3, 3)) * scale + rng.normal(size=3) * scale * 10
                point = triangle.T @ rng.dirichlet([1, 1, 1]) + rng.normal(size=3) * scale
                edges = np.column_stack([triangle[1] - triangle[0], triangle[2] - triangle[0]])
                normal = np.cross(edges[:, 0], edges[:, 1])
                solution, *_ = lstsq(np.column_stack([edges, normal / np.linalg.norm(normal)]),
                                     point - triangle[0])
                expected = [1 - solution[0] - solution[1], solution[0], solution[1]]
                with self.subTest(scale=scale):
                    np.testing.assert_allclose(skin_projection.barycentric_factors(point, triangle),
                                               expected, atol=1e-8)
        with self.assertRaises(ValueError):
            skin_projection.barycentric_factors([0, 0, 0], [[0, 0, 0], [1, 1, 1], [2, 2, 2]])
        corner = skin_projection.barycentric_factors([2, 0, 0], [[0, 0, 0], [2, 0, 0], [0, 2, 0]])
        np.testing.assert_allclose(corner, [0, 1, 0], atol=1e-15)

    def test_zero_area_rule_matches_triangulated_area(self):
        rng = np.random.default_rng(802)
        threshold = 0.5e-12  # |Newell normal|^2 <= 1e-24 means vector area <= 5e-13.
        checked = 0
        for _ in range(300):
            sides = int(rng.integers(3, 12))
            angles = np.sort(rng.uniform(0, 2 * np.pi, sides))
            radius = 10.0 ** rng.uniform(-8, 3)
            flat = np.column_stack([np.cos(angles), np.sin(angles), np.zeros(sides)]) * radius
            rotation = np.linalg.qr(rng.normal(size=(3, 3)))[0]
            offset = rng.normal(size=3) * 10.0 ** rng.uniform(0, 5)
            polygon = flat @ rotation.T + offset
            fan = polygon[1:-1] - polygon[0], polygon[2:] - polygon[0]
            area = float(np.linalg.norm(np.cross(*fan), axis=1).sum() / 2)
            if 1e-2 * threshold <= area <= 1e2 * threshold:
                continue
            checked += 1
            vertices = [tuple(float(v) for v in p) for p in polygon]
            face = list(range(sides))
            with self.subTest(area=area, sides=sides):
                if area > 1e2 * threshold:
                    geometry.validate_mesh(vertices, [face])
                elif area < 1e-2 * threshold:
                    with self.assertRaisesRegex(ValueError, 'zero area'):
                        geometry.validate_mesh(vertices, [face])
        self.assertGreater(checked, 200)
        first_three_collinear = [(0., 0., 0.), (1., 0., 0.), (2., 0., 0.), (1., 1., 0.)]
        geometry.validate_mesh(first_three_collinear, [[0, 1, 2, 3]])
        with self.assertRaisesRegex(ValueError, 'zero area'):
            geometry.validate_mesh(first_three_collinear, [[0, 1, 2]])


class UdimCoverageOracle(unittest.TestCase):
    @staticmethod
    def oracle_tiles(triangle):
        """Find positive-area intersections by exact projections on edge normals."""
        points = [(Fraction(float(u)), Fraction(float(v))) for u, v in triangle]
        (au, av), (bu, bv), (cu, cv) = points
        if (bu - au) * (cv - av) == (bv - av) * (cu - au):
            return []

        axes = [(1, 0), (0, 1)]
        for (u0, v0), (u1, v1) in zip(points, points[1:] + points[:1]):
            axes.append((v0 - v1, u1 - u0))
        projections = []
        for du, dv in axes:
            projected = [du * u + dv * v for u, v in points]
            projections.append((du, dv, min(projected), max(projected)))

        tiles = []
        for v in range(4):
            for u in range(10):
                for du, dv, triangle_min, triangle_max in projections:
                    origin = du * u + dv * v
                    tile_min = origin + min(0, du) + min(0, dv)
                    tile_max = origin + max(0, du) + max(0, dv)
                    # Require strict overlap so edge and vertex contact contribute no area.
                    if triangle_max <= tile_min or tile_max <= triangle_min:
                        break
                else:
                    tiles.append(1001 + u + 10 * v)
        return tiles

    def test_hand_built_required_tiles(self):
        cases = [
            ([[0.2, 0.2], [0.8, 0.2], [0.2, 0.8]], [1001]),
            ([[0.5, 0.2], [1.5, 0.2], [0.5, 0.8]], [1001, 1002]),
            ([[0.25, 0.25], [1.0000000005, 0.25], [1.0000000005, 0.75]], [1001, 1002]),
            ([[0.2, 0.2], [1.0, 0.5], [0.2, 0.8]], [1001]),
            ([[1.0, 0.1], [1.0, 0.9], [0.3, 0.5]], [1001]),
            ([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], [1001]),
            # Use exactly representable coordinates for contact at the tile corner (1, 1).
            ([[0.25, 0.25], [1.75, 0.25], [0.25, 1.75]], [1001, 1002, 1011]),
            ([[1.0, 1.0], [1.5, 1.2], [1.2, 1.6]], [1012]),
            ([[0.5, 1.5], [3.5, 1.5], [2.0, 2.5]], [1011, 1012, 1013, 1014, 1022, 1023]),
            ([[9.2, 0.2], [9.8, 0.2], [9.5, 0.8]], [1010]),
            ([[0.5, 0.5], [2.5, 0.5], [0.5, 0.50001]], [1001, 1002, 1003]),
        ]
        for triangle, expected in cases:
            with self.subTest(triangle=triangle):
                self.assertEqual(self.oracle_tiles(triangle), expected)
                result = udim_coverage.analyze([triangle], [1001, 1002, 1003, 1010, 1011, 1012,
                                                            1013, 1014, 1022, 1023])
                self.assertEqual(result['required_tiles'], expected)
                self.assertTrue(result['passed'])

    def test_random_triangles_match_separating_axis_oracle(self):
        rng = np.random.default_rng(901)
        for _ in range(120):
            triangle = rng.uniform(0, 1, (1, 2)) * [8, 3] + rng.uniform(-1.2, 1.2, (3, 2))
            triangle = np.clip(triangle, [0, 0], [10, 4])
            if hull_area(triangle) == 0:
                continue
            with self.subTest(triangle=triangle.tolist()):
                result = udim_coverage.analyze([triangle.tolist()], list(range(1001, 1041)))
                self.assertEqual(result['required_tiles'], self.oracle_tiles(triangle))

    def test_missing_outside_and_degenerate(self):
        result = udim_coverage.analyze([[[0.5, 0.2], [1.5, 0.2], [0.5, 0.8]]], [1001])
        self.assertEqual(result['missing_tiles'], [1002])
        self.assertFalse(result['passed'])
        result = udim_coverage.analyze([[[9.5, 0.2], [10.5, 0.2], [9.5, 0.8]]], [1010])
        self.assertEqual(result['required_tiles'], [1010])
        self.assertEqual(result['outside_domain_triangles'], 1)
        degenerate = [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]
        self.assertEqual(self.oracle_tiles(degenerate), [])
        result = udim_coverage.analyze([degenerate], [1001])
        self.assertEqual(result['degenerate_triangles'], 1)
        self.assertEqual(result['required_tiles'], [])


if __name__ == '__main__':
    unittest.main()
