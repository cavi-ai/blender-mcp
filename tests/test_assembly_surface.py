"""Collection assembly uses distinct operations rather than silently flattening roots."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class AssemblySurfaceTests(unittest.TestCase):
    def test_instance_append_and_assembly_export_use_explicit_operations(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'path': '/w/kit.blend', 'sha256': 'a'*64}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.asset_library('append', 'kit.blend', names=['Kit'],
                expected_sha256='a'*64, instance_collections=True, lease_id='L'))
            asyncio.run(server.asset_io('export', 'kit.glb', names=['Kit_A', 'Kit_B'], assembly=True, lease_id='L'))
        self.assertEqual(calls[0][1]['operation'], 'append_asset_library_instances')
        self.assertEqual(calls[1], ('owned_edit', {'operation': 'export_assembly', 'params': {
            'path': 'kit.glb', 'names': ['Kit_A', 'Kit_B'], 'axis': None, 'textures': False, 'lease_id': 'L'}}))

    def test_instance_mode_only_accepts_collection_roots(self):
        with self.assertRaisesRegex(ValueError, 'collections'):
            asyncio.run(server.asset_library('append', 'kit.blend', kind='objects', names=['Kit'],
                expected_sha256='a'*64, instance_collections=True, lease_id='L'))

    def test_assembly_export_rejects_animation_options(self):
        with self.assertRaisesRegex(ValueError, 'animations'):
            asyncio.run(server.asset_io('export', 'kit.fbx', names=['Kit'], assembly=True, animations=True, lease_id='L'))
