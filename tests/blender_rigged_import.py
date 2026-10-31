"""Native rigged GLB import, inspection and rollback checks."""

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
    "action": "claim", "owner": "rigged-import-fixture",
    "expected_project": state["project_id"]})["lease_id"]


def edit(operation, **params):
    return bridge.dispatch("owned_edit", {"operation": operation,
                                          "params": {**params, "lease_id": lease}})


try:
    edit("create_armature", name="RigImport", bones=[
        {"name": "Root", "head": [0, 0, -1], "tail": [0, 0, 0]},
        {"name": "Spine", "parent": "Root", "head": [0, 0, 0], "tail": [0, 0, 1],
         "connect": True},
    ])
    bpy.ops.mesh.primitive_uv_sphere_add(location=(0, 0, 0))
    mesh = bpy.context.object
    mesh.name = mesh.data.name = "RigMesh"
    edit("bind_skin", name="RigImport", names=["RigMesh"])
    rig = bpy.data.objects["RigImport"]

    for value in bpy.context.selected_objects:
        value.select_set(False)
    rig.select_set(True)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = rig
    exported = bpy.ops.export_scene.gltf(
        filepath=str(root / "rigged.glb"), export_format="GLB", use_selection=True,
        export_skins=True, export_animations=False, export_apply=False)
    assert "FINISHED" in exported

    before = bridge.dispatch("scene_info", {})
    selected = {value.name for value in bpy.context.selected_objects}
    active = bpy.context.view_layer.objects.active
    imported = bridge.dispatch("import_mesh", {
        "path": "rigged.glb", "name": "RiggedImport", "lease_id": lease})
    assert imported["skins"] == 1 and imported["joints"] == 2, imported
    assert imported["skinned_meshes"] and imported["armatures"], imported
    assert imported["bone_count"] == 2
    imported_rig = bpy.data.objects[imported["armatures"][0]]
    imported_mesh = bpy.data.objects[imported["skinned_meshes"][0]]
    assert imported_rig.name == "RiggedImport"
    assert imported_rig.type == "ARMATURE" and len(imported_rig.data.bones) == 2
    modifiers = [item for item in imported_mesh.modifiers
                 if item.type == "ARMATURE" and item.object == imported_rig]
    assert len(modifiers) == 1
    assert len(imported_mesh.vertex_groups) >= 2
    inspected = bridge.dispatch("inspect_rig", {
        "armature": imported_rig.name, "meshes": [imported_mesh.name]})
    assert inspected["root_bones"] == ["Root"]
    assert inspected["meshes"][0]["weights"]["ignored_groups"] == []
    assert {value.name for value in bpy.context.selected_objects} == selected
    assert bpy.context.view_layer.objects.active == active
    after = bridge.dispatch("scene_info", {})
    for original in before["objects"]:
        assert next(item for item in after["objects"] if item["name"] == original["name"]) == original

    try:
        bridge.dispatch("import_mesh", {
            "path": "rigged.glb", "name": "RiggedImport", "lease_id": lease})
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("Duplicate rigged import name was accepted")

    pools = ["objects", "armatures", "actions", "meshes", "materials", "images", "collections"]
    snapshot = {name: set(getattr(bpy.data, name)) for name in pools}
    real_import = bridge._load_glb

    def partially_import(path):
        real_import(path)
        raise RuntimeError("simulated failure after rigged import")

    with patch.object(bridge, "_load_glb", side_effect=partially_import):
        try:
            bridge.dispatch("import_mesh", {
                "path": "rigged.glb", "name": "FailedRig", "lease_id": lease})
        except RuntimeError:
            pass
        else:
            raise AssertionError("Failed rigged import was accepted")
    for name in pools:
        assert set(getattr(bpy.data, name)) == snapshot[name], f"Failed import leaked {name}"

    print(json.dumps({
        "armature": imported_rig.name,
        "bones": len(imported_rig.data.bones),
        "skinned_meshes": imported["skinned_meshes"],
        "vertex_groups": len(imported_mesh.vertex_groups),
        "rollback": True,
    }))
finally:
    folder.cleanup()
