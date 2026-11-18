import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server
from cavi_blender_mcp.client import MAX_TIMEOUT, SLOW_TIMEOUT, operation_timeout
from cavi_blender_mcp.presets import AXIS_PRESETS, USD_AXES

FBX_AXES = {"X", "Y", "Z", "-X", "-Y", "-Z"}
FBX_SCALES = {"FBX_SCALE_NONE", "FBX_SCALE_UNITS", "FBX_SCALE_CUSTOM", "FBX_SCALE_ALL"}
USD_AXIS = {"X", "Y", "Z", "NEGATIVE_X", "NEGATIVE_Y", "NEGATIVE_Z"}


class AAASurfaceTests(unittest.TestCase):
    def capture(self, result=None):
        calls = []

        def call(operation, params):
            calls.append((operation, params))
            return result if result is not None else {"path": "/tmp/x.png", "workspace": "/w"}

        patcher = patch.object(server, "BridgeClient", return_value=SimpleNamespace(call=call))
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def inner(self, calls):
        return [(params["operation"], params["params"]) for _, params in calls]

    def test_modifier_kinds_take_amount_and_source_operand(self):
        calls = self.capture({"name": "R", "type": "MESH", "location": [0, 0, 0],
                              "rotation_degrees": [0, 0, 0], "rotation_mode": "XYZ",
                              "scale": [1, 1, 1], "dimensions": [1, 1, 1], "parent": None,
                              "children": [], "collections": [], "modifiers": []})
        for kind, amount, operand in (("weld", .001, None), ("displace", .1, None),
                                      ("weighted_normal", 50, None), ("shrinkwrap", 0, "Body"),
                                      ("data_transfer", 1, "Proxy")):
            asyncio.run(server.mcp.call_tool("mesh_edit", {
                "action": "modifier", "name": "R", "kind": kind, "amount": amount,
                "lease_id": "L", **({"operand": operand} if operand else {})}))
        self.assertEqual([(p["kind"], p["amount"], p["operand"]) for _, p in self.inner(calls)],
                         [("weld", .001, None), ("displace", .1, None), ("weighted_normal", 50, None),
                          ("shrinkwrap", 0, "Body"), ("data_transfer", 1, "Proxy")])

    def test_mesh_actions_translate_preserve_and_defaults(self):
        calls = self.capture()
        asyncio.run(server.mesh_edit("decimate_to", "R", target_triangles=100, lease_id="L"))
        asyncio.run(server.mesh_edit("remesh_quad", "R", target_faces=500,
                                     preserve=["sharp"], lease_id="L"))
        asyncio.run(server.mesh_edit("lod_chain", "R", lease_id="L"))
        asyncio.run(server.mesh_edit("cleanup", "R", lease_id="L"))
        asyncio.run(server.mesh_edit("lightmap_uv", "R", lease_id="L"))
        decimate, remesh, lods, cleanup, lightmap = self.inner(calls)
        self.assertEqual(decimate, ("decimate_to", {
            "lease_id": "L", "name": "R", "amount": None, "target_triangles": 100,
            "symmetry_axis": None, "preserve_seams": True}))
        self.assertEqual((remesh[1]["preserve_sharp"], remesh[1]["preserve_boundary"]),
                         (True, False))
        self.assertEqual(lods[1]["rename_source"], False)
        self.assertEqual(cleanup[0], "cleanup_mesh")
        self.assertEqual(cleanup[1]["steps"], ["merge", "delete_loose", "recalc_normals"])
        self.assertEqual(lightmap[1]["uv_layer"], "UVMap_Lightmap")
        self.assertEqual(lightmap[1]["margin_px"], 4)

    def test_new_actions_refuse_foreign_parameters_before_the_bridge(self):
        calls = self.capture()
        for coroutine, message in [
            (server.mesh_edit("decimate_to", "R", target_faces=10), "Not valid for action"),
            (server.mesh_edit("remesh_quad", "R"), "target_faces is required for action"),
            (server.mesh_edit("remesh_quad", "R", target_faces=99, preserve=["seams"]),
             "preserve accepts only"),
            (server.mesh_edit("decimate_to", "R", preserve=["sharp"]), "preserve accepts only"),
            (server.mesh_edit("texel_density", "R"), "target_px_per_m is required for action"),
            (server.mesh_edit("collision", "R", steps=["merge"]), "Not valid for action=\\w+:\\ssteps"),
            (server.object_edit("rename", "R"), "new_name is required for action"),
            (server.object_edit("snap_to_grid", "R", new_name="x"), "Not valid for action"),
            (server.object_edit("apply_transforms", "R", grid=1), "Not valid for action=\\w+:\\sgrid"),
            (server.asset_io("export", "a.fbx", names=["R"],
                             bake_pair=server.BakePair(high=["H"], low=["R"])),
             "Not valid for action=\\w+:\\snames"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                asyncio.run(coroutine)
        self.assertEqual(calls, [])

    def test_object_keyframes_map_transform_channels(self):
        calls = self.capture({"name": "Camera", "type": "CAMERA", "location": [0, 0, 0],
                              "rotation_degrees": [0, 0, 0], "rotation_mode": "XYZ",
                              "scale": [1, 1, 1], "dimensions": [0, 0, 0], "parent": None,
                              "children": [], "collections": [], "modifiers": [],
                              "action": "Turntable", "frames": [1, 97]})
        keys = [{"frame": 1, "rotation_degrees": (0, 0, 0), "interpolation": "LINEAR"},
                {"frame": 97, "rotation_degrees": (0, 0, 360), "location": (0, 0, 1)}]
        asyncio.run(server.mcp.call_tool("object_edit", {
            "action": "keyframe", "name": "Camera", "action_name": "Turntable",
            "keyframes": keys, "lease_id": "L"}))
        self.assertEqual(self.inner(calls), [("object_keyframe", {
            "name": "Camera", "action_name": "Turntable", "keyframes": [
                {"frame": 1, "rotation_degrees": [0, 0, 0], "interpolation": "LINEAR"},
                {"frame": 97, "location": [0, 0, 1], "rotation_degrees": [0, 0, 360],
                 "interpolation": "BEZIER"}], "lease_id": "L"})])
        for bad in ([{"frame": 1}], [{"frame": 1, "value": 0.5}]):
            with self.subTest(bad=bad), self.assertRaisesRegex(Exception, "keyframe"):
                asyncio.run(server.mcp.call_tool("object_edit", {
                    "action": "keyframe", "name": "Camera", "action_name": "Clip",
                    "keyframes": bad, "lease_id": "L"}))
        self.assertEqual(len(calls), 1)

    def test_primitives_include_torus_grid_curve_and_text(self):
        result = {"name": "P", "type": "MESH", "location": [0, 0, 0],
                  "rotation_degrees": [0, 0, 0], "rotation_mode": "XYZ", "scale": [1, 1, 1],
                  "dimensions": [1, 1, 1], "parent": None, "children": [], "collections": [],
                  "modifiers": []}
        calls = self.capture(result)
        for kind in ("torus", "icosphere", "grid", "bezier_curve"):
            asyncio.run(server.mcp.call_tool("object_edit", {
                "action": "create_primitive", "name": kind, "kind": kind, "lease_id": "L"}))
        asyncio.run(server.mcp.call_tool("object_edit", {
            "action": "create_primitive", "name": "Sign", "kind": "text", "body": "EXIT",
            "lease_id": "L"}))
        self.assertEqual([(op, params["kind"], params["body"]) for op, params in self.inner(calls)],
                         [("create_primitive", kind, None) for kind in
                          ("torus", "icosphere", "grid", "bezier_curve")]
                         + [("create_primitive", "text", "EXIT")])

    def test_visibility_maps_viewport_and_render_flags(self):
        calls = self.capture({"name": "Prop", "type": "MESH", "location": [0, 0, 0],
                              "rotation_degrees": [0, 0, 0], "rotation_mode": "XYZ",
                              "scale": [1, 1, 1], "dimensions": [1, 1, 1], "parent": None,
                              "children": [], "collections": [], "modifiers": []})
        asyncio.run(server.mcp.call_tool("object_edit", {
            "action": "visibility", "name": "Prop", "hide_render": True, "lease_id": "L"}))
        self.assertEqual(self.inner(calls), [("set_visibility", {
            "name": "Prop", "hide_viewport": None, "hide_render": True, "lease_id": "L"})])
        for arguments in ({}, {"hide_viewport": True, "grid": 1}):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(ValueError, "visibility"):
                asyncio.run(server.object_edit("visibility", "Prop", lease_id="L", **arguments))
        with self.assertRaisesRegex(ValueError, "Not valid for action"):
            asyncio.run(server.object_edit("rename", "Prop", new_name="P", hide_render=True))

    def test_object_actions_map_to_bridge_operations(self):
        calls = self.capture()
        asyncio.run(server.object_edit("apply_transforms", "R", lease_id="L"))
        asyncio.run(server.object_edit("set_origin", "R", origin="point", location=(1, 2, 3),
                                       lease_id="L"))
        asyncio.run(server.object_edit("rename", "R", new_name="SM_R", lease_id="L"))
        asyncio.run(server.object_edit("add_socket", "R", new_name="Grip", lease_id="L"))
        ops = self.inner(calls)
        self.assertEqual([op for op, _ in ops],
                         ["apply_transforms", "set_origin", "rename_object", "add_socket"])
        self.assertEqual(ops[0][1]["components"], ["rotation", "scale"])
        self.assertEqual(ops[1][1]["location"], (1, 2, 3))

    def test_export_routes_new_features_to_export_asset(self):
        calls = self.capture()
        asyncio.run(server.asset_io("export", "a.fbx", names=["R"], lease_id="L"))
        asyncio.run(server.asset_io("export", "a.fbx", names=["R"], lods=True, lease_id="L"))
        asyncio.run(server.asset_io("export", "a.usdc", names=["R"], lease_id="L"))
        asyncio.run(server.asset_io("export", "t.fbx", names=["R"], textures=True,
                                    lease_id="L"))
        asyncio.run(server.asset_io("export", "t.usdc", names=["R"], textures=True,
                                    lease_id="L"))
        asyncio.run(server.asset_io("export", "p.fbx", lease_id="L",
                                    bake_pair=server.BakePair(high=["H"], low=["R"])))
        ops = self.inner(calls)
        self.assertEqual([op for op, _ in ops],
                         ["export_mesh", "export_asset", "export_asset", "export_asset",
                          "export_asset", "export_asset"])
        self.assertNotIn("lods", ops[0][1])
        self.assertTrue(ops[3][1]["textures"])
        self.assertTrue(ops[4][1]["textures"])
        self.assertEqual(ops[5][1]["bake_pair"], {"high": ["H"], "low": ["R"]})

    def test_texture_sizes_take_width_and_height(self):
        calls = self.capture()
        asyncio.run(server.mesh_edit("texel_density", "R", target_px_per_m=256,
                                     texture_resolution=(2048, 512), lease_id="L"))
        asyncio.run(server.mesh_edit("unwrap", "R", texture_resolution=512, lease_id="L"))
        (_, density), (_, unwrap) = self.inner(calls)
        self.assertEqual((density["texture_resolution"], unwrap["texture_resolution"]), ((2048, 512), 512))

    def test_review_sheet_needs_no_lease_and_scatter_is_owned(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sheet.png'
            path.write_bytes(b'\x89PNG\r\n\x1a\n')
            calls = self.capture({'path': str(path)})
            asyncio.run(server.review_sheet("s.png", mode="matcap"))
        asyncio.run(server.scatter("Ground", "Rocks", 2.0, lease_id="L"))
        self.assertEqual(calls[0][0], "review_sheet")
        self.assertNotIn("lease_id", calls[0][1])
        self.assertEqual(calls[1][0], "owned_edit")
        self.assertEqual(calls[1][1]["operation"], "scatter")

    def test_long_operations_get_longer_timeouts(self):
        self.assertEqual(operation_timeout("owned_edit", {"operation": "remesh_quad"}),
                         MAX_TIMEOUT)
        self.assertEqual(operation_timeout("owned_edit", {"operation": "lod_chain"}),
                         MAX_TIMEOUT)
        self.assertEqual(operation_timeout("review_sheet", {}), SLOW_TIMEOUT)

    def test_presets_use_exporter_enums_and_unity_writes_identity_nodes(self):
        self.assertEqual(AXIS_PRESETS["unity"], {
            "axis_forward": "Y", "axis_up": "Z", "apply_unit_scale": True,
            "apply_scale_options": "FBX_SCALE_UNITS", "bake_space_transform": False})
        for name, preset in AXIS_PRESETS.items():
            with self.subTest(name=name):
                self.assertIn(preset["axis_forward"], FBX_AXES)
                self.assertIn(preset["axis_up"], FBX_AXES)
                self.assertNotEqual(preset["axis_forward"][-1], preset["axis_up"][-1])
                self.assertIn(preset["apply_scale_options"], FBX_SCALES)
                self.assertTrue(set(USD_AXES[name]) <= USD_AXIS)
