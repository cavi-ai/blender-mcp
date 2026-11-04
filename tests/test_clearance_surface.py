"""Read-only clearance inputs, bounds and catalog contract."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class ClearanceSurfaceTests(unittest.TestCase):
    def test_clearance_is_read_only_and_keeps_explicit_metre_threshold(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'complete': True, 'passed': True}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002,
                                                      samples=9, max_queries=10000))
        self.assertEqual(calls[0][0], 'inspect_skin_clearance')
        self.assertEqual(calls[0][1]['min_clearance_m'], .002)
        self.assertEqual(calls[0][1]['max_queries'], 10000)
        self.assertNotIn('lease_id', calls[0][1])
        from cavi_blender_mcp.operations import LEASE_FREE
        self.assertIn('inspect_skin_clearance', LEASE_FREE)
        tool = next(tool for tool in asyncio.run(server.mcp.list_tools())
                    if tool.name == 'inspect_skin_clearance')
        self.assertTrue(tool.annotations.read_only_hint)
        self.assertIn('min_clearance_m', tool.input_schema['required'])
