"""Face extraction is explicit, bounded and routed through the ownership envelope."""
import asyncio
import unittest
from unittest.mock import patch

from cavi_blender_mcp import server
from cavi_blender_mcp.operations import LEASE_FREE, OPERATIONS


class ExtractFacesSurfaceTests(unittest.TestCase):
    def test_selection_routes_to_owned_extraction(self):
        calls = []
        with patch.object(server, 'call', lambda op, **args: calls.append((op, args)) or {}):
            asyncio.run(server.mesh_edit('extract_faces', 'Surface', new_name='Patch',
                face_indices=[3, 1], lease_id='owner'))
        self.assertEqual(calls, [('extract_faces', {'name': 'Surface', 'new_name': 'Patch',
            'face_indices': [3, 1], 'lease_id': 'owner'})])
        self.assertIn('extract_faces', OPERATIONS)
        self.assertNotIn('extract_faces', LEASE_FREE)

    def test_missing_unrelated_and_duplicate_parameters_fail_before_bridge(self):
        calls = []
        with patch.object(server, 'call', lambda *a, **k: calls.append((a, k))):
            for args in [{'new_name': 'Patch'}, {'face_indices': [0]},
                         {'new_name': 'Patch', 'face_indices': [0, 0]},
                         {'new_name': 'Patch', 'face_indices': [0], 'by': 'materials'}]:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    asyncio.run(server.mesh_edit('extract_faces', 'Surface', **args))
            with self.assertRaises(ValueError):
                asyncio.run(server.mesh_edit('separate', 'Surface', face_indices=[0]))
        self.assertEqual(calls, [])

    def test_protocol_rejects_invalid_indices_before_bridge(self):
        async def invoke(faces):
            return await server.mcp.call_tool('mesh_edit', {'action': 'extract_faces',
                'name': 'Surface', 'new_name': 'Patch', 'face_indices': faces})
        with patch.object(server, 'call') as call:
            for faces in [[], [-1], [True], [1.5], ['1'], [0] * 20001]:
                with self.subTest(faces=str(faces)[:35]), self.assertRaisesRegex(Exception, '[Vv]alidat'):
                    asyncio.run(invoke(faces))
            call.assert_not_called()
