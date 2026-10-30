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

for name, kind, location in (("AAA_Rock", "sphere", (0, 6, 0)), ("AAA_Blob", "sphere", (3, 6, 0)),
                             ("AAA_Crate", "cube", (6, 6, 0)), ("AAA_Box", "cube", (9, 6, 0)),
                             ("AAA_Pair", "cube", (12, 6, 0)),
                             ("AAA_Pair_high", "sphere", (12, 6, 0))):
    add = (bpy.ops.mesh.primitive_uv_sphere_add if kind == "sphere"
           else bpy.ops.mesh.primitive_cube_add)
    add(location=location)
    bpy.context.object.name = bpy.context.object.data.name = name
bpy.data.objects["AAA_Box"].scale = (2, 2, 2)
pair = bpy.data.objects.new("AAA_SharedA", bpy.data.meshes["AAA_Crate"].copy())
bpy.context.scene.collection.objects.link(pair)
bpy.context.scene.collection.objects.link(bpy.data.objects.new("AAA_SharedB", pair.data))
props = bpy.data.collections.new("AAA_Props")
bpy.context.scene.collection.children.link(props)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.1, location=(0, 0, -20))
pebble = bpy.context.object
pebble.name = "AAA_Pebble"
for owner in list(pebble.users_collection):
    owner.objects.unlink(pebble)
props.objects.link(pebble)
bpy.ops.object.armature_add(location=(0, 0, -30))
rig = bpy.context.object
rig.name = "EvalRig"
skin = bpy.data.objects.new("EvalSkin", source.data.copy())
bpy.context.scene.collection.objects.link(skin)
skin.modifiers.new("Skin", "ARMATURE").object = rig
skin.vertex_groups.new(name="Bone").add(list(range(len(skin.data.vertices))), 1, "REPLACE")
for value in bpy.context.selected_objects:
    value.select_set(False)

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
bridge.serve_background()
