import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class ShapeKeySurfaceTests(unittest.TestCase):
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

    def test_shape_key_actions_map_to_owned_operations(self):
        calls = self.capture()
        asyncio.run(server.object_edit("shape_key_add", "Cube", new_name="Smile",
                                       value=.5, offsets=[[0, 0, 0, .1]], lease_id="L"))
        asyncio.run(server.object_edit("shape_key_value", "Cube", new_name="Smile",
                                       value=.8, lease_id="L"))
        asyncio.run(server.object_edit("shape_key_keyframe", "Cube", new_name="Smile",
                                       action_name="SmileAction",
                                       keyframes=[server.ShapeKeyframe(frame=1, value=0),
                                                  server.ShapeKeyframe(frame=11, value=1)],
                                       lease_id="L"))
        asyncio.run(server.object_edit("shape_key_remove", "Cube", new_name="Smile",
                                       lease_id="L"))
        operations = self.inner(calls)
        self.assertEqual(operations[0], ("shape_key_add", {
            "lease_id": "L", "name": "Cube", "new_name": "Smile", "value": .5,
            "offsets": [[0, 0, 0, .1]], "source": None}))
        self.assertEqual(operations[1], ("shape_key_value", {
            "lease_id": "L", "name": "Cube", "new_name": "Smile", "value": .8}))
        self.assertEqual(operations[2], ("shape_key_keyframe", {
            "lease_id": "L", "name": "Cube", "new_name": "Smile",
            "action_name": "SmileAction",
            "keyframes": [{"frame": 1, "value": 0}, {"frame": 11, "value": 1}]}))
        self.assertEqual(operations[3], ("shape_key_remove", {
            "lease_id": "L", "name": "Cube", "new_name": "Smile"}))
        self.assertTrue(all(operation == "owned_edit" for operation, _ in calls))

    def test_shape_key_parameters_are_checked_before_the_bridge(self):
        calls = self.capture()
        for coroutine, message in [
            (server.object_edit("shape_key_add", "Cube"), "requires: new_name"),
            (server.object_edit("shape_key_value", "Cube", new_name="Smile"),
             "requires: value"),
            (server.object_edit("shape_key_keyframe", "Cube", new_name="Smile",
                                action_name="Action"), "requires: keyframes"),
            (server.object_edit("shape_key_keyframe", "Cube", new_name="Smile",
                                keyframes=[server.ShapeKeyframe(frame=1, value=0)]),
             "requires: action_name"),
            (server.object_edit("shape_key_remove", "Cube", new_name="Smile",
                                value=.5), "does not accept: value"),
            (server.object_edit("shape_key_add", "Cube", new_name="Smile",
                                action_name="Action"), "does not accept: action_name"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                asyncio.run(coroutine)
        self.assertEqual(calls, [])

    def test_shape_key_values_are_bounded(self):
        for arguments in (
            {"action": "shape_key_add", "name": "Cube", "new_name": "Smile", "value": 2},
            {"action": "shape_key_value", "name": "Cube", "new_name": "Smile", "value": -1},
            {"action": "shape_key_add", "name": "Cube", "new_name": "Smile",
             "offsets": [[0, 0, 0]]},
            {"action": "shape_key_keyframe", "name": "Cube", "new_name": "Smile",
             "action_name": "Action", "keyframes": []},
        ):
            with self.assertRaisesRegex(Exception, "validation error"):
                asyncio.run(server.mcp.call_tool("object_edit", arguments))


if __name__ == "__main__":
    unittest.main()
