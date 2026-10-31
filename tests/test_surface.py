import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server
from cavi_blender_mcp.client import OPERATIONS

TOOLS = {"scene_info", "inspect_mesh_quality", "inspect_rig", "rig_edit", "render_preview",
         "session_control", "object_edit", "mesh_edit", "assign_material", "bake",
         "asset_io", "review_sheet", "level_edit", "scatter"}


class SurfaceTests(unittest.TestCase):
    def capture(self, result=None):
        calls = []

        def call(operation, params):
            calls.append((operation, params))
            return result if result is not None else {"path": "/tmp/x.png", "workspace": "/w"}

        patcher = patch.object(server, "BridgeClient", return_value=SimpleNamespace(call=call))
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def test_catalog_has_expected_tools(self):
        tools = asyncio.run(server.mcp.list_tools())
        self.assertEqual({tool.name for tool in tools}, TOOLS)

    def test_rig_inspection_is_read_only_and_bounded(self):
        self.assertIn("inspect_rig", OPERATIONS)
        calls = self.capture()
        asyncio.run(server.inspect_rig("Rig", ["Skin"], max_influences=4))
        self.assertEqual(calls, [("inspect_rig", {
            "armature": "Rig", "meshes": ["Skin"], "max_influences": 4,
            "action": None, "checks": [], "samples": 8})])

        async def invalid():
            return await server.mcp.call_tool("inspect_rig", {
                "armature": "Rig", "meshes": ["Skin"], "max_influences": 33})

        with self.assertRaisesRegex(Exception, "32"):
            asyncio.run(invalid())

    def test_scene_info_pages_or_targets_one_object(self):
        calls = self.capture()
        asyncio.run(server.scene_info(limit=5, offset=10))
        asyncio.run(server.scene_info(name="Cube"))
        self.assertEqual(calls, [("scene_info", {"limit": 5, "offset": 10}),
                                 ("object_info", {"name": "Cube"})])

    def test_scene_info_limit_is_bounded(self):
        async def invalid():
            return await server.mcp.call_tool("scene_info", {"limit": 1001})

        with self.assertRaisesRegex(Exception, "1000"):
            asyncio.run(invalid())

    def test_render_preview_needs_no_lease(self):
        calls = self.capture()
        asyncio.run(server.render_preview("x.png", resolution=64, orthographic=True))
        operation, params = calls[0]
        self.assertEqual(operation, "render_preview")
        self.assertNotIn("lease_id", params)
        self.assertTrue(params["orthographic"])

    def test_actions_map_to_owned_bridge_operations(self):
        calls = self.capture()
        asyncio.run(server.object_edit("transform", "Cube", rotation_degrees=(0, 0, 90),
                                       lease_id="L"))
        asyncio.run(server.object_edit("set_color", "Cube", rgba=(1, 0, 0, 1), lease_id="L"))
        asyncio.run(server.mesh_edit("unwrap", "Cube", uv_layer="Lightmap", lease_id="L"))
        asyncio.run(server.asset_io("export", "a.glb", names=["Cube"], lease_id="L"))
        inner = [(params["operation"], params["params"]) for _, params in calls]
        self.assertTrue(all(operation == "owned_edit" for operation, _ in calls))
        self.assertEqual(inner[0][0], "transform_object")
        self.assertEqual(inner[1], ("set_color", {"lease_id": "L", "name": "Cube",
                                                  "rgba": (1, 0, 0, 1), "slot": 0}))
        self.assertEqual(inner[2][1]["angle_limit_degrees"], 66)
        self.assertEqual(inner[2][1]["island_margin"], 0.02)
        self.assertEqual(inner[3][0], "export_mesh")
        self.assertFalse(inner[3][1]["include_empties"])

    def test_action_parameters_are_checked_before_the_bridge(self):
        calls = self.capture()
        for coroutine, message in [
            (server.object_edit("create_primitive", "P"), "requires: kind"),
            (server.object_edit("shade", "P", rgba=(1, 1, 1, 1)), "does not accept: rgba"),
            (server.mesh_edit("modifier", "P", kind="bevel"), "requires: amount"),
            (server.asset_io("save", "a.blend", names=["P"]), "does not accept: names"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                asyncio.run(coroutine)
        self.assertEqual(calls, [])

    def test_generate_runs_without_lease(self):
        calls = self.capture()
        with patch.object(server, "generate", return_value={"path": "g.glb"}) as generate:
            asyncio.run(server.asset_io("generate", "g.glb", image="in.png"))
        self.assertEqual(calls, [("scene_info", {"limit": 1})])
        generate.assert_called_once_with("/w", "in.png", "g.glb", 128)
