"""Domain actions stay on the existing tools and refuse foreign parameters."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server
from cavi_blender_mcp.export_route import route_asset
from cavi_blender_mcp.operations import OPERATIONS, SLOW_OPERATIONS


class DomainSurfaceTests(unittest.TestCase):
    def capture(self, result):
        calls = []

        def call(operation, params):
            calls.append((operation, params))
            return result

        patcher = patch.object(server, "BridgeClient", return_value=SimpleNamespace(call=call))
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def test_geometry_graph_actions_keep_the_lease(self):
        calls = self.capture({"name": "Board", "modifiers": []})
        asyncio.run(server.geometry_nodes("create", "Board", new_name="Warp", lease_id="L"))
        asyncio.run(server.geometry_nodes(
            "add_node", "Board", modifier="Warp", new_name="Offset",
            node_type="GeometryNodeSetPosition", lease_id="L"))
        asyncio.run(server.geometry_nodes(
            "link", "Board", modifier="Warp", from_node="Group Input", from_socket="Geometry",
            to_node="Offset", to_socket="Geometry", lease_id="L"))
        self.assertEqual([item[1]["operation"] for item in calls], [
            "create_geometry_group", "add_geometry_node", "link_geometry_node"])
        self.assertEqual(calls[0][1]["params"]["new_name"], "Warp")
        self.assertEqual(calls[2][1]["params"]["to_socket"], "Geometry")
        for name in ("create_geometry_group", "add_geometry_node", "link_geometry_node"):
            self.assertIn(name, OPERATIONS)
            self.assertNotIn(name, SLOW_OPERATIONS)

    def test_geometry_graph_rejects_foreign_parameters(self):
        with self.assertRaises(ValueError):
            asyncio.run(server.geometry_nodes("create", "Board", new_name="Warp", inputs={"A": 1}))
        with self.assertRaises(ValueError):
            asyncio.run(server.geometry_nodes("link", "Board", modifier="Warp"))

    def test_object_domains_route_bounded_payloads(self):
        calls = self.capture({"name": "Board"})
        asyncio.run(server.object_edit(
            "rigid_body", "Board", collision_shape="BOX", frames=5, lease_id="L"))
        asyncio.run(server.object_edit("particles", "Board", count=12, seed=3, lease_id="L"))
        asyncio.run(server.object_edit(
            "hair", "Board", new_name="BoardHair",
            curves=[[(0, 0, 0), (0, 0, 1)], [(1, 0, 0), (1, 0, 1)]], lease_id="L"))
        asyncio.run(server.object_edit(
            "volume_to_mesh", "Board", source="Fog", resolution=16, lease_id="L"))
        operations = [item[1]["operation"] for item in calls]
        self.assertEqual(operations, [
            "rigid_body", "particle_system", "hair_curves", "volume_to_mesh"])
        self.assertEqual(calls[0][1]["params"]["frames"], 5)
        self.assertEqual(calls[0][1]["params"]["body"], "ACTIVE")
        self.assertEqual(calls[2][1]["params"]["curves"], [[[0, 0, 0], [0, 0, 1]], [[1, 0, 0], [1, 0, 1]]])
        self.assertIn("rigid_body", SLOW_OPERATIONS)
        self.assertNotIn("particle_system", SLOW_OPERATIONS)

    def test_sculpt_requires_a_bounded_strength(self):
        calls = self.capture({"name": "Board"})
        asyncio.run(server.mesh_edit(
            "sculpt_stroke", "Board", amount=0.5,
            vertices=[(0, 0, 1), (0, 0, 1), (0, 0, 1)], lease_id="L"))
        self.assertEqual(calls[0][1]["operation"], "sculpt_stroke")
        self.assertEqual(calls[0][1]["params"]["vertices"], [[0, 0, 1], [0, 0, 1], [0, 0, 1]])
        with self.assertRaisesRegex(ValueError, "Sculpt strength"):
            asyncio.run(server.mesh_edit(
                "sculpt_stroke", "Board", amount=2,
                vertices=[(0, 0, 1), (0, 0, 1), (0, 0, 1)]))
        self.assertIn("sculpt_stroke", OPERATIONS)

    def test_compositor_definition_is_complete(self):
        calls = self.capture({"name": "Compositor", "type": "COMPOSITOR"})
        asyncio.run(server.scene_edit("compositor", compositor=server.CompositorSpec(
            step="add_node", node="Blur", node_type="CompositorNodeBlur"), lease_id="L"))
        self.assertEqual(calls[0][1]["params"]["definition"], {
            "step": "add_node", "node": "Blur", "node_type": "CompositorNodeBlur"})
        with self.assertRaises(ValueError):
            server.CompositorSpec(step="link", from_node="Blur")

    def test_vdb_import_is_selected_by_suffix(self):
        route = route_asset("import", "cloud.vdb", {"name": "Cloud", "expected_sha256": None},
                            lease_id="L", pick=server.pick)
        self.assertEqual(route.operation, "import_vdb")
        self.assertIn("import_vdb", OPERATIONS)
        self.assertIn("import_vdb", SLOW_OPERATIONS)
