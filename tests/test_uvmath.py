import random
import unittest

from cavi_blender_mcp.mapping import measure_triangle, summarize
from cavi_blender_mcp.uvmath import coverage, density, overlap

QUAD = [[(0, 0), (0.5, 0), (0.5, 0.5)], [(0, 0), (0.5, 0.5), (0, 0.5)]]


class UVMathTests(unittest.TestCase):
    def test_adjacent_triangles_do_not_overlap(self):
        result = overlap(QUAD, 64)
        self.assertEqual(result["overlap_ratio"], 0)
        self.assertEqual(result["covered_cells"], 32 * 32 - 32)

    def test_stacked_islands_overlap_fully(self):
        result = overlap(QUAD + QUAD, 32)
        self.assertEqual(result["overlap_ratio"], 1)

    def test_partial_overlap_and_flipped_winding(self):
        shifted = [[(u + 0.25, v) for u, v in reversed(tri)] for tri in QUAD]
        result = overlap(QUAD + shifted, 64)
        self.assertAlmostEqual(result["overlap_ratio"], 1 / 3, delta=0.03)

    def test_outside_and_degenerate_triangles_are_ignored(self):
        counts = coverage([[(2, 2), (3, 2), (3, 3)], [(0, 0), (1, 1), (0.5, 0.5)]], 16)
        self.assertEqual(int(counts.sum()), 0)

    def test_large_triangles_use_banded_rasterization(self):
        counts = coverage([[(0, 0), (1, 0), (0, 1)]], 4096)
        self.assertAlmostEqual(int((counts > 0).sum()) / 4096 ** 2, 0.5, delta=0.001)

    def test_density_matches_per_triangle_summary(self):
        rng = random.Random(4)
        points, uvs, samples = [], [], []
        for _ in range(50):
            tri = [tuple(rng.uniform(-2, 2) for _ in range(3)) for _ in range(3)]
            uv = [tuple(rng.uniform(0, 1) for _ in range(2)) for _ in range(3)]
            points.append(tri)
            uvs.append(uv)
            samples.append(measure_triangle(tri, uv, (1024, 512)))
        expected = summarize(samples)["density_area_weighted"]
        self.assertAlmostEqual(density(points, uvs, (1024, 512)), expected, places=6)

    def test_resolution_is_bounded(self):
        with self.assertRaises(ValueError):
            coverage(QUAD, 8192)
