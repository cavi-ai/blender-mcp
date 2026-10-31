import asyncio
import sys
import unittest
from importlib.metadata import version
from types import SimpleNamespace
from unittest.mock import patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from cavi_blender_mcp import server
from cavi_blender_mcp.client import BridgeError, BridgeOperationError


def bridge_raising(exc):
    def call(operation, params):
        raise exc

    return patch.object(server, "BridgeClient", return_value=SimpleNamespace(call=call))


class AnticipatedErrorTests(unittest.TestCase):
    def assert_reports(self, name, arguments, text):
        with self.assertRaises(ToolError) as caught:
            asyncio.run(server.mcp.call_tool(name, arguments))
        self.assertNotIsInstance(caught.exception, UnexpectedToolError)
        self.assertIn(text, str(caught.exception))

    def test_validation_reaches_the_caller(self):
        self.assert_reports("object_edit", {"action": "rename", "name": "A"},
                            "rename requires: new_name")

    def test_bridge_failures_reach_the_caller(self):
        for exc in (BridgeOperationError("Object not found: A"),
                    BridgeError("Bridge response ID mismatch"),
                    ConnectionError("Blender bridge is not running"),
                    PermissionError("Connection file must be private")):
            with self.subTest(exc=type(exc).__name__), bridge_raising(exc):
                self.assert_reports("scene_info", {}, str(exc))

    def test_a_defect_keeps_its_details_on_the_server(self):
        with bridge_raising(TypeError("internal detail")), \
                self.assertRaises(UnexpectedToolError) as caught:
            asyncio.run(server.mcp.call_tool("scene_info", {}))
        self.assertNotIn("internal detail", str(caught.exception))

    def test_decorated_tools_stay_directly_callable(self):
        with self.assertRaisesRegex(ValueError, "requires: new_name"):
            asyncio.run(server.object_edit("rename", "A"))


class ServerInfoTests(unittest.TestCase):
    def test_reports_the_package_version(self):
        async def info():
            params = StdioServerParameters(command=sys.executable,
                                           args=["-m", "cavi_blender_mcp.server"])
            async with (
                stdio_client(params) as (reader, writer),
                ClientSession(reader, writer, read_timeout_seconds=60) as session,
            ):
                return (await session.initialize()).server_info

        result = asyncio.run(info())
        self.assertEqual((result.name, result.version),
                         ("cavi-blender-mcp", version("cavi-blender-mcp")))


if __name__ == "__main__":
    unittest.main()
