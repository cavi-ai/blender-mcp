"""Analytic UV preflight regressions, independent of Blender."""
import unittest

from cavi_blender_mcp.uv_layout import analyze

QUAD = [[(.1, .1), (.4, .1), (.4, .4)], [(.1, .1), (.4, .4), (.1, .4)]]
IDS = [[0, 1, 2], [0, 2, 3]]


def check(triangles=QUAD, vertices=IDS, resolution=(100, 100), padding=2, budget=10000):
    return analyze(triangles, vertices, resolution, padding, budget)


class UVLayoutTests(unittest.TestCase):
    def test_shared_diagonal_is_one_chart_without_overlap(self):
        r = check()
        self.assertTrue(r['complete'])
        self.assertTrue(r['unique_tile_ready'])
        self.assertEqual(r['charts'], 1)
        self.assertEqual(r['overlap']['triangle_pairs'], 0)

    def test_stacked_objects_and_reversed_winding_are_detected(self):
        r = check(QUAD + [list(reversed(t)) for t in QUAD],
                  IDS + [[6, 5, 4], [7, 6, 4]])
        self.assertFalse(r['unique_tile_ready'])
        self.assertEqual(r['charts'], 2)
        self.assertEqual(r['overlap']['triangle_pairs'], 2)
        self.assertAlmostEqual(r['overlap']['pairwise_area_pixels2'], 900)

    def test_subpixel_overlap_is_not_missed_by_pixel_centres(self):
        tri = [[(.1001, .1001), (.1002, .1001), (.1001, .1002)]]
        r = check(tri * 2, [[0, 1, 2], [3, 4, 5]])
        self.assertEqual(r['overlap']['triangle_pairs'], 1)
        self.assertGreater(r['overlap']['pairwise_area_pixels2'], 0)

    def test_touching_disconnected_charts_fail_positive_gutter_not_overlap(self):
        r = check(QUAD, [[0, 1, 2], [4, 5, 6]])
        self.assertEqual(r['charts'], 2)
        self.assertEqual(r['overlap']['triangle_pairs'], 0)
        self.assertEqual(r['padding']['triangle_pairs_below_requested'], 1)
        self.assertTrue(check(QUAD, [[0, 1, 2], [4, 5, 6]], padding=0)['unique_tile_ready'])

    def test_connected_fold_is_still_checked_for_overlap(self):
        r = check([QUAD[0], QUAD[0]], [[0, 1, 2], [0, 1, 3]])
        self.assertEqual(r['charts'], 1)
        self.assertEqual(r['overlap']['triangle_pairs'], 1)

    def test_rectangular_texture_measures_actual_pixel_gutter(self):
        tris = [[(.1, .1), (.2, .1), (.2, .2)],
                [(.21, .1), (.31, .1), (.21, .2)]]
        ids = [[0, 1, 2], [3, 4, 5]]
        self.assertEqual(check(tris, ids, (100, 1000))['padding']
                         ['triangle_pairs_below_requested'], 1)
        self.assertEqual(check(tris, ids, (1000, 100))['padding']
                         ['triangle_pairs_below_requested'], 0)

    def test_degenerate_nonfinite_outside_and_border_are_not_clean(self):
        triangles = [[(0, 0), (0, 0), (0, 0)],
                     [(float('nan'), 0), (1, 0), (0, 1)],
                     [(-.1, .1), (.1, .1), (.1, .2)],
                     [(.001, .5), (.1, .5), (.1, .6)]]
        r = check(triangles, [[i * 3 + j for j in range(3)] for i in range(4)])
        self.assertFalse(r['unique_tile_ready'])
        self.assertEqual(r['degenerate_triangles'], 1)
        self.assertEqual(r['nonfinite_triangles'], 1)
        self.assertEqual(r['outside_tile_triangles'], 1)
        self.assertGreater(r['padding']['border_triangles_below_requested'], 0)

    def test_budget_exhaustion_is_incomplete_even_when_nothing_found(self):
        # Many x-overlapping, y-separated triangles exercise broadphase work limits.
        triangles = [[(.1, .1 + i * .1), (.2, .1 + i * .1), (.1, .12 + i * .1)]
                     for i in range(6)]
        r = check(triangles, [[i * 3 + j for j in range(3)] for i in range(6)], budget=1)
        self.assertFalse(r['complete'])
        self.assertFalse(r['unique_tile_ready'])
        self.assertEqual(r['comparisons'], 1)

    def test_exact_budget_is_complete_when_no_work_remains(self):
        self.assertTrue(check(budget=1)['complete'])

    def test_input_order_does_not_change_geometry_findings(self):
        r = check(QUAD * 2, IDS + [[4, 5, 6], [4, 6, 7]])
        s = check(list(reversed(QUAD * 2)), list(reversed(IDS + [[4, 5, 6], [4, 6, 7]])))
        self.assertEqual(r['overlap']['triangle_pairs'], s['overlap']['triangle_pairs'])
        self.assertAlmostEqual(r['overlap']['pairwise_area_pixels2'],
                               s['overlap']['pairwise_area_pixels2'])

    def test_contained_triangle_reports_intersection_not_bounding_box_area(self):
        triangles = [[(.1, .1), (.9, .1), (.1, .9)],
                     [(.2, .2), (.3, .2), (.2, .3)]]
        r = check(triangles, [[0, 1, 2], [3, 4, 5]])
        self.assertAlmostEqual(r['overlap']['pairwise_area_pixels2'], 50)

    def test_seam_with_different_loop_uvs_is_not_connected(self):
        moved = [[(u + .5, v) for u, v in QUAD[1]]]
        r = check([QUAD[0]] + moved)
        self.assertEqual(r['charts'], 2)

    def test_output_examples_are_bounded_without_truncating_counts(self):
        r = check([QUAD[0]] * 10, [[i * 3 + j for j in range(3)] for i in range(10)])
        self.assertEqual(r['overlap']['triangle_pairs'], 45)
        self.assertEqual(len(r['overlap']['examples']), 32)
        self.assertTrue(r['complete'])

    def test_invalid_or_unbounded_arguments_are_rejected(self):
        for kwargs in ({'resolution': (0, 10)}, {'padding': -1}, {'budget': 0},
                       {'vertices': []}, {'resolution': (True, 10)}, {'padding': float('inf')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                check(**kwargs)
