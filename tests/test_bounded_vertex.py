"""Face-bounded proportional edit contracts."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server, vertex_edit


class BoundedVertexTests(unittest.TestCase):
    def test_face_graph_pins_open_and_vertex_only_shared_boundaries(self):
        faces = [(0, 1, 4, 3), (1, 2, 5, 4), (3, 4, 7, 6), (4, 5, 8, 7), (4, 9, 10)]
        edges, pinned, region = vertex_edit.bounded_face_graph(faces, [0, 1, 2, 3], 11)
        self.assertEqual(region, set(range(9)))
        self.assertEqual(set(pinned), set(range(9)))
        self.assertNotIn((4, 9), edges)
        _, pinned, _ = vertex_edit.bounded_face_graph(faces[:-1], [0, 1, 2, 3], 9)
        self.assertEqual(set(pinned), set(range(9)) - {4})

    def test_influence_cannot_cross_a_pinned_vertex(self):
        faces = [(0, 1, 4, 3), (1, 2, 5, 4), (3, 4, 7, 6), (4, 5, 8, 7),
                 (8, 9, 12, 11), (9, 10, 13, 12), (11, 12, 15, 14), (12, 13, 16, 15)]
        edges, pinned, _ = vertex_edit.bounded_face_graph(faces, list(range(8)), 17)
        allowed = [edge for edge in edges if not set(edge) & set(pinned)]
        positions = [(float(i), 0., 0.) for i in range(17)]
        influence = dict(vertex_edit.geodesic_weights(positions, allowed, [4], 100))
        self.assertIn(4, influence)
        self.assertNotIn(12, influence)

    def test_bounded_move_contract(self):
        calls = []
        def call(op, params):
            calls.append((op, params))
            return {}
        base = {'action': 'move_vertices', 'name': 'Mesh', 'vertex_indices': [4], 'offset': [0, 0, .01],
                'face_indices': [0, 1, 2, 3], 'amount': .08, 'expected_mesh_sha256': 'a'*64,
                'lease_id': 'lease'}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.mesh_edit(**base))
            for override in ({'amount': None}, {'expected_mesh_sha256': None},
                             {'symmetry_axis': 'X', 'symmetry_tolerance_m': .01},
                             {'face_indices': [0, 0]}):
                with self.subTest(override=override), self.assertRaises(ValueError):
                    asyncio.run(server.mesh_edit(**{**base, **override}))
        self.assertEqual(calls[0][1]['params']['face_indices'], [0, 1, 2, 3])
