"""Topology defect measurements on hand-built mesh arrays, independent of Blender."""
import unittest

import numpy as np

from cavi_blender_mcp.mesh_topology import COINCIDENT_DISTANCE_M, report

CUBE = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
CUBE_FACES = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 4, 7, 3), (1, 2, 6, 5)]
SQUARE = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
UPRIGHT = [(.25, .5, -.5), (.75, .5, -.5), (.75, .5, .5), (.25, .5, .5)]
COUNTS = ("inconsistent_winding_edges", "coincident_vertex_pairs", "sliver_triangles",
          "self_intersecting_face_pairs")
EXAMPLES = ("inconsistent_winding_edge_examples", "coincident_vertex_pair_examples",
            "sliver_triangle_examples", "self_intersecting_face_pair_examples")


def build(points, faces, zero_area=()):
    """Blender-shaped arrays: one edge per vertex pair, fan triangles, every triangle pair a candidate."""
    edges, loop_edges = {}, []
    for face in faces:
        for k, vertex in enumerate(face):
            key = tuple(sorted((vertex, face[(k + 1) % len(face)])))
            loop_edges.append(edges.setdefault(key, len(edges)))
    totals = [len(face) for face in faces]
    triangles, owners = [], []
    for index, face in enumerate(faces):
        for k in range(1, len(face) - 1):
            triangles.append((face[0], face[k], face[k + 1]))
            owners.append(index)
    excluded = np.zeros(len(faces), bool)
    excluded[list(zero_area)] = True
    candidates = np.stack(np.triu_indices(len(triangles), 1), 1)
    result = report(points, [v for face in faces for v in face], loop_edges,
                    np.cumsum([0] + totals)[:-1], totals, len(edges), triangles, owners,
                    excluded, candidates)
    return result, edges


