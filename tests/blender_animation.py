"""Native pose, action, animation export and re-import checks."""

import json
import math
import struct
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

folder = tempfile.TemporaryDirectory()
root = Path(folder.name)
bridge._workspace = root
state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "animation-fixture",
    "expected_project": state["project_id"]})["lease_id"]


def edit(operation, **params):
    return bridge.dispatch("owned_edit", {"operation": operation,
                                          "params": {**params, "lease_id": lease}})


def refused(operation, message, **params):
    try:
        edit(operation, **params)
    except (ValueError, RuntimeError) as exc:
        assert message in str(exc), exc
    else:
        raise AssertionError(f"{operation} accepted {params}")


def glb_document(path):
    data = path.read_bytes()
    offset, chunks = 12, []
    while offset + 8 <= len(data):
        length, kind = struct.unpack("<II", data[offset:offset + 8])
        offset += 8
        chunks.append((kind, data[offset:offset + length]))
        offset += length
    return json.loads(chunks[0][1])


try:
    edit("create_armature", name="AnimRig", bones=[
        {"name": "Root", "head": [0, 0, -1], "tail": [0, 0, 0]},
        {"name": "Spine", "parent": "Root", "head": [0, 0, 0], "tail": [0, 0, 1],
         "connect": True},
    ])
    bpy.ops.mesh.primitive_uv_sphere_add(location=(0, 0, 0))
    mesh = bpy.context.object
    mesh.name = mesh.data.name = "AnimMesh"
    edit("bind_skin", name="AnimRig", names=["AnimMesh"])
    rig = bpy.data.objects["AnimRig"]

    created = edit("keyframe_rig", name="AnimRig", action_name="Walk", keyframes=[
        {"frame": 1, "poses": [
            {"bone": "Root", "rotation_degrees": [0, 0, 0]},
            {"bone": "Spine", "rotation_degrees": [0, 0, 0]}]},
        {"frame": 11, "poses": [
            {"bone": "Root", "rotation_degrees": [0, 0, 45]},
            {"bone": "Spine", "location": [0, 0, 1]}]},
    ])
    action = bpy.data.actions["Walk"]
    assert created["action"] == "Walk" and created["frame_range"] == [1, 11], created
    assert created["action_slot"] and created["keyed_bones"] == ["Root", "Spine"]
    assert rig.animation_data.action == action
    assert action.use_frame_range and action.frame_start == 1 and action.frame_end == 11
    assert action.get("cavi_rig_action") == "AnimRig"
    assert len(action.layers) == 1 and len(action.layers[0].strips) == 1
    bpy.context.scene.frame_set(11)
    bpy.context.view_layer.update()
    assert abs(math.degrees(rig.pose.bones["Root"].rotation_euler.z) - 45) < 1e-4
    clips = bridge.dispatch("inspect_rig", {"armature": "AnimRig", "meshes": ["AnimMesh"]})
    assert clips["clips"][0]["name"] == "Walk" and clips["clips"][0]["frame_range"] == [1, 11]

    posed = edit("pose_rig", name="AnimRig", frame=5, reset=True,
                 poses=[{"bone": "Spine", "rotation_degrees": [30, 0, 0]}])
    assert posed["frame"] == 5 and posed["posed"] == ["Spine"] and posed["reset"]
    assert abs(math.degrees(rig.pose.bones["Spine"].rotation_euler.x) - 30) < 1e-4
    cleared = edit("clear_pose", name="AnimRig", frame=5)
    assert cleared["reset_bones"] == 2
    for bone in rig.pose.bones:
        assert tuple(round(value, 6) for value in bone.location) == (0, 0, 0)
        assert tuple(round(value, 6) for value in bone.scale) == (1, 1, 1)

    refused("keyframe_rig", "already exists", name="AnimRig", action_name="Walk",
            keyframes=[{"frame": 1, "poses": [{"bone": "Root",
                                               "rotation_degrees": [0, 0, 0]}]}])
    refused("keyframe_rig", "does not exist", name="AnimRig", action_name="MissingBone",
            keyframes=[{"frame": 1, "poses": [{"bone": "Missing",
                                               "rotation_degrees": [0, 0, 0]}]}])
    refused("keyframe_rig", "increasing", name="AnimRig", action_name="Backwards",
            keyframes=[{"frame": 2, "poses": [{"bone": "Root",
                                               "rotation_degrees": [0, 0, 0]}]},
                       {"frame": 1, "poses": [{"bone": "Root",
                                               "rotation_degrees": [0, 0, 1]}]}])
    refused("pose_rig", "needs rotation", name="AnimRig", poses=[{"bone": "Root"}])
    refused("pose_rig", "positive", name="AnimRig",
            poses=[{"bone": "Root", "scale": [0, 1, 1]}])
    many = [{"frame": index + 1, "poses": [{"bone": "Root",
                                            "rotation_degrees": [0, 0, index]}]}
            for index in range(33)]
    refused("keyframe_rig", "1 to 32", name="AnimRig", action_name="TooMany",
            keyframes=many)

    exported = bridge.dispatch("export_asset", {
        "names": ["AnimMesh"], "path": "anim.fbx", "animations": True, "lease_id": lease})
    assert exported["bytes"] > 0
    assert exported["armatures"] == ["AnimRig"] and exported["skinned_meshes"] == ["AnimMesh"]
    assert exported["animations"][0]["name"] == "Walk", exported
    assert exported["animations"][0]["frame_range"] == [1, 11]
    glb = bridge.dispatch("export_asset", {
        "names": ["AnimMesh"], "path": "anim.glb", "animations": True, "lease_id": lease})
    assert glb["bytes"] > 0
    document = glb_document(root / "anim.glb")
    assert document.get("animations") and document.get("skins"), document.keys()

    refused("export_asset", "FBX and GLB", names=["AnimMesh"], path="anim.usd",
            animations=True)
    bpy.ops.mesh.primitive_cube_add(location=(5, 0, 0))
    bpy.context.object.name = "Unskinned"
    refused("export_asset", "armature", names=["Unskinned"], path="bad.fbx",
            animations=True)
    refused("export_asset", "cannot combine", names=["AnimMesh"], path="lod.fbx",
            animations=True, lods=True)
    refused("export_asset", "cannot combine", names=["AnimMesh"], path="col.fbx",
            animations=True, collision=True)
    refused("export_asset", "cannot combine", names=["AnimMesh"], path="inst.fbx",
            animations=True, preserve_instances=True)

    before_actions, before_objects = set(bpy.data.actions), set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(root / "anim.fbx"))
    new_actions = set(bpy.data.actions) - before_actions
    new_objects = set(bpy.data.objects) - before_objects
    assert any(item.type == "ARMATURE" for item in new_objects)
    assert new_actions and max(action.frame_range[1] for action in new_actions) >= 11

    before_actions, before_objects = set(bpy.data.actions), set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(root / "anim.glb"))
    new_actions = set(bpy.data.actions) - before_actions
    new_objects = set(bpy.data.objects) - before_objects
    assert any(item.type == "ARMATURE" for item in new_objects)
    assert new_actions

    try:
        bridge.dispatch("export_asset", {"names": ["AnimMesh"], "path": "unowned.fbx",
                                         "animations": True})
        raise AssertionError("Unowned animated export succeeded")
    except RuntimeError as exc:
        assert "lease_id" in str(exc)

    print(json.dumps({
        "action": created["action"],
        "frames": created["frame_range"],
        "keyed_bones": created["keyed_bones"],
        "fbx_bytes": exported["bytes"],
        "glb_bytes": glb["bytes"],
        "glb_animations": len(document["animations"]),
        "glb_skins": len(document["skins"]),
    }))
finally:
    folder.cleanup()
