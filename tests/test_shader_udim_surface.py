"""Explicit UDIM declarations route through the existing owned image operation."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from cavi_blender_mcp import server


class ShaderUdimSurfaceTests(unittest.TestCase):
    def test_tile_numbers_are_forwarded_with_the_authored_pattern(self):
        self.assertIn('tiles', server.ShaderImage.model_fields)
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.assign_material(action='set_image', material_name='Glaze', node='Pattern',
                image=server.ShaderImage(path='glaze.<UDIM>.exr', color_space='Non-Color',
                    tiles=[1001, 1002, 1011]), lease_id='L'))
        operation, envelope = calls[0]
        self.assertEqual(operation, 'owned_edit')
        self.assertEqual(envelope['operation'], 'set_material_image')
        self.assertEqual(envelope['params']['image']['tiles'], [1001, 1002, 1011])
        self.assertEqual(envelope['params']['lease_id'], 'L')

    def test_tile_declarations_reject_noninteger_and_empty_values(self):
        self.assertIn('tiles', server.ShaderImage.model_fields)
        for tiles in [[], [1000], [True], ['1001'], [1001.5]]:
            with self.subTest(tiles=tiles), self.assertRaises(ValidationError):
                server.ShaderImage(path='glaze.<UDIM>.exr', color_space='Non-Color', tiles=tiles)
