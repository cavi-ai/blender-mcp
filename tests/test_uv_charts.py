"""Source charts retain their face identity across triangle ordering and UV cuts."""
import unittest

from cavi_blender_mcp import uv_layout


class FaceChartTests(unittest.TestCase):
    def membership(self, triangles, vertices, faces):
        function = getattr(uv_layout, 'face_charts', None)
        self.assertIsNotNone(function, 'UV inspection must expose source-face chart membership')
        return function(triangles, vertices, faces)

    def test_continuous_faces_join_but_disconnected_stacks_do_not(self):
        triangles = [[(0, 0), (1, 0), (0, 1)], [(1, 0), (1, 1), (0, 1)],
                     [(0, 0), (1, 0), (0, 1)]]
        vertices = [[0, 1, 2], [1, 3, 2], [4, 5, 6]]
        self.assertEqual(self.membership(triangles, vertices, [7, 9, 12]), {7: 7, 9: 7, 12: 12})
        self.assertEqual(self.membership(triangles[::-1], vertices[::-1], [12, 9, 7]),
                         {7: 7, 9: 7, 12: 12})

    def test_a_uv_cut_splits_shared_geometry_and_quad_diagonals_remain_one_face(self):
        triangles = [[(0, 0), (1, 0), (0, 1)], [(1, 0), (1, 1), (0, 1)],
                     [(2, 0), (2, 1), (1, 1)]]
        vertices = [[0, 1, 2], [1, 3, 2], [1, 4, 3]]
        self.assertEqual(self.membership(triangles, vertices, [3, 3, 8]), {3: 3, 8: 8})

    def test_degenerate_uvs_retain_topological_membership_without_claiming_quality(self):
        self.assertEqual(self.membership([[(0, 0)]*3]*2, [[0, 1, 2], [1, 3, 2]], [0, 1]),
                         {0: 0, 1: 0})

    def test_nonfinite_coordinates_and_mismatched_source_faces_are_rejected(self):
        for triangles, vertices, faces in (([[(float('nan'), 0), (1, 0), (0, 1)]], [[0, 1, 2]], [0]),
                ([[(0, 0), (1, 0), (0, 1)]], [[0, 1, 2]], [])):
            with self.subTest(faces=faces), self.assertRaises(ValueError):
                self.membership(triangles, vertices, faces)
