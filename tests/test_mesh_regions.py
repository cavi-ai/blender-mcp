import asyncio
import unittest
from unittest.mock import patch

from cavi_blender_mcp import server
from cavi_blender_mcp.operations import LEASE_FREE


class MeshRegionSurfaceTests(unittest.TestCase):
    def test_face_pages_are_read_only_and_reuse_pagination(self):
        with patch.object(server, 'call', return_value={}) as call:
            asyncio.run(server.scene_info(name='Wall', faces=True, limit=8, offset=16))
        self.assertEqual(call.call_args.args, ('inspect_mesh_faces',))
        self.assertEqual(call.call_args.kwargs, {'name': 'Wall', 'limit': 8, 'offset': 16})
        self.assertIn('inspect_mesh_faces', LEASE_FREE)

    def test_extrusion_routes_exact_selection_and_optional_geometry_pin(self):
        with patch.object(server, 'call', return_value={}) as call:
            asyncio.run(server.mesh_edit('extrude_faces', 'Wall', face_indices=[1, 2],
                offset=(0, 0, .25), expected_mesh_sha256='a' * 64, lease_id='owner'))
        self.assertEqual(call.call_args.args, ('extrude_faces',))
        self.assertEqual(call.call_args.kwargs, {'name': 'Wall', 'face_indices': [1, 2],
            'offset': (0, 0, .25), 'expected_mesh_sha256': 'a' * 64, 'lease_id': 'owner'})
        self.assertNotIn('extrude_faces', LEASE_FREE)

    def test_modes_and_unused_inputs_reject_before_native_dispatch(self):
        cases = [server.scene_info(faces=True), server.scene_info('Wall', faces=True, definition=True),
                 server.mesh_edit('extrude_faces', 'Wall', face_indices=[1], offset=(0, 0, 0)),
                 server.mesh_edit('extrude_faces', 'Wall', face_indices=[1, 1], offset=(0, 0, 1)),
                 server.mesh_edit('unwrap', 'Wall', expected_mesh_sha256='a' * 64)]
        with patch.object(server, 'call') as call:
            for case in cases:
                with self.subTest(case=case), self.assertRaises(ValueError):
                    asyncio.run(case)
            call.assert_not_called()

    def test_native_parameter_validation_is_independent_of_bpy(self):
        from cavi_blender_mcp.mesh_regions import selection

        faces, offset = selection([1, 2], [0, 0, .25], 3, None, 'a' * 64)
        self.assertEqual(faces, [1, 2])
        self.assertEqual(offset, [0., 0., .25])
        for faces, offset, expected in [([], [0, 0, 1], None), ([True], [0, 0, 1], None),
                ([3], [0, 0, 1], None), ([1, 1], [0, 0, 1], None), ([1], [0, 0, 0], None),
                ([1], [True, 0, 1], None), ([1], [0, 0, float('nan')], None),
                ([1], [0, 0, 1], 'b' * 64), ([1], [0, 0, 1], 'bad')]:
            with self.subTest(faces=faces, offset=offset, expected=expected), self.assertRaises(ValueError):
                selection(faces, offset, 3, expected, 'a' * 64)
