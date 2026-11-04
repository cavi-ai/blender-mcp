"""Collection definition controls retain explicit scene-instance scope."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class InstanceControlsSurfaceTests(unittest.TestCase):
    def test_definition_inspection_and_controls_use_scoped_operations(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'name': 'Fence', 'modifiers': []}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.scene_info(name='Kit', definition=True, offset=2, limit=3))
            asyncio.run(server.geometry_nodes('inspect', 'Fence', instance='Kit'))
            asyncio.run(server.geometry_nodes('set_inputs', 'Fence', instance='Kit',
                modifier='Generator', inputs={'Socket_1': 5}, lease_id='L'))
        self.assertEqual(calls[0], ('inspect_collection_instance', {'name': 'Kit', 'offset': 2, 'limit': 3}))
        self.assertEqual(calls[1], ('inspect_instance_geometry_nodes', {'name': 'Fence', 'modifier': None, 'instance': 'Kit'}))
        self.assertEqual(calls[2], ('owned_edit', {'operation': 'set_instance_geometry_inputs', 'params': {
            'name': 'Fence', 'modifier': 'Generator', 'instance': 'Kit',
            'inputs': {'Socket_1': 5}, 'attributes': {}, 'lease_id': 'L'}}))

    def test_definition_requires_a_scene_instance_name(self):
        with self.assertRaisesRegex(ValueError, 'name'):
            asyncio.run(server.scene_info(definition=True))

    def test_snapshot_does_not_infer_an_internal_objects_placement(self):
        with self.assertRaisesRegex(ValueError, 'instance'):
            asyncio.run(server.geometry_nodes('bake_copy', 'Fence', instance='Kit', new_name='Fence_LOD0', lease_id='L'))
