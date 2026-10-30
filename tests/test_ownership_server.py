import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class LegacyBridgeTests(unittest.TestCase):
    def test_new_mcp_refuses_to_edit_a_bridge_without_ownership_support(self):
        effects = []

        def legacy(operation, params):
            if operation == "owned_edit":
                raise RuntimeError("Unknown operation: owned_edit")
            effects.append(operation)
            return {"name": "WouldHaveBeenCreated"}

        with (
            patch.object(server, "BridgeClient", return_value=SimpleNamespace(call=legacy)),
            self.assertRaisesRegex(RuntimeError, "owned_edit"),
        ):
            server.create_primitive("Prop", "cube", lease_id="unvalidated-token")
        self.assertEqual(effects, [])
