import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class ResultContractTests(unittest.IsolatedAsyncioTestCase):
    def test_nested_decode_failure_keeps_transport_outcome_unknown(self):
        from mcp.server.mcpserver.exceptions import ToolError

        from cavi_blender_mcp.client import BridgeError
        from cavi_blender_mcp.contracts import failure
        transport = BridgeError("Invalid response; outcome unknown")
        transport.__cause__ = ValueError("Malformed response JSON")
        wrapper = ToolError("Inspect outputs")
        wrapper.__cause__ = transport
        result = failure("export", wrapper)
        self.assertEqual(result.structured_content["error"]["outcome"], "unknown")
        self.assertEqual(result.structured_content["error"]["next_action"],
                         "inspect_application_and_outputs")

    def test_schema_compaction_preserves_property_names_and_literal_values(self):
        from cavi_blender_mcp.contracts import compact_schema

        schema = {"title": "Arguments", "properties": {"title": {"title": "Title", "type": "string"}},
                  "const": {"title": "literal"}, "default": {"title": "default"}}
        compact = compact_schema(schema)
        self.assertIn("title", compact["properties"])
        self.assertEqual(compact["const"], schema["const"])
        self.assertEqual(compact["default"], schema["default"])

    async def test_catalog_omits_redundant_field_titles(self):
        from cavi_blender_mcp import server

        tools = await server.mcp.list_tools()
        for tool in tools:
            for field in tool.input_schema.get("properties", {}).values():
                self.assertNotIn("title", field)

    async def test_real_stdio_contracts_and_rejected_input(self):
        params = StdioServerParameters(command=sys.executable,
                                       args=["-m", "cavi_blender_mcp.server"])
        async with stdio_client(params) as (r, w), ClientSession(r, w) as client:
            await client.initialize()
            tools = {t.name: t for t in (await client.list_tools()).tools}
            for name in ("scene_info", "inspect_mesh_quality", "session_control", "asset_io"):
                self.assertTrue(tools[name].output_schema.get("properties"), name)
            rejected = await client.call_tool("scene_info", {"limit": 0})
            self.assertTrue(rejected.is_error)
            self.assertEqual(rejected.structured_content["error"]["code"], "INVALID_ARGUMENT")
            self.assertEqual(rejected.structured_content["error"]["outcome"], "rejected")
            self.assertFalse(rejected.structured_content["error"]["retry_safe"])

    def test_quality_contract_requires_units_and_preserves_extra_details(self):
        from cavi_blender_mcp.contracts import MeshQuality

        valid = {"scope": "static_source_current_frame", "frame": 1, "file": "",
                 "dirty": False, "density_unit": "pixels_per_meter", "scene_unit_meters": 1.,
                 "objects": [], "texture_resolution": [1024, 1024], "not_checked": [],
                 "custom_detail": "kept"}
        model = MeshQuality.model_validate(valid)
        self.assertEqual(model.model_dump()["custom_detail"], "kept")
        with self.assertRaises(ValueError):
            MeshQuality.model_validate({**valid, "density_unit": "pixels_per_cm"})
        with self.assertRaises(ValueError):
            MeshQuality.model_validate({k: v for k, v in valid.items() if k != "objects"})

    def test_import_result_keeps_object_details(self):
        from cavi_blender_mcp.contracts import AssetResult

        result = {"path": "prop.fbx", "objects": [{"name": "Prop", "type": "MESH"}]}
        self.assertEqual(AssetResult.model_validate(result).model_dump(), result)

    async def test_transport_failure_never_invites_mutation_retry(self):
        from mcp.server.mcpserver.exceptions import ToolError

        from cavi_blender_mcp.contracts import failure

        try:
            raise ConnectionError("Outcome may be unknown")
        except ConnectionError as cause:
            error = ToolError("Inspect the scene")
            error.__cause__ = cause
        result = failure("object_edit", error)
        self.assertEqual(result.structured_content["error"]["outcome"], "unknown")
        self.assertFalse(result.structured_content["error"]["retry_safe"])
