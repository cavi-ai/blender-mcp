import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server
from cavi_blender_mcp.client import MAX_TIMEOUT, operation_timeout


class BakeSurfaceTests(unittest.TestCase):
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

    def test_normal_defaults_map_to_an_owned_bake(self):
        calls = self.capture()
        asyncio.run(server.bake("normal", "Low", "out.png", high=["High"], lease_id="L"))
        operation, params = self.inner(calls)[0]
        self.assertEqual(operation, "bake_png")
        self.assertEqual(params, {
            "lease_id": "L", "map": "normal", "name": "Low", "path": "out.png",
            "high": ["High"], "resolution": 1024, "samples": 16, "margin": 4,
            "cage_extrusion": .01, "max_ray_distance": .1, "normal_space": "tangent",
            "uv_layer": None, "isolate": True, "bit_depth": 16})
        self.assertEqual(calls[0][0], "owned_edit")

    def test_ao_defaults_and_options(self):
        calls = self.capture()
        asyncio.run(server.bake("ao", "Low", "ao.png", resolution=128, samples=2,
                                margin=2, isolate=False, lease_id="L"))
        self.assertEqual(self.inner(calls)[0][1], {
            "lease_id": "L", "map": "ao", "name": "Low", "path": "ao.png", "high": None,
            "resolution": 128, "samples": 2, "margin": 2, "cage_extrusion": .01,
            "max_ray_distance": .1, "uv_layer": None, "isolate": False, "bit_depth": 16})

    def test_curvature_and_lightmap_defaults(self):
        calls = self.capture()
        asyncio.run(server.bake("curvature", "Low", "curvature.png", lease_id="L"))
        asyncio.run(server.bake("lightmap", "Low", "lightmap.png", samples=4,
                                lease_id="L"))
        operations = self.inner(calls)
        self.assertEqual(operations[0], ("bake_png", {
            "lease_id": "L", "map": "curvature", "name": "Low",
            "path": "curvature.png", "resolution": 1024, "samples": 16,
            "margin": 4, "uv_layer": None, "isolate": True, "bit_depth": 16}))
        self.assertEqual(operations[1], ("bake_png", {
            "lease_id": "L", "map": "lightmap", "name": "Low",
            "path": "lightmap.png", "resolution": 1024, "samples": 4,
            "margin": 4, "uv_layer": None, "isolate": True, "bit_depth": 16}))

    def test_explicit_output_precision_reaches_the_owned_operation(self):
        calls = self.capture()
        for depth in (8, 16):
            asyncio.run(server.bake("normal", "Low", f"n{depth}.png",
                                    bit_depth=depth, lease_id="L"))
        self.assertEqual([p['bit_depth'] for _, p in self.inner(calls)], [8, 16])

    def test_invalid_precision_is_rejected_before_the_bridge(self):
        calls = self.capture()
        for depth in (7, 32, True, "16"):
            with self.subTest(depth=depth), self.assertRaisesRegex(Exception, "validation"):
                asyncio.run(server.mcp.call_tool("bake", {
                    "map": "normal", "name": "Low", "path": "n.png", "bit_depth": depth}))
        self.assertEqual(calls, [])

    def test_high_and_cage_apply_only_to_normal_and_ao(self):
        calls = self.capture()
        for arguments, message in [
            ({"map": "curvature", "name": "Low", "path": "c.png", "high": ["High"]},
             "does not accept: high"),
            ({"map": "lightmap", "name": "Low", "path": "l.png",
             "cage_extrusion": 0.1}, "does not accept: cage_extrusion"),
            ({"map": "curvature", "name": "Low", "path": "c.png",
             "normal_space": "object"}, "does not accept: normal_space"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(Exception, message):
                asyncio.run(server.mcp.call_tool("bake", arguments))
        self.assertEqual(calls, [])

    def test_bake_parameters_are_bounded(self):
        calls = self.capture()
        for arguments, message in [
            ({"map": "ao", "name": "Low", "path": "a.png", "normal_space": "tangent"},
             "does not accept: normal_space"),
            ({"map": "normal", "name": "Low", "path": "a.png", "resolution": 32},
             "validation"),
            ({"map": "ao", "name": "Low", "path": "a.png", "samples": 0},
             "validation"),
            ({"map": "ao", "name": "Low", "path": "a.png", "margin": 65},
             "validation"),
            ({"map": "ao", "name": "Low", "path": "a.png", "cage_extrusion": 2},
             "validation"),
            ({"map": "ao", "name": "Low", "path": "a.png", "max_ray_distance": 11},
             "validation"),
            ({"map": "normal", "name": "Low", "path": "a.png", "normal_space": "world"},
             "validation"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(Exception, message):
                asyncio.run(server.mcp.call_tool("bake", arguments))
        self.assertEqual(calls, [])

    def test_old_bridge_is_refused_before_a_low_precision_write(self):
        effects = []

        def legacy(operation, params):
            self.assertEqual(operation, "owned_edit")
            if params["operation"] == "bake_png":
                raise RuntimeError("Unknown operation: bake_png")
            effects.append("8-bit file written")
            return {}

        with (patch.object(server, "BridgeClient", return_value=SimpleNamespace(call=legacy)),
              self.assertRaisesRegex(RuntimeError, "bake_png")):
            asyncio.run(server.bake("normal", "Low", "n.png", lease_id="L"))
        self.assertEqual(effects, [])

    def test_bake_uses_the_longest_timeout(self):
        self.assertEqual(operation_timeout("owned_edit", {"operation": "bake_png"}),
                         MAX_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
