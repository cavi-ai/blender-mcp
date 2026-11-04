"""Procedural input edits use the owner lease; inspection is read-only."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class GeometryNodesSurfaceTests(unittest.TestCase):
    def test_edits_and_snapshot_keep_the_lease(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'name': 'Fence'}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.geometry_nodes('set_inputs', 'Fence', modifier='Generator',
                inputs={'Socket_1': 5}, lease_id='L'))
            asyncio.run(server.geometry_nodes('bake_copy', 'Fence', new_name='Fence_LOD0', lease_id='L'))
        self.assertEqual(calls[0], ('owned_edit', {'operation': 'set_geometry_inputs', 'params': {
            'name': 'Fence', 'modifier': 'Generator', 'inputs': {'Socket_1': 5},
            'attributes': {}, 'lease_id': 'L'}}))
        self.assertEqual(calls[1][1]['params']['lease_id'], 'L')
        self.assertEqual(calls[1][1]['operation'], 'snapshot_geometry')

    def test_inspection_does_not_mutate(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'name': 'Fence', 'modifiers': []}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.geometry_nodes('inspect', 'Fence'))
        self.assertEqual(calls, [('inspect_geometry_nodes', {'name': 'Fence', 'modifier': None})])

    def test_action_parameters_are_not_silently_ignored(self):
        for action, kwargs in [('inspect', {'inputs': {'Socket_1': 5}}),
                               ('bake_copy', {}), ('set_inputs', {'modifier': 'Generator'})]:
            with self.subTest(action=action), self.assertRaises(ValueError):
                asyncio.run(server.geometry_nodes(action, 'Fence', **kwargs))
