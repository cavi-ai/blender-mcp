"""Read-only clearance inputs, bounds and catalog contract."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class ClearanceSurfaceTests(unittest.TestCase):
    def test_region_attribute_is_opt_in_and_forwarded(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'complete': True, 'passed': True, 'garments': [{'regions': []}]}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002))
            asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002,
                                                      region_attribute='garment_role'))
        self.assertNotIn('region_attribute', calls[0][1])
        self.assertEqual(calls[1][1]['region_attribute'], 'garment_role')
        tool = next(tool for tool in asyncio.run(server.mcp.list_tools())
                    if tool.name == 'inspect_skin_clearance')
        self.assertIn('region_attribute', tool.input_schema['properties'])

    def test_regional_request_rejects_older_bridge_responses(self):
        from mcp.server.mcpserver.exceptions import UnexpectedToolError

        for response in ({'garments': [{}]}, {'garments': []}, {'garments': [{'regions': None}]}):
            client = SimpleNamespace(call=lambda *_, result=response: result)
            with (self.subTest(response=response),
                  patch.object(server, 'BridgeClient', return_value=client),
                  self.assertRaisesRegex(UnexpectedToolError, 'refresh the Blender bridge')):
                asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002,
                                                          region_attribute='garment_role'))

    def test_explicit_frames_are_forwarded_and_invalid_schedules_rejected(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'complete': True, 'passed': True}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002,
                                                      sample_frames=[1, 12.5, 25]))
            asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002,
                                                      sample_frames=[12.5]))
            for invalid in ([], [True], [float('nan')], [float('inf')], [0], [26],
                            [2, 2], [3, 2], list(range(1, 34)), ['2']):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002,
                                                              sample_frames=invalid))
        self.assertEqual([params['sample_frames'] for _, params in calls], [[1., 12.5, 25.], [12.5]])

    def test_rest_option_requires_one_frame_and_echo(self):
        from mcp.server.mcpserver.exceptions import UnexpectedToolError

        calls = []
        def call(operation, params):
            calls.append(params)
            return {'rest_armature': 'Rig'}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            for frames in (None, [1, 2]):
                with self.assertRaises(ValueError):
                    asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002,
                                                              sample_frames=frames, rest_armature='Rig'))
            asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002,
                                                      sample_frames=[12.5], rest_armature='Rig'))
        self.assertEqual(calls[0]['rest_armature'], 'Rig')
        with (patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=lambda *_: {})),
              self.assertRaises(UnexpectedToolError)):
            asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002,
                                                      sample_frames=[12.5], rest_armature='Rig'))

    def test_witness_opt_in_and_stale_bridge(self):
        from mcp.server.mcpserver.exceptions import UnexpectedToolError

        calls = []
        def call(operation, params):
            calls.append(params)
            return {'garments': [{'worst_support': None, 'regions': [{'worst_support': None}]}]}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002))
            asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002,
                        region_attribute='role', include_worst_support=True))
        self.assertNotIn('include_worst_support', calls[0])
        self.assertIs(calls[1]['include_worst_support'], True)
        for result in ({'garments': [{}]}, {'garments': [{'worst_support': None, 'regions': [{}]}]}):
            with (patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=lambda *_, value=result: value)),
                  self.assertRaises(UnexpectedToolError)):
                asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002,
                            region_attribute='role', include_worst_support=True))

    def test_violation_patches_require_single_frame_and_bridge_support(self):
        from mcp.server.mcpserver.exceptions import UnexpectedToolError

        calls = []
        def call(operation, params):
            calls.append(params)
            return {'garments': [{'violation_patches': {}}]}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            for frames in (None, [1, 2]):
                with self.assertRaises(ValueError):
                    asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002,
                                                              sample_frames=frames, include_violation_patches=True))
            asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002,
                                                      sample_frames=[12.5], include_violation_patches=True))
        self.assertIs(calls[0]['include_violation_patches'], True)
        with (patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=lambda *_: {'garments': [{}]})),
              self.assertRaises(UnexpectedToolError)):
            asyncio.run(server.inspect_skin_clearance('Body', ['Coat'], 1, 25, .002,
                                                      sample_frames=[12.5], include_violation_patches=True))

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
