import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cavi_blender_mcp.client import OPERATIONS, BridgeClient, default_connection

ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_transport_has_no_code_execution_operation(self):
        self.assertNotIn("execute_code", OPERATIONS)
        with self.assertRaisesRegex(ValueError, "Unknown operation"):
            BridgeClient().call("execute_code", {"code": "print(1)"})

    def test_empty_connection_environment_uses_the_default_path(self):
        with patch.dict(os.environ, {"CAVI_BLENDER_CONNECTION": ""}):
            self.assertEqual(
                default_connection(),
                Path.home() / ".cavi/blender-mcp/connection.json",
            )

    def test_remote_host_is_rejected_before_connection(self):
        from cavi_blender_mcp.client import BridgeClient

        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "connection.json"
            config.write_text(json.dumps({"host": "example.com", "port": 80, "token": "x" * 64}))
            config.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "loopback"):
                BridgeClient(config).call("scene_info")

    @unittest.skipIf(os.name == "nt", "POSIX mode check")
    def test_shared_credential_file_is_rejected(self):
        from cavi_blender_mcp.client import BridgeClient

        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "connection.json"
            config.write_text("{}")
            config.chmod(0o644)
            with self.assertRaisesRegex(PermissionError, "private"):
                BridgeClient(config).call("scene_info")

    def test_write_path_cannot_escape_workspace(self):
        from cavi_blender_mcp.paths import destination

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "work"
            root.mkdir()
            with self.assertRaisesRegex(ValueError, "workspace"):
                destination(root, "../escaped.fbx", {".fbx"})
            link = root / "outside"
            link.symlink_to(root.parent, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "workspace"):
                destination(root, "outside/escaped.fbx", {".fbx"})

    def test_write_does_not_replace_existing_asset(self):
        from cavi_blender_mcp.paths import destination

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "asset.fbx"
            path.write_text("original")
            with self.assertRaises(FileExistsError):
                destination(Path(temp), "asset.fbx", {".fbx"})
            self.assertEqual(path.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
