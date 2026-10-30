"""Exercise the runtime CLI against a disposable native Blender scene."""

import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

python = sys.argv[sys.argv.index("--") + 1]


def cli(action, requests):
    process = subprocess.Popen(
        [str(Path(python).with_name("cavi-blender-mcp")), "runtime", action],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(requests):
            with bridge._jobs.not_empty:
                if not bridge._jobs.not_empty.wait_for(lambda: bool(bridge._jobs.queue), timeout=10):
                    raise AssertionError("CLI did not send its expected bridge request")
            bridge.pump()
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, (stdout, stderr)
        return json.loads(stdout)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    os.environ["CAVI_BLENDER_CONNECTION"] = str(root / "connection.json")
    os.environ["CAVI_BLENDER_WORKSPACE"] = str(root / "assets")
    bridge.register()
    try:
        bpy.data.objects["Cube"].location.z = 3.25
        before = bridge.dispatch("scene_info", {})
        dirty = bpy.data.is_dirty
        selection = [item.name for item in bpy.context.selected_objects]
        old_config = json.loads((root / "connection.json").read_text())
        old_runtime = bridge.dispatch("runtime_status", {})
        status = cli("status", 1)
        assert status["pid"] == os.getpid()
        result = cli("restart", 2)
        new_config = json.loads((root / "connection.json").read_text())
        assert result["connected"] is True
        assert result["pid"] == old_runtime["pid"] == os.getpid()
        assert result["generation"] != old_runtime["generation"]
        assert new_config["port"] != old_config["port"]
        assert new_config["token"] != old_config["token"]
        assert bridge.dispatch("scene_info", {}) == before
        assert bpy.data.is_dirty == dirty
        assert [item.name for item in bpy.context.selected_objects] == selection
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", old_config["port"])) != 0
        assert cli("status", 1)["generation"] == result["generation"]
        current_config = (root / "connection.json").read_bytes()
        with patch.object(bridge.os, "replace", side_effect=OSError("read-only connection directory")):
            try:
                bridge.dispatch("runtime_restart", {})
            except OSError:
                pass
            else:
                raise AssertionError("Failed connection publication was accepted")
        assert (root / "connection.json").read_bytes() == current_config
        assert cli("status", 1)["generation"] == result["generation"]
        assert bridge.dispatch("scene_info", {}) == before
        print(json.dumps({"native_runtime": "passed", "scene_preserved": True,
                          "pid_preserved": True, "credentials_rotated": True,
                          "publication_failure_preserves_connection": True}))
    finally:
        bridge.unregister()
