"""Native coordinate planning rejects overflow without reducing source precision."""
import unittest

from cavi_blender_mcp import mesh_regions


class VertexEditTests(unittest.TestCase):
    def planner(self):
        from importlib.util import find_spec

        self.assertIsNotNone(find_spec('cavi_blender_mcp.vertex_edit'), 'Vertex translation planning is missing')
        from cavi_blender_mcp.vertex_edit import translated
        return translated

    def test_translation_retains_fractional_shape_deltas(self):
        translate = self.planner()
        basis = translate([(-1, -1, 0)], [.25, .125, .5])
        morph = translate([(-1, -1, .2)], [.25, .125, .5])
        self.assertEqual(basis, [(-.75, -.875, .5)])
        self.assertAlmostEqual(morph[0][2]-basis[0][2], .2, delta=1e-7)

    def test_nonfinite_coordinates_and_float_storage_overflow_are_rejected(self):
        translate = self.planner()
        for point in ((float('nan'), 0, 0), (float('inf'), 0, 0), (4e38, 0, 0)):
            with self.subTest(point=point), self.assertRaises(ValueError):
                translate([point], [.25, 0, 0])

    def test_vertex_selection_rejects_duplicates_stale_geometry_and_bad_indices(self):
        for selected, expected in (([0,0], None), ([3], None), ([-1], None), ([True], None), ([0], 'a'*64)):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                mesh_regions.selection(selected, [.25,0,0], 3, expected, 'b'*64,
                                       field='vertex_indices')
