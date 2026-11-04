"""Delivered contacts retain source-frame and rest-axis reference contracts."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server
from cavi_blender_mcp.rig_models import ContactReference, ContactWindow


class DeliveredContactTests(unittest.TestCase):
    def test_reference_and_fractional_clip_offset_reach_inspection(self):
        calls = []

        def call(operation, params):
            calls.append((operation, params))
            return {"armature": "Imported", "bones": [], "meshes": []}

        window = ContactWindow(
            bone="Foot",
            point=(0, 0, -0.1),
            start_frame=1,
            end_frame=25,
            max_drift_m=0.001,
            max_height_error_m=0.001,
            ground_z_m=0,
        )
        with patch.object(server, "BridgeClient", return_value=SimpleNamespace(call=call)):
            asyncio.run(
                server.inspect_rig(
                    "Imported",
                    ["Skin"],
                    action="ImportedWalk",
                    contacts=[window],
                    contact_reference=ContactReference(armature="Source", action="Walk"),
                    contact_frame_offset=2.5,
                )
            )
        self.assertEqual(calls[0][1]["contact_frame_offset"], 2.5)
        self.assertEqual(calls[0][1]["contact_reference"], {"armature": "Source", "action": "Walk"})
