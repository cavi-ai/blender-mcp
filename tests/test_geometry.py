import unittest

from cavi_blender_mcp.geometry import validate_mesh


class GeometryTests(unittest.TestCase):
    def test_accepts_indexed_quads_without_changing_winding(self):
        vertices = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
        faces = [[0, 1, 2, 3]]
        self.assertEqual(validate_mesh(vertices, faces), (vertices, faces))

    def test_invalid_topology_is_refused_before_creation(self):
        vertices = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
        for faces in ([[0, 1]], [[0, 1, 3]], [[0, 1, 1]], [[0, 1, 2.0]], [[0, True, 2]]):
            with self.subTest(faces=faces), self.assertRaises(ValueError):
                validate_mesh(vertices, faces)
        with self.assertRaises(ValueError):
            validate_mesh([[0, 0, 0], [1, 0, 0], [2, 0, 0]], [[0, 1, 2]])

    def test_nonfinite_or_unbounded_vertices_are_refused(self):
        for value in (float("nan"), float("inf"), 1e7, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_mesh([[value, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]])

    def test_geometry_budgets_are_enforced(self):
        with self.assertRaises(ValueError):
            validate_mesh([[0, 0, 0]] * 10001, [[0, 1, 2]])
        with self.assertRaises(ValueError):
            validate_mesh([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]] * 20001)
