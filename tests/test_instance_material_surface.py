"""Internal material targets keep explicit ownership and binding modes."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class InstanceMaterialSurfaceTests(unittest.TestCase):
    def test_instance_assignment_uses_a_distinct_owned_operation(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'material': 'Finish', 'objects': ['BaseStone'], 'slot': 0,
                    'updated': False, 'material_users': 1, 'base_color_srgb': [1., 1., 1., 1.],
                    'roughness': .5, 'metallic': 0., 'base_color_texture': None,
                    'textures': {}, 'config': {}, 'texture_packed': True}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.assign_material(['BaseStone'], 'Finish', instance='Kit_B',
                link_mode='OBJECT', lease_id='L'))
        operation, params = calls[0]
        self.assertEqual(operation, 'owned_edit')
        self.assertEqual(params['operation'], 'assign_instance_material')
        self.assertEqual(params['params']['instance'], 'Kit_B')
        self.assertEqual(params['params']['link_mode'], 'OBJECT')
        self.assertEqual(params['params']['lease_id'], 'L')

    def test_default_assignment_omits_new_optional_parameters(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'material': 'Finish', 'objects': ['Cube'], 'slot': 0,
                    'updated': False, 'material_users': 1, 'base_color_srgb': [1., 1., 1., 1.],
                    'roughness': .5, 'metallic': 0., 'base_color_texture': None,
                    'textures': {}, 'config': {}, 'texture_packed': True}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.assign_material(['Cube'], 'Finish', lease_id='L'))
        self.assertEqual(calls[0][1]['operation'], 'assign_material')
        self.assertNotIn('instance', calls[0][1]['params'])
        self.assertNotIn('link_mode', calls[0][1]['params'])
