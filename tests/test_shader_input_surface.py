"""Native shader input operations preserve the existing material assignment route."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class ShaderInputSurfaceTests(unittest.TestCase):
    def test_inspection_is_lease_free_and_edits_keep_ownership(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'material': 'ArtistFinish', 'nodes': []}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.assign_material(material_name='ArtistFinish', action='inspect',
                group_path=['Finish Controls'], limit=3, offset=2))
            asyncio.run(server.assign_material(material_name='ArtistFinish', action='set_inputs',
                node='Hero Surface', group_path=['Finish Controls'], inputs={'Roughness': .2}, lease_id='L'))
        self.assertEqual(calls[0], ('inspect_material_nodes', {'material_name': 'ArtistFinish',
            'group_path': ['Finish Controls'], 'node': None, 'limit': 3, 'offset': 2}))
        self.assertEqual(calls[1], ('owned_edit', {'operation': 'set_material_inputs', 'params': {
            'material_name': 'ArtistFinish', 'group_path': ['Finish Controls'], 'node': 'Hero Surface',
            'inputs': {'Roughness': .2}, 'lease_id': 'L'}}))

    def test_action_parameters_are_checked_before_native_dispatch(self):
        for options in [{'action': 'set_inputs', 'inputs': {'Roughness': .2}},
                        {'action': 'set_inputs', 'node': 'Surface', 'inputs': {}},
                        {'action': 'inspect', 'roughness': .2}, {'action': 'assign', 'node': 'Surface'}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                asyncio.run(server.assign_material(material_name='ArtistFinish', **options))
