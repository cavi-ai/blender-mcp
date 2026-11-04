"""Authored texture and output-default edits route through owned native operations."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class ShaderTextureSurfaceTests(unittest.TestCase):
    def test_native_outputs_are_forwarded_without_assignment_options(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.assign_material(action='set_inputs', material_name='Glaze', node='Tint',
                outputs={'Color': [.2, .4, .8, 1.]}, lease_id='L'))
        operation, envelope = calls[0]
        self.assertEqual(operation, 'owned_edit')
        self.assertEqual(envelope['operation'], 'set_material_inputs')
        self.assertEqual(envelope['params']['outputs'], {'Color': [.2, .4, .8, 1.]})
        self.assertEqual(envelope['params']['lease_id'], 'L')

    def test_image_spec_requires_explicit_interpretation_and_owned_dispatch(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.assign_material(action='set_image', material_name='Glaze', node='Pattern',
                group_path=['Finish'], image=server.ShaderImage(path='patterns/ceramic.exr',
                color_space='Non-Color', alpha_mode='CHANNEL_PACKED'), lease_id='L'))
        operation, envelope = calls[0]
        self.assertEqual(operation, 'owned_edit')
        self.assertEqual(envelope['operation'], 'set_material_image')
        self.assertEqual(envelope['params']['image'], {'path': 'patterns/ceramic.exr',
            'color_space': 'Non-Color', 'alpha_mode': 'CHANNEL_PACKED'})
        self.assertEqual(envelope['params']['lease_id'], 'L')
