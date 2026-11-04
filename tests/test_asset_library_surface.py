"""Native library inspection is read-only; append binds names to inspected source bytes."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class AssetLibrarySurfaceTests(unittest.TestCase):
    def test_inspect_and_append_use_distinct_lease_policies(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'path': '/w/kit.blend', 'sha256': 'a'*64}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.asset_library('inspect', 'kit.blend', kind='objects'))
            asyncio.run(server.asset_library('append', 'kit.blend', kind='collections',
                names=['Kit'], expected_sha256='a'*64, lease_id='L'))
        self.assertEqual(calls[0], ('inspect_asset_library', {'path': 'kit.blend',
            'kind': 'objects', 'offset': 0, 'limit': 100}))
        self.assertEqual(calls[1], ('owned_edit', {'operation': 'append_asset_library', 'params': {
            'path': 'kit.blend', 'kind': 'collections', 'names': ['Kit'], 'expected_sha256': 'a'*64,
            'lease_id': 'L'}}))

    def test_append_requires_exact_source_and_selection(self):
        for kwargs in ({}, {'names': ['Kit']}, {'expected_sha256': 'a'*64}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                asyncio.run(server.asset_library('append', 'kit.blend', **kwargs))

    def test_inspection_rejects_append_parameters(self):
        with self.assertRaisesRegex(ValueError, 'names'):
            asyncio.run(server.asset_library('inspect', 'kit.blend', names=['Kit']))
