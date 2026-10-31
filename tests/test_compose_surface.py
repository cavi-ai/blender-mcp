import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class ComposeSurfaceTests(unittest.TestCase):
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

    def test_mesh_composition_actions_map_to_owned_operations(self):
        calls = self.capture()
        asyncio.run(server.mesh_edit("boolean", "A", operand="B", operation="difference",
                                     lease_id="L"))
        asyncio.run(server.mesh_edit("join", "A", names=["B", "C"], lease_id="L"))
        asyncio.run(server.mesh_edit("separate", "A", lease_id="L"))
        asyncio.run(server.mesh_edit("mirror", "A", lease_id="L"))
        asyncio.run(server.mesh_edit("array", "A", count=3, offset=(0, 0, 2), lease_id="L"))
        asyncio.run(server.mesh_edit("solidify", "A", thickness=.05, lease_id="L"))
        ops = self.inner(calls)
        self.assertEqual([name for name, _ in ops], [
            "boolean_mesh", "join_meshes", "separate_mesh", "mirror_mesh", "array_mesh",
            "solidify_mesh"])
        self.assertTrue(all(operation == "owned_edit" for operation, _ in calls))
        self.assertEqual(ops[0][1], {
            "lease_id": "L", "name": "A", "operand": "B", "operation": "difference",
            "solver": "exact", "keep_operand": False, "self_intersection": False})
        self.assertEqual(ops[1][1], {"lease_id": "L", "name": "A", "names": ["B", "C"]})
        self.assertEqual(ops[2][1], {"lease_id": "L", "name": "A", "by": "loose_parts"})
        self.assertEqual(ops[3][1], {
            "lease_id": "L", "name": "A", "symmetry_axis": "X", "merge_distance": .001,
            "clipping": False})
        self.assertEqual(ops[4][1], {
            "lease_id": "L", "name": "A", "count": 3, "offset": (0, 0, 2)})
        self.assertEqual(ops[5][1], {
            "lease_id": "L", "name": "A", "thickness": .05, "offset": -1})

    def test_object_assembly_actions_map_to_owned_operations(self):
        calls = self.capture()
        asyncio.run(server.object_edit("duplicate", "A", new_name="B", lease_id="L"))
        asyncio.run(server.object_edit("parent", "A", new_name="B", lease_id="L"))
        asyncio.run(server.object_edit("unparent", "A", lease_id="L"))
        asyncio.run(server.object_edit("move_to_collection", "A", new_name="Props",
                                       lease_id="L"))
        ops = self.inner(calls)
        self.assertEqual([name for name, _ in ops], [
            "duplicate_object", "parent_object", "unparent_object", "move_to_collection"])
        self.assertTrue(all(operation == "owned_edit" for operation, _ in calls))
        self.assertEqual(ops[0][1], {
            "lease_id": "L", "name": "A", "new_name": "B", "count": 1,
            "offset": (0, 0, 0), "linked": False})
        self.assertEqual(ops[1][1], {"lease_id": "L", "name": "A", "new_name": "B"})
        self.assertEqual(ops[2][1], {"lease_id": "L", "name": "A"})
        self.assertEqual(ops[3][1], {
            "lease_id": "L", "name": "A", "new_name": "Props", "create": True})

    def test_composition_parameters_are_checked_before_the_bridge(self):
        calls = self.capture()
        for coroutine, message in [
            (server.mesh_edit("boolean", "A", operation="union"), "requires: operand"),
            (server.mesh_edit("boolean", "A", operand="B"), "requires: operation"),
            (server.mesh_edit("join", "A"), "requires: names"),
            (server.mesh_edit("join", "A", names=["B"], by="materials"),
             "does not accept: by"),
            (server.mesh_edit("mirror", "A", thickness=.1), "does not accept: thickness"),
            (server.mesh_edit("array", "A", count=2), "requires: offset"),
            (server.mesh_edit("solidify", "A"), "requires: thickness"),
            (server.object_edit("duplicate", "A"), "requires: new_name"),
            (server.object_edit("unparent", "A", new_name="B"), "does not accept: new_name"),
            (server.object_edit("move_to_collection", "A"), "requires: new_name"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                asyncio.run(coroutine)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
