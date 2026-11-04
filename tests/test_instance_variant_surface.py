"""Making an instance unique is an explicit owned edit with a collection label."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class InstanceVariantSurfaceTests(unittest.TestCase):
    def test_make_unique_keeps_the_lease_and_definition_name(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'name': 'Kit_B', 'type': 'EMPTY', 'location': [0., 0., 0.],
                    'rotation_degrees': [0., 0., 0.], 'rotation_mode': 'XYZ', 'scale': [1., 1., 1.],
                    'dimensions': [0., 0., 0.], 'parent': None, 'children': 0,
                    'collections': [], 'modifiers': []}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.object_edit('make_unique', 'Kit_B', new_name='TunedKit', lease_id='L'))
        self.assertEqual(calls, [('owned_edit', {'operation': 'make_instance_unique', 'params': {
            'name': 'Kit_B', 'new_name': 'TunedKit', 'lease_id': 'L'}})])

    def test_unique_definition_requires_a_name_and_rejects_duplicate_flags(self):
        for options in [{}, {'new_name': 'TunedKit', 'linked': True}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                asyncio.run(server.object_edit('make_unique', 'Kit_B', lease_id='L', **options))
