"""Start a dedicated Blender bridge without replacing an occupied session."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .client import BridgeClient


def start_runtime(project=None):
    workspace = Path(os.environ.get(
        "CAVI_BLENDER_WORKSPACE", Path.home() / "Documents/CaviBlender"
    )).expanduser().resolve()
    source = None
    if project is not None:
        source = (workspace / project).resolve()
        if Path(project).is_absolute() or not source.is_relative_to(workspace):
            raise ValueError("Project must stay inside the workspace")
        if source.suffix.lower() != ".blend" or not source.is_file():
            raise ValueError("Project must be an existing workspace .blend file")
    client = BridgeClient()
    try:
        scene = client.call("scene_info")
    except ConnectionError as exc:
        confirmed_offline = isinstance(exc.__cause__, (FileNotFoundError, ConnectionRefusedError))
        if not confirmed_offline:
            raise RuntimeError(
                "Cannot confirm that the bridge is unavailable; inspect status before starting"
            ) from exc
    else:
        if source is not None and scene.get("file") != str(source):
            raise RuntimeError("A different Blender project is connected; it was left untouched")
        return {"connected": True, "launch_requested": False,
                "workspace": scene.get("workspace"), "file": scene.get("file"),
                "version": scene.get("version"), "object_count": len(scene.get("objects", []))}
    configured = os.environ.get("CAVI_BLENDER_BIN")
    default = "/Applications/Blender.app/Contents/MacOS/Blender" if sys.platform == "darwin" else ""
    executable = configured or shutil.which("blender") or default
    if not executable or not Path(executable).is_file() or not os.access(executable, os.X_OK):
        raise FileNotFoundError("Blender is unavailable; set CAVI_BLENDER_BIN to its executable")
    connection = client.config.expanduser().resolve()
    connection.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    workspace.mkdir(parents=True, exist_ok=True)
    command = [executable, "--factory-startup", "--disable-autoexec"]
    if source is not None:
        command.append(str(source))
    command.extend(["--python", str(Path(__file__).with_name("bootstrap.py"))])
    env = dict(os.environ, CAVI_BLENDER_CONNECTION=str(connection),
               CAVI_BLENDER_WORKSPACE=str(workspace))
    fd, log_path = tempfile.mkstemp(prefix="launch-", suffix=".log", dir=connection.parent)
    with os.fdopen(fd, "wb") as log:
        process = subprocess.Popen(
            command, env=env, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
    return {"connected": False, "launch_requested": True, "pid": process.pid,
            "workspace": str(workspace), "log": log_path,
            "reason": "Blender launch requested; inspect runtime status after startup"}
