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

    def test_pose_and_keyframe_actions_map_to_owned_operations(self):
        calls = self.capture()
        pose = server.PoseSpec(bone="Spine", rotation_degrees=(0, 0, 45))
        asyncio.run(server.rig_edit("pose", "Rig", poses=[pose], frame=5, reset=True,
                                    lease_id="L"))
        keyframe = server.KeyframeSpec(frame=1, poses=[pose])
        asyncio.run(server.rig_edit("keyframe", "Rig", action_name="Walk",
                                    keyframes=[keyframe], lease_id="L"))
        asyncio.run(server.rig_edit("clear_pose", "Rig", frame=1, lease_id="L"))
        operations = self.inner(calls)
        self.assertEqual(operations[0], ("pose_rig", {
            "lease_id": "L", "name": "Rig", "frame": 5, "reset": True,
            "poses": [{"bone": "Spine", "rotation_degrees": (0, 0, 45),
                       "location": None, "scale": None}]}))
        self.assertEqual(operations[1], ("keyframe_rig", {
            "lease_id": "L", "name": "Rig", "action_name": "Walk",
            "keyframes": [{"frame": 1, "poses": [{
                "bone": "Spine", "rotation_degrees": (0, 0, 45),
                "location": None, "scale": None}]}]}))
        self.assertEqual(operations[2], ("clear_pose", {"lease_id": "L", "name": "Rig",
                                                        "frame": 1}))

    def test_animation_parameters_are_checked_before_the_bridge(self):
        calls = self.capture()
        pose = server.PoseSpec(bone="Spine", rotation_degrees=(0, 0, 45))
        keyframe = server.KeyframeSpec(frame=1, poses=[pose])
        for coroutine, message in [
            (server.rig_edit("pose", "Rig"), "requires: poses"),
            (server.rig_edit("keyframe", "Rig", keyframes=[keyframe]),
             "requires: action_name"),
            (server.rig_edit("keyframe", "Rig", action_name="Walk"),
             "requires: keyframes"),
            (server.rig_edit("clear_pose", "Rig", poses=[pose]), "does not accept: poses"),
            (server.rig_edit("pose", "Rig", poses=[pose], keyframes=[keyframe]),
             "does not accept: keyframes"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                asyncio.run(coroutine)
        self.assertEqual(calls, [])

    def test_invalid_animation_inputs_are_bounded(self):
        for arguments in (
            {"action": "keyframe", "name": "Rig", "action_name": "Walk",
             "keyframes": [{"frame": 0, "poses": [{"bone": "Spine",
                                                    "rotation_degrees": [0, 0, 1]}]}]},
            {"action": "keyframe", "name": "Rig", "action_name": "Walk",
             "keyframes": [{"frame": 1, "poses": []}]},
        ):
            with self.assertRaisesRegex(Exception, "validation error"):
                asyncio.run(server.mcp.call_tool("rig_edit", arguments))

    def test_animated_export_routes_to_export_asset(self):
        calls = self.capture()
        asyncio.run(server.asset_io("export", "a.fbx", names=["A"], animations=True,
                                    lease_id="L"))
        operation, params = self.inner(calls)[0]
        self.assertEqual(operation, "export_asset")
        self.assertTrue(params["animations"])
        with self.assertRaisesRegex(ValueError, "does not accept: animations"):
            asyncio.run(server.asset_io("export", "p.fbx", lease_id="L",
                                        bake_pair=server.BakePair(high=["H"], low=["L"]),
                                        animations=True))

    def test_animation_qa_maps_to_inspect_rig(self):
        calls = self.capture()
        asyncio.run(server.inspect_rig("Rig", ["Skin"], action="Walk",
                                       checks=["root_motion", "loop", "deformation"],
                                       samples=8))
        self.assertEqual(calls, [("inspect_rig", {
            "armature": "Rig", "meshes": ["Skin"], "max_influences": 4,
            "action": "Walk", "checks": ["root_motion", "loop", "deformation"],
            "samples": 8})])

    def test_animation_qa_parameters_are_bounded(self):
        for arguments in (
            {"armature": "Rig", "meshes": ["Skin"], "checks": ["foot_slide"]},
            {"armature": "Rig", "meshes": ["Skin"], "samples": 1},
            {"armature": "Rig", "meshes": ["Skin"], "samples": 33},
            {"armature": "Rig", "meshes": ["Skin"], "action": ""},
        ):
            with self.assertRaisesRegex(Exception, "validation error"):
                asyncio.run(server.mcp.call_tool("inspect_rig", arguments))

    def test_retarget_maps_to_an_owned_operation(self):
        calls = self.capture()
        asyncio.run(server.rig_edit("retarget", "Target", source="Source",
                                    source_action="Walk", action_name="Retargeted",
                                    mapping={"Root": "Bone"}, samples=4, lease_id="L"))
        self.assertEqual(self.inner(calls)[0], ("retarget_rig", {
            "lease_id": "L", "name": "Target", "source": "Source",
            "source_action": "Walk", "action_name": "Retargeted",
            "mapping": {"Root": "Bone"}, "samples": 4}))

    def test_retarget_parameters_are_bounded(self):
        calls = self.capture()
        for coroutine, message in [
            (server.rig_edit("retarget", "Target", source_action="Walk",
                             action_name="Retargeted"), "requires: source"),
            (server.rig_edit("retarget", "Target", source="Source",
                             action_name="Retargeted"), "requires: source_action"),
            (server.rig_edit("retarget", "Target", source="Source",
                             source_action="Walk"), "requires: action_name"),
            (server.rig_edit("retarget", "Target", source="Source",
                             source_action="Walk", action_name="Retargeted",
                             keyframes=[]), "does not accept: keyframes"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                asyncio.run(coroutine)
        for arguments in (
            {"action": "retarget", "name": "Target", "source": "Source",
             "source_action": "Walk", "action_name": "Retargeted", "samples": 1},
            {"action": "retarget", "name": "Target", "source": "Source",
             "source_action": "Walk", "action_name": "Retargeted", "samples": 257},
        ):
            with self.assertRaisesRegex(Exception, "validation error"):
                asyncio.run(server.mcp.call_tool("rig_edit", arguments))
        self.assertEqual(calls, [])

    def test_action_and_nla_actions_map_to_owned_operations(self):
        calls = self.capture()
        asyncio.run(server.rig_edit("set_action", "Rig", action_name="Walk", lease_id="L"))
        asyncio.run(server.rig_edit("set_action", "Rig", lease_id="L"))
        asyncio.run(server.rig_edit("rename_action", "Rig", action_name="Walk",
                                    new_name="Run", lease_id="L"))
        asyncio.run(server.rig_edit("delete_action", "Rig", action_name="Run",
                                    lease_id="L"))
        asyncio.run(server.rig_edit("nla_push", "Rig", action_name="Walk",
                                    track_name="Locomotion", strip_name="Walk",
                                    start_frame=5, lease_id="L"))
        asyncio.run(server.rig_edit("nla_remove", "Rig", track_name="Locomotion",
                                    lease_id="L"))
        operations = self.inner(calls)
        self.assertEqual(operations[0], ("set_action", {
            "lease_id": "L", "name": "Rig", "action_name": "Walk"}))
        self.assertEqual(operations[1], ("set_action", {
            "lease_id": "L", "name": "Rig", "action_name": None}))
        self.assertEqual(operations[2], ("rename_action", {
            "lease_id": "L", "name": "Rig", "action_name": "Walk", "new_name": "Run"}))
        self.assertEqual(operations[3], ("delete_action", {
            "lease_id": "L", "name": "Rig", "action_name": "Run"}))
        self.assertEqual(operations[4], ("nla_push", {
            "lease_id": "L", "name": "Rig", "action_name": "Walk",
            "track_name": "Locomotion", "strip_name": "Walk", "start_frame": 5}))
        self.assertEqual(operations[5], ("nla_remove", {
            "lease_id": "L", "name": "Rig", "track_name": "Locomotion",
            "strip_name": None}))

    def test_action_and_nla_parameters_are_checked(self):
        calls = self.capture()
        for coroutine, message in [
            (server.rig_edit("rename_action", "Rig", action_name="Walk"),
             "requires: new_name"),
            (server.rig_edit("delete_action", "Rig"), "requires: action_name"),
            (server.rig_edit("nla_remove", "Rig", strip_name="Walk",
                             track_name="Track", action_name="Walk"),
             "does not accept: action_name"),
            (server.rig_edit("set_action", "Rig", poses=[]), "does not accept: poses"),
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
