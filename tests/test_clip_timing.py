"""Clip timing is explicit and reaches bake and read-only validation."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server
from cavi_blender_mcp.rig_models import ClipTiming, ContactWindow, MotionSkinPair


class ClipTimingTests(unittest.TestCase):
    def test_timing_and_affine_sampling_reach_the_bridge(self):
        calls = []

        def call(operation, params):
            calls.append((operation, params))
            return {'name': 'Clip'}

        timing = ClipTiming(start_frame=2.5, playback_rate=2)
        window = ContactWindow(bone='Foot', point=(0, 0, -.1), start_frame=12,
            end_frame=28, max_drift_m=.001, max_height_error_m=.001, ground_z_m=0)
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.rig_edit('bake', 'Source', new_name='Clip', action_name='Run',
                start_frame=12, end_frame=28, timing=timing, lease_id='L'))
            asyncio.run(server.compare_rig_motion('Source', 'Clip',
                [MotionSkinPair(source='Skin', candidate='ClipSkin')], 12, 28, .001,
                candidate_frame_scale=.5, candidate_frame_offset=-3.5))
            asyncio.run(server.inspect_rig('Clip', ['ClipSkin'], contacts=[window],
                contact_frame_scale=.5, contact_frame_offset=-3.5))
        self.assertEqual(calls[0][1]['params']['timing'], timing.model_dump())
        self.assertEqual(calls[1][1]['candidate_frame_scale'], .5)
        self.assertEqual(calls[2][1]['contact_frame_scale'], .5)

    def test_timing_rejects_invalid_rates_and_unrelated_edits(self):
        for rate in (0, -1, True, float('inf'), '2'):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                ClipTiming(start_frame=1, playback_rate=rate)
        with self.assertRaisesRegex(ValueError, 'does not accept: timing'):
            asyncio.run(server.rig_edit('clear_pose', 'Source', timing=ClipTiming(
                start_frame=1, playback_rate=2), lease_id='L'))
