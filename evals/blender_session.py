"""Disposable native fixture with event-driven bridge handling on Blender's main thread."""

import os
import socket
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

source = bpy.data.objects["Cube"]
material_target = bpy.data.objects.new("MaterialTarget", source.data.copy())
bpy.context.scene.collection.objects.link(material_target)
shared = bpy.data.objects.new("SharedTarget", source.data)
bpy.context.scene.collection.objects.link(shared)
uv_target = bpy.data.objects.new("UVTarget", source.data.copy())
bpy.context.scene.collection.objects.link(uv_target)
for layer in list(uv_target.data.uv_layers):
    uv_target.data.uv_layers.remove(layer)

dispatch = bridge.dispatch


def checked_dispatch(operation, params):
    result = dispatch(operation, params)
    if operation == "owned_edit":
        operation, params = params["operation"], params["params"]
    if operation == "shade_mesh":
        assert all(
            polygon.use_smooth == params["smooth"]
            for polygon in bpy.data.objects[params["name"]].data.polygons
        ), "Shading did not match the requested state"
    return result


bridge.dispatch = checked_dispatch
bridge.register()
with socket.socket(fileno=int(os.environ["CAVI_EVAL_READY_FD"])) as ready:
    ready.sendall(b"ready")
# Requests block on the same queue used by the production bridge. The fixture process
# is terminated by its owner after evaluation, without touching another Blender session.
for _ in iter(int, 1):
    with bridge._jobs.not_empty:
        bridge._jobs.not_empty.wait_for(lambda: bool(bridge._jobs.queue))
    bridge.pump()
