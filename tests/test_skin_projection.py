"""Skin coordinates retain precision near triangle edges without relaxing admission."""
import unittest

import numpy as np

from cavi_blender_mcp.skin_projection import barycentric_factors

TRIANGLE = [(0.18260040879249573, 0.025469088926911354, 1.4310777187347412),
            (0.192268505692482, 0.037407442927360535, 1.4130725860595703),
            (0.1784992665052414, 0.02648898772895336, 1.4283682107925415)]
NEAREST = (0.1911902278661728, 0.03655241057276726, 1.4142704010009766)
VERTEX_TRIANGLE = [(0.3108440935611725, -0.015848562121391296, 1.1760691404342651),
                   (0.30041956901550293, -0.018298104405403137, 1.1816051006317139),
                   (0.2994089126586914, -0.01226722914725542, 1.1807605028152466)]


class SkinProjectionTests(unittest.TestCase):
    def test_near_edge_projection_stays_within_existing_tolerance(self):
        actual = barycentric_factors(NEAREST, TRIANGLE)
        np.testing.assert_allclose(actual, [6.019561576975363e-7, .9216892007689,
                                          .07831019727494225], rtol=0, atol=1e-12)
        self.assertTrue(all(-1e-5 <= value <= 1 + 1e-5 for value in actual))

    def test_each_existing_vertex_has_its_analytic_coordinates(self):
        for index, point in enumerate(VERTEX_TRIANGLE):
            with self.subTest(index=index):
                np.testing.assert_allclose(barycentric_factors(point, VERTEX_TRIANGLE),
                                           np.eye(3)[index], rtol=0, atol=1e-12)

    def test_interior_coordinates_are_affine_and_project_off_plane(self):
        triangle = np.array([(1, 2, 3), (3, 2, 3), (1, 5, 3)], dtype=np.float64)
        expected = np.array([.2, .3, .5])
        point = expected @ triangle + [0, 0, .125]
        np.testing.assert_allclose(barycentric_factors(point, triangle), expected,
                                   rtol=0, atol=1e-12)

    def test_outside_points_are_not_clamped_or_made_admissible(self):
        actual = barycentric_factors((-.01, .5, 0), [(0, 0, 0), (1, 0, 0), (0, 1, 0)])
        self.assertLess(actual[1], -1e-5)
        np.testing.assert_allclose(actual, [.51, -.01, .5], rtol=0, atol=1e-12)

    def test_degenerate_nonfinite_and_malformed_inputs_fail_closed(self):
        for triangle, point in [([(0, 0, 0)] * 3, (0, 0, 0)),
                                ([(0, 0, 0), (1, 0, 0), (2, 0, 0)], (0, 0, 0)),
                                (TRIANGLE, (float('nan'), 0, 0)),
                                ([(float('inf'), 0, 0)] * 3, (0, 0, 0)),
                                (TRIANGLE[:2], NEAREST)]:
            with self.subTest(triangle=triangle, point=point), self.assertRaises(ValueError):
                barycentric_factors(point, triangle)
