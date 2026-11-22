"""Violation components respect connectivity, region buckets and output bounds."""
import unittest

from cavi_blender_mcp.blender_clearance_patches import summarize


class ClearancePatchTests(unittest.TestCase):
    def test_components_region_split_and_order(self):
        vertices = {0: (-.2, (1,)), 1: (-.1, (1,)), 2: (-.3, (2,)), 4: (-.05, (1,))}
        result = summarize(vertices, [(0, 1, 2), (2, 3, 4)], 5, 5)
        self.assertEqual(result['total_patches'], 3)
        self.assertEqual(result['violating_vertices'], 4)
        self.assertEqual([patch['worst_vertex'] for patch in result['patches']], [2, 0, 4])
        self.assertEqual(result['patches'][1]['vertex_count'], 2)
        self.assertTrue(result['vertex_scan_complete'])

    def test_caps_and_partial_coverage(self):
        vertices = {i: (-float(i+1), ()) for i in range(40)}
        result = summarize(vertices, [], 100, 40)
        self.assertEqual(result['total_patches'], 40)
        self.assertEqual(len(result['patches']), 32)
        self.assertTrue(result['truncated'])
        self.assertFalse(result['vertex_scan_complete'])
        linked = summarize(vertices, [(i, i+1, i+2) for i in range(38)], 40, 40)
        self.assertEqual(linked['patches'][0]['vertex_count'], 40)
        self.assertEqual(len(linked['patches'][0]['seeds']), 8)
        self.assertEqual(linked['patches'][0]['seeds'][0]['vertex_index'], 39)
