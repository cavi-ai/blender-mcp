"""Tool discovery explains inputs and image tools return typed file receipts."""

import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jsonschema import Draft202012Validator
from mcp.server.mcpserver import Context

from cavi_blender_mcp import server

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC")


class CatalogQualityTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_rendered_file_keeps_the_outcome_unknown(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(
            server, 'BridgeClient',
            return_value=SimpleNamespace(call=lambda *args: {'path': str(Path(folder) / 'gone.png')}),
        ), self.assertLogs(level='ERROR'):
            reply = await server.mcp.call_tool('render_preview', {'path': 'gone.png'},
                                              Context(mcp_server=server.mcp))
        self.assertTrue(reply.is_error)
        self.assertEqual(reply.structured_content['error']['outcome'], 'unknown')
        self.assertFalse(reply.structured_content['error']['retry_safe'])

    async def test_mesh_offset_accepts_solidify_scalar_and_array_vector(self):
        tools = {tool.name: tool for tool in await server.mcp.list_tools()}
        validator = Draft202012Validator(tools['mesh_edit'].input_schema)
        validator.validate({'action': 'solidify', 'name': 'Plane', 'thickness': .1, 'offset': .5})
        validator.validate({'action': 'array', 'name': 'Cube', 'count': 2, 'offset': [1, 0, 0]})
        self.assertFalse(validator.is_valid({'action': 'array', 'name': 'Cube', 'offset': '1'}))
        self.assertFalse(validator.is_valid({'action': 'solidify', 'name': 'Plane', 'offset': 2}))

    async def test_every_tool_explains_its_inputs_and_result(self):
        for tool in await server.mcp.list_tools():
            with self.subTest(tool=tool.name):
                self.assertGreaterEqual(len(tool.description.strip()), 40)
                self.assertIsInstance(tool.output_schema, dict)
                for name, schema in tool.input_schema.get("properties", {}).items():
                    self.assertTrue(schema.get("description", "").strip(), f"{tool.name}.{name}")

    async def test_image_tools_keep_png_blocks_and_return_validated_receipts(self):
        tools = {tool.name: tool for tool in await server.mcp.list_tools()}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "preview.png"
            path.write_bytes(PNG)
            for name in ("render_preview", "review_sheet"):
                with self.subTest(tool=name), patch.object(
                    server, "BridgeClient",
                    return_value=SimpleNamespace(call=lambda *args: {"path": str(path)}),
                ):
                    reply = await server.mcp.call_tool(name, {"path": "preview.png"})
                    self.assertEqual(reply.structured_content, {
                        "path": str(path), "mime_type": "image/png"})
                    Draft202012Validator(tools[name].output_schema).validate(reply.structured_content)
                    images = [block for block in reply.content if block.type == "image"]
                    self.assertEqual(len(images), 1)
                    self.assertEqual(images[0].mime_type, "image/png")
                    self.assertEqual(base64.b64decode(images[0].data), PNG)
