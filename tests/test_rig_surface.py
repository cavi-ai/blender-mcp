import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class RigSurfaceTests(unittest.TestCase):
    def capture(self):
        calls = []

        def call(operation, params):
            calls.append((operation, params))
            return {"path": "/tmp/x.png", "workspace": "/w"}

        patcher = patch.object(server, "BridgeClient", return_value=SimpleNamespace(call=call))
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def inner(self, calls):
        return [(params["operation"], params["params"]) for _, params in calls]

    def test_create_maps_bones_to_an_owned_operation(self):
        calls = self.capture()
        bone = server.BoneSpec(name="Root", head=(0, 0, 0), tail=(0, 0, 1))
        asyncio.run(server.rig_edit("create", "Rig", bones=[bone], lease_id="L"))
        operation, params = self.inner(calls)[0]
        self.assertEqual(operation, "create_armature")
        self.assertEqual(params["name"], "Rig")
        self.assertEqual(params["location"], (0, 0, 0))
        self.assertEqual(params["bones"], [{
            "name": "Root", "head": (0, 0, 0), "tail": (0, 0, 1), "parent": None,
            "connect": False, "deform": True, "roll_degrees": 0}])
        self.assertEqual(calls[0][0], "owned_edit")

    def test_bind_and_weight_defaults(self):
        calls = self.capture()
        asyncio.run(server.rig_edit("bind", "Rig", names=["A", "B"], lease_id="L"))
        asyncio.run(server.rig_edit("weights", "Mesh", lease_id="L"))
        operations = self.inner(calls)
        self.assertEqual(operations[0], ("bind_skin", {
            "lease_id": "L", "name": "Rig", "names": ["A", "B"]}))
        self.assertEqual(operations[1], ("repair_weights", {
            "lease_id": "L", "name": "Mesh", "max_influences": 4,
            "clean_threshold": 0.0001, "normalize": True}))
        self.assertTrue(all(operation == "owned_edit" for operation, _ in calls))

    def test_weight_options_are_forwarded(self):
        calls = self.capture()
        asyncio.run(server.rig_edit("weights", "Mesh", max_influences=2,
                                    clean_threshold=0.01, normalize=False, lease_id="L"))
        self.assertEqual(self.inner(calls)[0][1], {
            "lease_id": "L", "name": "Mesh", "max_influences": 2,
            "clean_threshold": 0.01, "normalize": False})

    def test_action_parameters_are_checked_before_the_bridge(self):
        calls = self.capture()
        for coroutine, message in [
            (server.rig_edit("create", "Rig"), "requires: bones"),
            (server.rig_edit("bind", "Rig"), "requires: names"),
            (server.rig_edit("bind", "Rig", names=["A"], location=(0, 0, 0)),
             "does not accept: location"),
            (server.rig_edit("weights", "Mesh", names=["A"]), "does not accept: names"),
            (server.rig_edit("weights", "Mesh", bones=[server.BoneSpec(
                name="Root", head=(0, 0, 0), tail=(0, 0, 1))]), "does not accept: bones"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                asyncio.run(coroutine)
        self.assertEqual(calls, [])

    def test_invalid_bone_and_weight_inputs_are_bounded(self):
        for arguments in (
            {"action": "create", "name": "Rig", "bones": [{
                "name": "Root", "head": [0, 0], "tail": [0, 0, 1]}]},
            {"action": "weights", "name": "Mesh", "max_influences": 0},
            {"action": "weights", "name": "Mesh", "max_influences": 33},
            {"action": "weights", "name": "Mesh", "clean_threshold": 2},
            {"action": "weights", "name": "Mesh", "normalize": "yes"},
        ):
            with self.assertRaisesRegex(Exception, "validation error"):
                asyncio.run(server.mcp.call_tool("rig_edit", arguments))


if __name__ == "__main__":
    unittest.main()
