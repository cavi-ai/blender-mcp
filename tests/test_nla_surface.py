"""Typed NLA changes retain omitted settings and the existing edit lease."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from cavi_blender_mcp import server
from cavi_blender_mcp.rig_models import NlaStripSettings


class NlaSurfaceTests(unittest.TestCase):
    def test_sparse_settings_reach_the_owned_strip_edit(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'name': 'Rig'}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.rig_edit('nla_edit', 'Rig', track_name='Gesture',
                strip_name='Wave', strip_settings=NlaStripSettings(
                    frame_start=5.5, repeat=2, blend_in=3), lease_id='L'))
        self.assertEqual(calls, [('owned_edit', {'operation': 'nla_edit', 'params': {
            'name': 'Rig', 'track_name': 'Gesture', 'strip_name': 'Wave',
            'strip_settings': {'frame_start': 5.5, 'repeat': 2.0, 'blend_in': 3.0},
            'lease_id': 'L'}})])

    def test_bad_settings_fail_before_transport(self):
        for value in ({}, {'scale': 0}, {'repeat': float('inf')}, {'mute': 1},
                      {'blend_type': 'invented'}, {'action_frame_start': 5, 'action_frame_end': 4},
                      {'use_auto_blend': True, 'blend_in': 2}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                NlaStripSettings.model_validate(value)

    def test_strip_edit_requires_exact_track_strip_and_changes(self):
        for params in ({}, {'track_name': 'Track'}, {'track_name': 'Track', 'strip_name': 'Clip'}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                asyncio.run(server.rig_edit('nla_edit', 'Rig', lease_id='L', **params))

    def test_other_rig_actions_reject_strip_settings(self):
        with self.assertRaisesRegex(ValueError, 'strip_settings'):
            asyncio.run(server.rig_edit('set_action', 'Rig',
                strip_settings=NlaStripSettings(mute=True), lease_id='L'))
