import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class PBRSurfaceTests(unittest.TestCase):
    def capture(self):
        calls = []

        def call(operation, params):
            calls.append((operation, params))
            return {"path": "/tmp/x.png", "workspace": "/w"}

        patcher = patch.object(server, "BridgeClient", return_value=SimpleNamespace(call=call))
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def test_material_defaults_are_resolved_by_the_bridge(self):
        calls = self.capture()
        asyncio.run(server.assign_material(["A"], "M", lease_id="L"))
        self.assertEqual(calls, [("owned_edit", {
            "operation": "assign_material",
            "params": {
                "names": ["A"], "material_name": "M", "base_color_texture": None,
                "base_color": None, "roughness": None, "metallic": None,
                "roughness_texture": None, "metallic_texture": None,
                "normal_texture": None, "normal_strength": None,
                "emission_texture": None, "emission_strength": None,
                "alpha_texture": None, "alpha_mode": None, "uv_scale": None,
                "uv_offset": None, "uv_rotation_degrees": None,
                "update_existing": False, "slot": 0, "lease_id": "L"}})])

    def test_material_maps_and_transform_are_forwarded(self):
        calls = self.capture()
        asyncio.run(server.assign_material(
            ["A", "B"], "PBR", base_color_texture="base.png", base_color=(.2, .4, .6, 1),
            roughness=.7, metallic=.3, roughness_texture="r.png",
            metallic_texture="m.png", normal_texture="n.png", normal_strength=1.5,
            emission_texture="e.png", emission_strength=2.5, alpha_texture="a.png",
            alpha_mode="clip", uv_scale=(2, 3), uv_offset=(.1, .2),
            uv_rotation_degrees=45, update_existing=True, slot=1, lease_id="L"))
        params = calls[0][1]["params"]
        self.assertEqual(calls[0][1]["operation"], "assign_material")
        self.assertEqual(params["base_color"], (.2, .4, .6, 1))
        self.assertEqual(params["roughness_texture"], "r.png")
        self.assertEqual(params["normal_strength"], 1.5)
        self.assertEqual(params["alpha_mode"], "clip")
        self.assertEqual(params["uv_scale"], (2, 3))
        self.assertEqual(params["uv_offset"], (.1, .2))
        self.assertEqual(params["uv_rotation_degrees"], 45)
        self.assertTrue(params["update_existing"])
        self.assertEqual(params["slot"], 1)

    def test_material_inputs_are_validated_before_the_bridge(self):
        calls = self.capture()
        for arguments in (
            {"names": ["A"], "material_name": "M", "alpha_mode": "cutout"},
            {"names": ["A"], "material_name": "M", "uv_scale": [1]},
            {"names": ["A"], "material_name": "M", "uv_offset": [1, 2, 3]},
            {"names": ["A"], "material_name": "M", "normal_strength": "1"},
            {"names": ["A"], "material_name": "M", "update_existing": "yes"},
            {"names": ["A"], "material_name": "M", "slot": 32},
        ):
            with self.assertRaisesRegex(Exception, "validation error"):
                asyncio.run(server.mcp.call_tool("assign_material", arguments))
        self.assertEqual(calls, [])

    def test_materials_check_is_forwarded_and_bounded(self):
        calls = self.capture()
        asyncio.run(server.inspect_mesh_quality(["A"], checks=["materials"]))
        self.assertEqual(calls[0][1]["checks"], ["materials"])
        with self.assertRaisesRegex(Exception, "materials"):
            asyncio.run(server.mcp.call_tool("inspect_mesh_quality", {
                "names": ["A"], "checks": ["explode"]}))


if __name__ == "__main__":
    unittest.main()
