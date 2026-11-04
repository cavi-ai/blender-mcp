"""Contact correction is explicit, leased and separate from inspection."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server
from cavi_blender_mcp.rig_models import FootLockWindow


class FootLockTests(unittest.TestCase):
    def test_contact_correction_forwards_the_complete_profile(self):
        calls = []

        def call(operation, params):
            calls.append(params)
            return {"name": "Rig"}

        window = FootLockWindow(
            bone="Foot.L",
            point=(0, 0, 0),
            start_frame=5,
            end_frame=20,
            max_drift_m=0.001,
            max_height_error_m=0.001,
            ground_z_m=0,
            pole=(0, -1, 1),
            pole_angle_degrees=90,
        )
        with patch.object(server, "BridgeClient", return_value=SimpleNamespace(call=call)):
            asyncio.run(
                server.rig_edit(
                    "contact_lock",
                    "Rig",
                    source_action="Walk",
                    action_name="Grounded",
                    new_name="GroundedRig",
                    foot_locks=[window],
                    lease_id="L",
                )
            )
            with self.assertRaisesRegex(ValueError, "does not accept: foot_locks"):
                asyncio.run(server.rig_edit("clear_pose", "Rig", foot_locks=[window], lease_id="L"))
        self.assertEqual(calls[0]["operation"], "lock_rig_contacts")
        self.assertEqual(calls[0]["params"]["foot_locks"][0]["pole"], (0, -1, 1))
        self.assertEqual(calls[0]["params"]["lease_id"], "L")
