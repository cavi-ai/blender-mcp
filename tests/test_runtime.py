import errno
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class RuntimeStartTests(unittest.TestCase):
    def test_start_includes_bridge_factory_settings_and_disables_autoexec(self):
        from cavi_blender_mcp.runtime import start_runtime

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            binary = root / "blender"
            binary.write_text("binary")
            binary.chmod(0o700)
            project = root / "working.blend"
            project.write_bytes(b"project")
            calls = []

            def spawn(command, **kwargs):
                calls.append((command, kwargs))
                return SimpleNamespace(pid=123)

            with (
                patch.dict(os.environ, {"CAVI_BLENDER_BIN": str(binary),
                                       "CAVI_BLENDER_WORKSPACE": str(root),
                                       "CAVI_BLENDER_CONNECTION": str(root / "connection.json")}),
                patch("cavi_blender_mcp.runtime.subprocess.Popen", side_effect=spawn),
            ):
                result = start_runtime("working.blend")
            self.assertTrue(result["launch_requested"])
            self.assertFalse(result["connected"])
            command, kwargs = calls[0]
            self.assertEqual(command[:4], [str(binary), "--factory-startup", "--disable-autoexec", str(project)])
            self.assertEqual(command[-2], "--python")
            self.assertTrue(Path(command[-1]).is_file())
            self.assertEqual(kwargs["env"]["CAVI_BLENDER_WORKSPACE"], str(root))
            self.assertTrue(kwargs["start_new_session"])

    def test_connected_session_is_reused(self):
        from cavi_blender_mcp.runtime import start_runtime

        with (
            patch("cavi_blender_mcp.runtime.BridgeClient.call", return_value={"file": "", "objects": []}),
            patch("cavi_blender_mcp.runtime.subprocess.Popen", side_effect=AssertionError("launched")),
        ):
            result = start_runtime()
        self.assertTrue(result["connected"])
        self.assertFalse(result["launch_requested"])

    def test_a_timed_out_session_is_not_replaced(self):
        from cavi_blender_mcp.runtime import start_runtime

        def occupied(*args):
            raise ConnectionError("bridge timeout") from TimeoutError()

        with (
            patch("cavi_blender_mcp.runtime.BridgeClient.call", side_effect=occupied),
            patch("cavi_blender_mcp.runtime.subprocess.Popen", side_effect=AssertionError("launched")),
            self.assertRaisesRegex(RuntimeError, "unavailable"),
        ):
            start_runtime()

    def test_project_outside_workspace_is_refused(self):
        from cavi_blender_mcp.runtime import start_runtime

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, {"CAVI_BLENDER_WORKSPACE": folder}),
            self.assertRaisesRegex(ValueError, "workspace"),
        ):
            start_runtime("../other.blend")

    def test_start_does_not_replace_a_different_connected_project(self):
        from cavi_blender_mcp.runtime import start_runtime

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "requested.blend").write_bytes(b"project")
            with (
                patch.dict(os.environ, {"CAVI_BLENDER_WORKSPACE": str(root)}),
                patch("cavi_blender_mcp.runtime.BridgeClient.call", return_value={"file": "other.blend"}),
                patch("cavi_blender_mcp.runtime.subprocess.Popen", side_effect=AssertionError("launched")),
                self.assertRaisesRegex(RuntimeError, "different Blender project"),
            ):
                start_runtime("requested.blend")

    def test_missing_binary_does_not_launch_anything(self):
        from cavi_blender_mcp.runtime import start_runtime

        def refused(*args):
            raise ConnectionError("offline") from ConnectionRefusedError(errno.ECONNREFUSED, "refused")

        with (
            patch.dict(os.environ, {"CAVI_BLENDER_BIN": "/missing/blender"}),
            patch("cavi_blender_mcp.runtime.BridgeClient.call", side_effect=refused),
            patch("cavi_blender_mcp.runtime.subprocess.Popen", side_effect=AssertionError("launched")),
            self.assertRaisesRegex(FileNotFoundError, "Blender"),
        ):
            start_runtime()