class MeshTopologyTests(unittest.TestCase):
    def test_clean_controls_report_zero(self):
        apart = [(x + 5, y, z) for x, y, z in UPRIGHT]
        for points, faces in ((CUBE, CUBE_FACES),
                              ([(0, 0, 0), (1, 0, 0), (.5, .866, 0)], [(0, 1, 2)]),
                              (SQUARE + apart, [(0, 1, 2, 3), (4, 5, 6, 7)])):
            with self.subTest(faces=faces):
                result, _ = build(points, faces)
                self.assertEqual([result[name] for name in COUNTS], [0, 0, 0, 0])
                self.assertEqual([result[name] for name in EXAMPLES], [[], [], [], []])

    def test_a_flipped_cube_face_reports_its_four_edges(self):
        faces = list(CUBE_FACES)
        faces[1] = (7, 6, 5, 4)
        result, edges = build(CUBE, faces)
        self.assertEqual(result["inconsistent_winding_edges"], 4)
        expected = sorted(edges[key] for key in ((4, 5), (5, 6), (6, 7), (4, 7)))
        self.assertEqual(result["inconsistent_winding_edge_examples"], expected)
        self.assertEqual(result["self_intersecting_face_pairs"], 0)

    def test_duplicated_vertices_within_tolerance_are_pairs_and_contacts_do_not_cross(self):
        near = COINCIDENT_DISTANCE_M / 2
        points = SQUARE + [(0, 0, 0), (1 + near, 0, 0), (1, 0, 1), (0, 0, 1)]
        result, _ = build(points, [(0, 1, 2, 3), (4, 5, 6, 7)])
        self.assertEqual(result["coincident_vertex_pairs"], 2)
        self.assertEqual(result["coincident_vertex_pair_examples"], [[0, 4], [1, 5]])
        self.assertEqual(result["self_intersecting_face_pairs"], 0)
        far = SQUARE + [(0, 0, 2 * COINCIDENT_DISTANCE_M), (1, 0, 2 * COINCIDENT_DISTANCE_M),
                        (1, 0, 1), (0, 0, 1)]
        self.assertEqual(build(far, [(0, 1, 2, 3), (4, 5, 6, 7)])[0]["coincident_vertex_pairs"], 0)

    def test_coincident_pairs_span_cell_boundaries_and_stay_bounded(self):
        edge = COINCIDENT_DISTANCE_M
        points = [(3, 3, 3), (5, 0, 0), (3, 3, 3), (5 + edge / 2, 0, 0), (5, 0, 0),
                  (.99 * edge,) * 3, (1.01 * edge,) * 3, (-1e-6, 1e-6, -1e-6), (1e-6, -1e-6, 1e-6)]
        result, _ = build(points, [])
        self.assertEqual(result["coincident_vertex_pairs"], 6)
        self.assertEqual(result["coincident_vertex_pair_examples"],
                         [[0, 2], [1, 3], [1, 4], [3, 4], [5, 6], [7, 8]])
        cluster, _ = build([(2, 3, 4)] * 2000, [])
        self.assertEqual(cluster["coincident_vertex_pairs"], 2000 * 1999 // 2)
        self.assertEqual(cluster["coincident_vertex_pair_examples"], [[0, j] for j in range(1, 33)])
        self.assertTrue(cluster["coincident_vertex_pairs_complete"])

    def test_dense_coincidence_search_preserves_other_topology_counts(self):
        needle = [(0, 0, 0), (1, 0, 0), (.5, .005, 0)]
        dense = [(i * 1e-8, 0, 0) for i in range(1500)]
        result, _ = build(needle + dense, [(0, 1, 2)])
        self.assertFalse(result["coincident_vertex_pairs_complete"])
        self.assertIsNone(result["coincident_vertex_pairs"])
        self.assertEqual(result["coincident_vertex_pair_examples"], [])
        self.assertEqual(result["sliver_triangles"], 1)
        self.assertEqual(result["self_intersecting_face_pairs"], 0)

    def test_a_needle_triangle_is_a_sliver_unless_its_face_has_zero_area(self):
        needle = [(0, 0, 0), (1, 0, 0), (.5, .005, 0)]
        result, _ = build(needle, [(0, 1, 2)])
        self.assertEqual(result["sliver_triangles"], 1)
        self.assertEqual(result["sliver_triangle_examples"], [[0, 0]])
        self.assertEqual(build(needle, [(0, 1, 2)], zero_area=[0])[0]["sliver_triangles"], 0)

    def test_crossing_quads_report_one_face_pair_unless_they_share_a_vertex(self):
        result, _ = build(SQUARE + UPRIGHT, [(0, 1, 2, 3), (4, 5, 6, 7)])
        self.assertEqual(result["self_intersecting_face_pairs"], 1)
        self.assertEqual(result["self_intersecting_face_pair_examples"], [[0, 1]])
        fin = SQUARE + [(.6, .4, -.5), (.6, .4, .5), (0, 0, 0)]
        separate, _ = build(fin, [(0, 1, 2, 3), (6, 4, 5)])
        self.assertEqual(separate["self_intersecting_face_pair_examples"], [[0, 1]])
        shared, _ = build(fin, [(0, 1, 2, 3), (0, 4, 5)])
        self.assertEqual(shared["self_intersecting_face_pairs"], 0)

    def test_triangle_sections_with_matching_endpoints_cross_but_point_contact_does_not(self):
        left = [(0, -1, 0), (0, 1, 0), (2, 1, 0)]
        right = [(0, 0, -1), (0, 0, 1), (2, 0, 1)]
        faces = [(0, 1, 2), (5, 4, 3)]
        crossing, _ = build(left + right, faces)
        self.assertEqual(crossing["self_intersecting_face_pair_examples"], [[0, 1]])
        contact, _ = build(left + [(x + 1, y, z) for x, y, z in right], faces)
        self.assertEqual(contact["self_intersecting_face_pairs"], 0)


if __name__ == "__main__":
    unittest.main()
