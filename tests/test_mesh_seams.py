import asyncio
import unittest
from unittest.mock import patch

from cavi_blender_mcp import server
from cavi_blender_mcp.operations import LEASE_FREE


class MeshSeamTests(unittest.TestCase):
    def test_edge_pages_are_read_only_and_reject_ambiguous_page_modes(self):
        with patch.object(server, 'call', return_value={}) as call:
            asyncio.run(server.scene_info('Sleeve', edges=True, limit=8, offset=16))
        self.assertEqual(call.call_args.args, ('inspect_mesh_edges',))
        self.assertEqual(call.call_args.kwargs, {'name': 'Sleeve', 'limit': 8, 'offset': 16})
        self.assertIn('inspect_mesh_edges', LEASE_FREE)
        for args in ({'edges': True}, {'name': 'Sleeve', 'edges': True, 'faces': True},
                     {'name': 'Sleeve', 'edges': True, 'definition': True}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                asyncio.run(server.scene_info(**args))

    def test_seam_edit_requires_a_precise_selection_and_explicit_state(self):
        with patch.object(server, 'call', return_value={}) as call:
            asyncio.run(server.mesh_edit('set_seams', 'Sleeve', edge_indices=[1, 2], seam=False,
                expected_mesh_sha256='a'*64, lease_id='owner'))
        self.assertEqual(call.call_args.args, ('set_seams',))
        self.assertEqual(call.call_args.kwargs, {'name': 'Sleeve', 'edge_indices': [1, 2],
            'seam': False, 'expected_mesh_sha256': 'a'*64, 'lease_id': 'owner'})
        for args in ({'edge_indices': [1]}, {'edge_indices': [1, 1], 'seam': True},
                     {'edge_indices': [-1], 'seam': True}, {'edge_indices': [True], 'seam': True},
                     {'edge_indices': [1], 'seam': True, 'uv_layer': 'UVMap'}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                asyncio.run(server.mesh_edit('set_seams', 'Sleeve', **args))

    def test_projection_options_keep_smart_default_and_reject_unused_angle(self):
        from cavi_blender_mcp.uv_regions import projection

        self.assertEqual(projection(None, None), ('smart', 66))
        for method in ('angle_based', 'conformal', 'minimum_stretch'):
            self.assertEqual(projection(method, None), (method, None))
            with self.subTest(method=method), self.assertRaises(ValueError):
                projection(method, 66)
        for method, angle in [('bad', None), ('smart', 0), ('smart', True), ('smart', float('nan'))]:
            with self.subTest(method=method, angle=angle), self.assertRaises(ValueError):
                projection(method, angle)

    def test_edge_selection_rejects_stale_or_ambiguous_indices(self):
        from cavi_blender_mcp.mesh_regions import indices

        self.assertEqual(indices([1, 2], 3, 'edge_indices'), [1, 2])
        for selected in ([], [1, 1], [True], [-1], [3]):
            with self.subTest(selected=selected), self.assertRaisesRegex(ValueError, 'edge_indices'):
                indices(selected, 3, 'edge_indices')

    def test_seam_projection_routes_without_automatic_fallback(self):
        spec = server.UVRegion(bounds=(.5, 0, 1, 1), texture_resolution=(2048, 1024), margin_px=8)
        with patch.object(server, 'call', return_value={}) as call:
            asyncio.run(server.mesh_edit('unwrap_faces', 'Sleeve', face_indices=[1, 2],
                uv_region=spec, unwrap_method='conformal'))
        self.assertEqual(call.call_args.kwargs['unwrap_method'], 'conformal')
        self.assertIsNone(call.call_args.kwargs['angle_limit_degrees'])
        with self.assertRaisesRegex(ValueError, 'angle_limit_degrees'):
            asyncio.run(server.mesh_edit('unwrap_faces', 'Sleeve', face_indices=[1, 2],
                uv_region=spec, unwrap_method='conformal', angle_limit_degrees=66))
