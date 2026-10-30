import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server
from cavi_blender_mcp.client import MAX_TIMEOUT, SLOW_TIMEOUT, operation_timeout
from cavi_blender_mcp.presets import AXIS_PRESETS, USD_AXES

FBX_AXES = {"X", "Y", "Z", "-X", "-Y", "-Z"}
FBX_SCALES = {"FBX_SCALE_NONE", "FBX_SCALE_UNITS", "FBX_SCALE_CUSTOM", "FBX_SCALE_ALL"}
USD_AXIS = {"X", "Y", "Z", "NEGATIVE_X", "NEGATIVE_Y", "NEGATIVE_Z"}


class AAASurfaceTests(unittest.TestCase):
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
            (server.mesh_edit("decimate_to", "R", target_faces=10), "does not accept"),
            (server.mesh_edit("remesh_quad", "R"), "requires: target_faces"),
            (server.mesh_edit("remesh_quad", "R", target_faces=99, preserve=["seams"]),
             "preserve accepts only"),
            (server.mesh_edit("decimate_to", "R", preserve=["sharp"]), "preserve accepts only"),
            (server.mesh_edit("texel_density", "R"), "requires: target_px_per_m"),
            (server.mesh_edit("collision", "R", steps=["merge"]), "does not accept: steps"),
            (server.object_edit("rename", "R"), "requires: new_name"),
            (server.object_edit("snap_to_grid", "R", new_name="x"), "does not accept"),
            (server.object_edit("apply_transforms", "R", grid=1), "does not accept: grid"),
            (server.asset_io("export", "a.fbx", names=["R"],
                             bake_pair=server.BakePair(high=["H"], low=["R"])),
             "does not accept: names"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                asyncio.run(coroutine)
        self.assertEqual(calls, [])

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
        asyncio.run(server.asset_io("export", "p.fbx", lease_id="L",
                                    bake_pair=server.BakePair(high=["H"], low=["R"])))
        ops = self.inner(calls)
        self.assertEqual([op for op, _ in ops],
                         ["export_mesh", "export_asset", "export_asset", "export_asset"])
        self.assertNotIn("lods", ops[0][1])
        self.assertEqual(ops[3][1]["bake_pair"], {"high": ["H"], "low": ["R"]})

    def test_review_sheet_needs_no_lease_and_scatter_is_owned(self):
        calls = self.capture()
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

    def test_presets_use_exporter_enums_and_keep_unity_defaults(self):
        self.assertEqual(AXIS_PRESETS["unity"], {
            "axis_forward": "-Z", "axis_up": "Y", "apply_unit_scale": True,
            "apply_scale_options": "FBX_SCALE_UNITS", "bake_space_transform": True})
        for name, preset in AXIS_PRESETS.items():
            with self.subTest(name=name):
                self.assertIn(preset["axis_forward"], FBX_AXES)
                self.assertIn(preset["axis_up"], FBX_AXES)
                self.assertNotEqual(preset["axis_forward"][-1], preset["axis_up"][-1])
                self.assertIn(preset["apply_scale_options"], FBX_SCALES)
                self.assertTrue(set(USD_AXES[name]) <= USD_AXIS)
