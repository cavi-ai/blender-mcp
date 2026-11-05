"""Analytic source-UV coverage cannot pass missing tiles or incomplete work."""

import importlib
import importlib.util
import unittest

QUAD = [[(0,0),(2,0),(2,2)], [(0,0),(2,2),(0,2)]]


class UdimCoverageTests(unittest.TestCase):
    def check_uvs(self, triangles=QUAD, tiles=(1001,1002,1011,1012), budget=100000):
        self.assertIsNotNone(importlib.util.find_spec('cavi_blender_mcp.udim_coverage'))
        return importlib.import_module('cavi_blender_mcp.udim_coverage').analyze(triangles, list(tiles), budget)

    def test_missing_tile_and_complete_repair(self):
        failed = self.check_uvs(tiles=(1001,1002,1011))
        self.assertEqual(failed['required_tiles'], [1001,1002,1011,1012])
        self.assertEqual(failed['missing_tiles'], [1012])
        self.assertTrue(failed['complete'])
        self.assertFalse(failed['passed'])
        self.assertTrue(self.check_uvs()['passed'])

    def test_boundary_contacts_do_not_request_neighboring_tiles(self):
        result = self.check_uvs([[(0,0),(1,0),(0,1)]])
        self.assertEqual(result['required_tiles'], [1001])
        self.assertEqual(result['unused_tiles'], [1002,1011,1012])
        self.assertTrue(result['passed'])

    def test_enclosed_cells_without_vertices_and_winding(self):
        triangle = [[(0,0),(3,0),(0,3)]]
        expected = [1001,1002,1003,1011,1012,1021]
        result = self.check_uvs(triangle, expected)
        self.assertEqual(result['required_tiles'], expected)
        reverse = self.check_uvs([list(reversed(triangle[0]))], expected)
        self.assertEqual(reverse['required_tiles'], expected)
        self.assertTrue(reverse['passed'])

    def test_invalid_uvs_do_not_pass(self):
        result = self.check_uvs([[(0,0),(0,0),(0,0)],[(float('nan'),0),(1,0),(0,1)],
                                [(-.1,.1),(.2,.1),(.2,.3)],[(10,.1),(11,.1),(10,.9)]])
        self.assertEqual(result['degenerate_triangles'], 1)
        self.assertEqual(result['nonfinite_triangles'], 1)
        self.assertEqual(result['outside_domain_triangles'], 2)
        self.assertFalse(result['passed'])

    def test_budget_cannot_claim_unused_tiles_or_success(self):
        result = self.check_uvs(budget=1)
        self.assertFalse(result['complete'])
        self.assertFalse(result['passed'])
        self.assertIsNone(result['unused_tiles'])
        self.assertEqual(result['candidate_comparisons'], 1)
        self.assertTrue(self.check_uvs(budget=8)['complete'])
        huge = self.check_uvs([[ (0,0), (1,0), (0,1e20)]], budget=1)
        self.assertFalse(huge['complete'])
        self.assertEqual(huge['candidate_comparisons'], 1)

    def test_entirely_outside_huge_bounds_do_not_loop_over_empty_columns(self):
        result = self.check_uvs([[(11,0),(12,0),(11,1e20)]], budget=1)
        self.assertTrue(result['complete'])
        self.assertFalse(result['passed'])
        self.assertEqual(result['candidate_comparisons'], 0)

    def test_unavailable_native_tiles_cannot_pass(self):
        self.check_uvs()
        from cavi_blender_mcp.udim_coverage import analyze
        result = analyze(QUAD, [1001,1002,1011,1012], unavailable_tiles=[1012])
        self.assertEqual(result['unavailable_tiles'], [1012])
        self.assertFalse(result['passed'])
        self.assertTrue(any(e['kind'] == 'unavailable_tile' for e in result['examples']))

    def test_reports_are_bounded_without_losing_counts(self):
        result = self.check_uvs([[(0,0),(1,0),(0,2005)]], tiles=(), budget=3000)
        self.assertTrue(result['complete'])
        self.assertGreater(result['required_tile_count'], 1000)
        self.assertEqual(len(result['required_tiles']), 1000)
        self.assertTrue(result['required_tiles_truncated'])
        self.assertGreater(result['missing_tile_count'], 1000)
        self.assertFalse(result['passed'])
