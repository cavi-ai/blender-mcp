"""Disposable native fixture with event-driven bridge handling on Blender's main thread."""

import os
import socket
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp.presets import AXIS_PRESETS

source = bpy.data.objects["Cube"]
material_target = bpy.data.objects.new("MaterialTarget", source.data.copy())
bpy.context.scene.collection.objects.link(material_target)
shared = bpy.data.objects.new("SharedTarget", source.data)
bpy.context.scene.collection.objects.link(shared)
uv_target = bpy.data.objects.new("UVTarget", source.data.copy())
bpy.context.scene.collection.objects.link(uv_target)
for layer in list(uv_target.data.uv_layers):
    uv_target.data.uv_layers.remove(layer)
pbr_target = bpy.data.objects.new("PBRTarget", source.data.copy())
bpy.context.scene.collection.objects.link(pbr_target)
pbr_no_uv = bpy.data.objects.new("PBRNoUV", source.data.copy())
bpy.context.scene.collection.objects.link(pbr_no_uv)
for layer in list(pbr_no_uv.data.uv_layers):
    pbr_no_uv.data.uv_layers.remove(layer)
pbr_custom = bpy.data.objects.new("PBRCustomTarget", source.data.copy())
bpy.context.scene.collection.objects.link(pbr_custom)
pbr_custom.data.materials.append(bpy.data.materials.new("PBRCustom"))
bpy.ops.mesh.primitive_uv_sphere_add(location=(60, 0, 0))
bpy.context.object.name = bpy.context.object.data.name = "RigMesh"
bpy.ops.mesh.primitive_uv_sphere_add(location=(60, 5, 0))
bpy.context.object.name = bpy.context.object.data.name = "RigMeshUnbound"
bpy.ops.mesh.primitive_cube_add(location=(70, 0, 0))
bpy.context.object.name = bpy.context.object.data.name = "BakeLow"
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.2,
                                     location=(70, 0, 0))
bpy.context.object.name = bpy.context.object.data.name = "BakeHigh"
bpy.ops.object.light_add(type="POINT", location=(73, -3, 4))
bpy.context.object.data.energy = 1000
bpy.ops.mesh.primitive_cube_add(location=(70, 5, 0))
bpy.context.object.name = bpy.context.object.data.name = "BakeNoUV"
for layer in list(bpy.data.objects["BakeNoUV"].data.uv_layers):
    bpy.data.objects["BakeNoUV"].data.uv_layers.remove(layer)
bpy.ops.mesh.primitive_cube_add(location=(80, 0, 0))
morph = bpy.context.object
morph.name = morph.data.name = "MorphSource"
morph.shape_key_add(name="Basis")
expand = morph.shape_key_add(name="Expand")
for point in expand.data:
    point.co.x *= 1.5
for value in bpy.context.selected_objects:
    value.select_set(False)
morph.select_set(True)
bpy.context.view_layer.objects.active = morph
result = bpy.ops.export_scene.gltf(
    filepath=str(Path(os.environ["CAVI_BLENDER_WORKSPACE"]) / "morph.glb"),
    export_format="GLB", use_selection=True, export_apply=True,
    export_morph=True, export_morph_animation=False)
assert "FINISHED" in result
for value in bpy.context.selected_objects:
    value.select_set(False)
morph_key = morph.data.shape_keys.key_blocks["Expand"]
morph_key.value = 0
morph_key.keyframe_insert("value", frame=1)
morph_key.value = 1
morph_key.keyframe_insert("value", frame=11)
morph.select_set(True)
bpy.context.view_layer.objects.active = morph
result = bpy.ops.export_scene.gltf(
    filepath=str(Path(os.environ["CAVI_BLENDER_WORKSPACE"]) / "morph-anim.glb"),
    export_format="GLB", use_selection=True, export_apply=True,
    export_animations=True, export_morph=True, export_morph_animation=True,
    export_animation_mode="ACTIONS")
assert "FINISHED" in result
for value in bpy.context.selected_objects:
    value.select_set(False)

for name, kind, location in (("AAA_Rock", "sphere", (0, 6, 0)), ("AAA_Blob", "sphere", (3, 6, 0)),
                             ("AAA_Crate", "cube", (6, 6, 0)), ("AAA_Box", "cube", (9, 6, 0)),
                             ("AAA_Pair", "cube", (12, 6, 0)),
                             ("AAA_Pair_high", "sphere", (12, 6, 0)),
                             ("CMP_A", "cube", (20, 0, 0)), ("CMP_B", "cube", (20.5, 0, 0)),
                             ("CMP_C", "cube", (24, 0, 0)), ("CMP_D", "cube", (27, 0, 0)),
                             ("CMP_M", "cube", (30, 0, 0)), ("CMP_N", "cube", (33, 0, 0)),
                             ("CMP_Parent", "cube", (36, 0, 0)),
                             ("CMP_Child", "cube", (39, 0, 0))):
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
bpy.ops.mesh.primitive_plane_add(location=(42, 0, 0))
bpy.context.object.name = bpy.context.object.data.name = "CMP_Plane"
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
rig.select_set(True)
skin.select_set(True)
bpy.context.view_layer.objects.active = rig
workspace = Path(os.environ["CAVI_BLENDER_WORKSPACE"])
result = bpy.ops.export_scene.gltf(
    filepath=str(workspace / "rigged.glb"), export_format="GLB", use_selection=True,
    export_skins=True, export_animations=False, export_apply=False)
assert "FINISHED" in result
result = bpy.ops.export_scene.fbx(
    filepath=str(workspace / "rigged.fbx"), use_selection=True,
    object_types={"MESH", "ARMATURE"}, add_leaf_bones=False, bake_anim=False,
    global_scale=1, **AXIS_PRESETS["unity"])
assert "FINISHED" in result
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
