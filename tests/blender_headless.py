"""Headless runtime start from an installed layout keeps Blender's own numpy."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import bpy

source = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(source))
from cavi_blender_mcp.client import BridgeClient

python = sys.argv[sys.argv.index("--") + 1]

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    site = root / "site-packages"
    shutil.copytree(source / "cavi_blender_mcp", site / "cavi_blender_mcp",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (site / "numpy").mkdir()
    (site / "numpy" / "__init__.py").write_text(
        "raise ImportError('server numpy shadows Blender numpy')\n")
    connection = root / "state" / "connection.json"
    env = dict(os.environ, CAVI_BLENDER_CONNECTION=str(connection),
               CAVI_BLENDER_WORKSPACE=str(root / "assets"),
               CAVI_BLENDER_BIN=bpy.app.binary_path)
    started = subprocess.run(
        [python, "-c", ("import sys; sys.path.insert(0, sys.argv[1]); "
                        "from cavi_blender_mcp.cli import main; sys.exit(main(sys.argv[2:]))"),
         str(site), "runtime", "start", "--background"],
        check=False, env=env, capture_output=True, text=True, timeout=60)
    assert started.returncode == 0, (started.stdout, started.stderr)
    launch = json.loads(started.stdout)
    assert launch["launch_requested"] and launch["background"], launch
    pid = launch["pid"]
    try:
        client = BridgeClient(connection)
        deadline = time.monotonic() + 60
        while True:
            try:
                client.call("scene_info", {"limit": 1}, timeout=5)
                break
            except ConnectionError:
                if time.monotonic() > deadline:
                    raise AssertionError(Path(launch["log"]).read_text()) from None
                time.sleep(0.5)
        report = client.call("inspect_mesh_quality", {"names": ["Cube"],
                                                      "checks": ["lightmap", "topology"]})
        checks = report["objects"][0]["checks"]
        assert "lightmap" in checks and checks["topology"]["non_manifold_edges"] == 0, report
        print(json.dumps({"headless_numpy": "passed", "pid": pid}))
    finally:
        os.kill(pid, signal.SIGTERM)
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            os.kill(pid, signal.SIGKILL)
