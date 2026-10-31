import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class LevelSurfaceTests(unittest.TestCase):
    def capture(self):
        calls = []

        def call(operation, params):
            calls.append((operation, params))
            return {"workspace": "/w"}

        patcher = patch.object(server, "BridgeClient", return_value=SimpleNamespace(call=call))
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def inner(self, calls):
        return [(params["operation"], params["params"]) for _, params in calls]

    def test_level_actions_map_to_owned_operations(self):
        calls = self.capture()
        asyncio.run(server.level_edit("terrain", "Terrain", lease_id="L"))
        asyncio.run(server.level_edit("place", lease_id="L", collection="Level", placements=[
            server.Placement(source="Rock", name="Rock_01", location=(1, 2, 3),
                             rotation_degrees=(0, 0, 90), scale=(2, 2, 2), linked=True)]))
        asyncio.run(server.level_edit("snap", names=["Rock_01"], terrain="Terrain",
                                      offset=0.5, align_to_normal=True, lease_id="L"))
        operations = self.inner(calls)
        self.assertEqual([name for name, _ in operations],
                         ["create_terrain", "place_objects", "snap_to_surface"])
        self.assertTrue(all(operation == "owned_edit" for operation, _ in calls))
        self.assertEqual(operations[0][1], {
            "lease_id": "L", "name": "Terrain", "size": (100.0, 100.0), "height": 10.0,
            "resolution": 128, "location": (0.0, 0.0, 0.0), "image": None, "seed": 0,
            "octaves": 4, "frequency": 4.0})
        self.assertEqual(operations[1][1], {
            "lease_id": "L", "collection": "Level", "placements": [{
                "source": "Rock", "name": "Rock_01", "location": (1, 2, 3),
                "rotation_degrees": (0, 0, 90), "scale": (2, 2, 2), "linked": True}]})
        self.assertEqual(operations[2][1], {
            "lease_id": "L", "names": ["Rock_01"], "terrain": "Terrain", "offset": 0.5,
            "align_to_normal": True})

    def test_level_parameters_are_checked_before_the_bridge(self):
        calls = self.capture()
        for coroutine, message in [
            (server.level_edit("terrain"), "requires: name"),
            (server.level_edit("place"), "requires: placements"),
            (server.level_edit("snap", names=["Rock"]), "requires: terrain"),
            (server.level_edit("place", placements=[], size=(1, 1)), "does not accept: size"),
            (server.level_edit("snap", names=["Rock"], terrain="T", name="X"),
             "does not accept: name"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                asyncio.run(coroutine)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
