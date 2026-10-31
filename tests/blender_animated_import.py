"""Native animated GLB import and export round-trip checks."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

folder = tempfile.TemporaryDirectory()
root = Path(folder.name)
bridge._workspace = root
state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "animated-import-fixture",
    "expected_project": state["project_id"]})["lease_id"]


def edit(operation, **params):
    return bridge.dispatch("owned_edit", {"operation": operation,
                                          "params": {**params, "lease_id": lease}})


try:
    edit("create_armature", name="SourceRig", bones=[
        {"name": "Root", "head": [0, 0, -1], "tail": [0, 0, 0]},
        {"name": "Spine", "parent": "Root", "head": [0, 0, 0], "tail": [0, 0, 1],
         "connect": True},
    ])
    bpy.ops.mesh.primitive_uv_sphere_add(location=(0, 0, 0))
    mesh = bpy.context.object
    mesh.name = mesh.data.name = "SourceMesh"
    edit("bind_skin", name="SourceRig", names=["SourceMesh"])
    edit("keyframe_rig", name="SourceRig", action_name="Walk", keyframes=[
        {"frame": 1, "poses": [{"bone": "Spine", "rotation_degrees": [0, 0, 0]}]},
        {"frame": 11, "poses": [{"bone": "Spine", "rotation_degrees": [0, 0, 45]}]},
    ])
    bridge.dispatch("export_asset", {
        "names": ["SourceMesh"], "path": "walk.glb", "animations": True, "lease_id": lease})

    imported = bridge.dispatch("import_mesh", {
        "path": "walk.glb", "name": "AnimatedImport", "lease_id": lease})
    assert imported["animations"], imported
    assert imported["armatures"] and imported["skinned_meshes"], imported
    animation = imported["animations"][0]
    assert animation["frame_range"] == [1, 11], animation
    imported_rig = bpy.data.objects[imported["armatures"][0]]
    imported_mesh = bpy.data.objects[imported["skinned_meshes"][0]]
    action = bpy.data.actions[animation["name"]]
    assert list(action.frame_range) == [1, 11], action.frame_range
    assert imported_rig.type == "ARMATURE" and len(imported_rig.data.bones) == 2
    assert imported_mesh.find_armature() == imported_rig

    inspected = bridge.dispatch("inspect_rig", {
        "armature": imported_rig.name, "meshes": [imported_mesh.name]})
    assert any(clip["name"] == action.name for clip in inspected["clips"]), inspected["clips"]

    for suffix in ("fbx", "glb"):
        exported = bridge.dispatch("export_asset", {
            "names": [imported_mesh.name], "path": f"reexport.{suffix}",
            "animations": True, "lease_id": lease})
        assert exported["bytes"] > 0
        assert any(item["name"] == action.name for item in exported["animations"])

    try:
        bridge.dispatch("import_mesh", {
            "path": "walk.glb", "name": "AnimatedImport", "lease_id": lease})
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("Duplicate animated import name was accepted")

    pools = ["objects", "armatures", "actions", "meshes", "materials", "images", "collections"]
    snapshot = {key: set(getattr(bpy.data, key)) for key in pools}
    real_import = bridge._load_glb

    def partially_import(path):
        real_import(path)
        raise RuntimeError("simulated failure after animated import")

    with patch.object(bridge, "_load_glb", side_effect=partially_import):
        try:
            bridge.dispatch("import_mesh", {
                "path": "walk.glb", "name": "FailedAnimated", "lease_id": lease})
        except RuntimeError:
            pass
        else:
            raise AssertionError("Failed animated import was accepted")
    for key in pools:
        assert set(getattr(bpy.data, key)) == snapshot[key], f"Failed import leaked {key}"

    print(json.dumps({
        "armature": imported_rig.name,
        "bones": len(imported_rig.data.bones),
        "action": action.name,
        "frame_range": list(action.frame_range),
        "clips": len(inspected["clips"]),
        "reexports": ["reexport.fbx", "reexport.glb"],
        "rollback": True,
    }))
finally:
    folder.cleanup()
