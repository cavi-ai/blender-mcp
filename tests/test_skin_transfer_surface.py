"""Typed surface transfer options and edit ownership."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class SkinTransferSurfaceTests(unittest.TestCase):
    def test_transfer_routes_explicit_quality_budgets_under_the_edit_lease(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'name': 'CoatSkin'}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.rig_edit('transfer_weights', 'Coat', source='Body',
                new_name='CoatSkin', max_distance_m=.02, max_discarded_weight=.005,
                max_influences=4, lease_id='L'))
        self.assertEqual(calls[0][0], 'owned_edit')
        self.assertEqual(calls[0][1]['operation'], 'transfer_skin_weights')
        params = calls[0][1]['params']
        self.assertEqual(params['max_distance_m'], .02)
        self.assertEqual(params['max_discarded_weight'], .005)
        self.assertEqual(params['lease_id'], 'L')

    def test_selected_morph_channels_share_the_weight_transfer(self):
        calls = []
        def call(operation, params):
            calls.append(params)
            return {'name': 'CoatSkin'}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.rig_edit('transfer_weights', 'Coat', source='Body',
                new_name='CoatSkin', max_distance_m=.02, max_discarded_weight=.005,
                shape_names=['BodyFit', 'ShoulderCorrective'], lease_id='L'))
        self.assertEqual(calls[0]['params']['shape_names'], ['BodyFit', 'ShoulderCorrective'])

    def test_distance_and_loss_budgets_are_required_before_any_native_edit(self):
        for args in ({'max_distance_m': .02}, {'max_discarded_weight': .005}):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'requires'):
                asyncio.run(server.rig_edit('transfer_weights', 'Coat', source='Body',
                    new_name='CoatSkin', **args))

    def test_native_operation_is_owned_and_slow(self):
        from cavi_blender_mcp.operations import LEASE_FREE, OPERATIONS, SLOW_OPERATIONS
        self.assertIn('transfer_skin_weights', OPERATIONS)
        self.assertIn('transfer_skin_weights', SLOW_OPERATIONS)
        self.assertNotIn('transfer_skin_weights', LEASE_FREE)
