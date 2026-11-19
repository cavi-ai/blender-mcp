"""Start a dedicated Blender bridge without replacing an occupied session."""

import os
import secrets
import subprocess
import tempfile
from pathlib import Path

from cavi_mcp_core import apps
from cavi_mcp_core import workspace as core_workspace

from . import process_launch
from .client import BridgeClient

BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")


def workspace_root():
    """The configured workspace; ``CAVI_BLENDER_WORKSPACE`` must be an absolute path."""
    return core_workspace.root("CAVI_BLENDER_WORKSPACE",
                               default=Path.home() / "Documents/CaviBlender")


def blender_executable():
    """Blender from ``CAVI_BLENDER_BIN``, the macOS app or ``PATH``."""
    executable = apps.find_executable(BLENDER, "blender", "CAVI_BLENDER_BIN", None).path
    if executable is None or not os.access(executable, os.X_OK):
        raise FileNotFoundError("Blender is unavailable; set CAVI_BLENDER_BIN to its executable")
    return str(executable)


def start_runtime(project=None, background=False):
    owned = bool(os.environ.get(process_launch.OWNER))
    if owned and not background:
        raise RuntimeError("Supervised Blender launches require background mode")
    workspace = workspace_root()
    source = None if project is None else core_workspace.input_file(workspace, project, {".blend"})
    client = BridgeClient()
    try:
        scene = client.call("scene_info", {"limit": 1})
    except ConnectionError as exc:
        confirmed_offline = isinstance(exc.__cause__, (FileNotFoundError, ConnectionRefusedError))
        if not confirmed_offline:
            raise RuntimeError(
                "Cannot confirm that the bridge is unavailable; inspect status before starting"
            ) from exc
    else:
        if owned:
            raise RuntimeError("A Blender bridge is already connected; inspect its existing ownership")
        if source is not None and scene.get("file") != str(source):
            raise RuntimeError("A different Blender project is connected; it was left untouched")
        return {"connected": True, "launch_requested": False,
                "workspace": scene.get("workspace"), "file": scene.get("file"),
                "version": scene.get("version"), "bridge": scene.get("bridge"),
                "object_count": scene.get("total", len(scene.get("objects", [])))}
    executable = blender_executable()
    connection = client.config.expanduser().resolve()
    connection.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    workspace.mkdir(parents=True, exist_ok=True)
    command = [executable, *(["--background"] if background else []),
               "--factory-startup", "--disable-autoexec"]
    if source is not None:
        command.append(str(source))
    command.extend(["--python-exit-code", "1", "--python", str(Path(__file__).with_name("bootstrap.py"))])
    env = dict(os.environ, CAVI_BLENDER_CONNECTION=str(connection),
               CAVI_BLENDER_WORKSPACE=str(workspace))
    env = process_launch.environment(env)
    native_command, launch_id = command, secrets.token_hex(16) if owned else None
    command = process_launch.command(command, env=env,launch_id=launch_id)
    fd, log_path = tempfile.mkstemp(prefix="launch-", suffix=".log", dir=connection.parent)
    with os.fdopen(fd, "wb") as log:
        process = subprocess.Popen(
            command, env=env, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
    if owned:
        process_launch.wait_registered(process,env=env,launch_id=launch_id,args=native_command)
    return {"connected": False, "launch_requested": True, "pid": process.pid,
            "background": background,
            "workspace": str(workspace), "log": log_path,
            "reason": "Blender launch requested; inspect runtime status after startup"}
