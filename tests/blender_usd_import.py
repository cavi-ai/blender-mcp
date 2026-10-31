"""Native static, textured and rigged USD import checks."""

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
    "action": "claim", "owner": "usd-import-fixture",
    "expected_project": state["project_id"]})["lease_id"]


def export_usd(path, objects, **extra):
    for value in bpy.context.selected_objects:
        value.select_set(False)
    for value in objects:
        value.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    options = {"selected_objects_only": True, "export_animation": False,
               "export_materials": True, "export_textures_mode": "KEEP",
               "relative_paths": True, "export_armatures": False,
               **extra}
    result = bpy.ops.wm.usd_export(filepath=str(path), **options)
    assert "FINISHED" in result


try:
    inside_path = root / "inside.png"
    image = bpy.data.images.new("UsdTexture", 2, 2)
    image.filepath_raw = str(inside_path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    bpy.ops.mesh.primitive_cube_add()
    source = bpy.context.object
    source.name = source.data.name = "UsdSource"
    material = bpy.data.materials.new("UsdMaterial")
    material.use_nodes = True
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(str(inside_path))
    shader = material.node_tree.nodes.get("Principled BSDF")
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    source.data.materials.append(material)
    export_usd(root / "static.usdc", [source])
    before = bridge.dispatch("scene_info", {})
    images_before = set(bpy.data.images)
    static = bridge.dispatch("import_usd", {
        "path": "static.usdc", "name": "StaticUsd", "lease_id": lease})
    assert static["format"] == "usd" and static["objects"], static
    meshes = [bpy.data.objects[item["name"]] for item in static["objects"]
              if item["type"] == "MESH"]
    assert len(meshes) == 1 and len(meshes[0].data.vertices) == 8
    assert len(meshes[0].data.uv_layers) == 1
    assert meshes[0].material_slots
    assert static["imported_vertices"] == 8
    textures = [node.image for slot in meshes[0].material_slots
                if slot.material and slot.material.use_nodes
                for node in slot.material.node_tree.nodes
                if node.type == "TEX_IMAGE" and node.image]
    assert textures
    assert all(image.packed_file or Path(bpy.path.abspath(image.filepath)).resolve().is_relative_to(root)
               for image in textures)
    after = bridge.dispatch("scene_info", {})
    for original in before["objects"]:
        assert next(item for item in after["objects"] if item["name"] == original["name"]) == original

    bridge.dispatch("create_armature", {
        "name": "UsdRig", "bones": [
            {"name": "Root", "head": [0, 0, -1], "tail": [0, 0, 0]},
            {"name": "Spine", "parent": "Root", "head": [0, 0, 0], "tail": [0, 0, 1],
             "connect": True}], "lease_id": lease})
    bpy.ops.mesh.primitive_uv_sphere_add(location=(5, 0, 0))
    skin = bpy.context.object
    skin.name = skin.data.name = "UsdSkin"
    bridge.dispatch("bind_skin", {"name": "UsdRig", "names": ["UsdSkin"],
                                  "lease_id": lease})
    rig = bpy.data.objects["UsdRig"]
    export_usd(root / "rigged.usdc", [rig, skin], export_armatures=True,
               export_materials=False)
    rigged = bridge.dispatch("import_usd", {
        "path": "rigged.usdc", "name": "RiggedUsd", "lease_id": lease})
    assert rigged["armatures"] and rigged["skinned_meshes"], rigged
    assert rigged["bone_count"] == 2
    imported_rig = bpy.data.objects[rigged["armatures"][0]]
    imported_skin = bpy.data.objects[rigged["skinned_meshes"][0]]
    assert imported_rig.type == "ARMATURE" and len(imported_rig.data.bones) == 2
    assert imported_skin.find_armature() == imported_rig
    inspected = bridge.dispatch("inspect_rig", {
        "armature": imported_rig.name, "meshes": [imported_skin.name]})
    assert inspected["root_bones"] == ["Root"]

    bridge.dispatch("owned_edit", {"operation": "keyframe_rig", "params": {
        "name": "UsdRig", "action_name": "UsdWalk", "lease_id": lease,
        "keyframes": [{"frame": 1, "poses": [{"bone": "Spine",
                                               "rotation_degrees": [0, 0, 0]}]},
                       {"frame": 11, "poses": [{"bone": "Spine",
                                                "rotation_degrees": [0, 0, 45]}]}]}})
    export_usd(root / "animated.usdc", [rig, skin], export_armatures=True,
               export_animation=True)
    try:
        bridge.dispatch("import_usd", {
            "path": "animated.usdc", "name": "AnimatedUsd", "lease_id": lease})
    except (ValueError, RuntimeError) as exc:
        assert "animated import workflow" in str(exc), exc
    else:
        raise AssertionError("Animated USD import bypassed the animated workflow")

    with tempfile.TemporaryDirectory() as outside:
        external_path = Path(outside) / "external.png"
        image = bpy.data.images.new("UsdExternal", 2, 2)
        image.filepath_raw = str(external_path)
        image.file_format = "PNG"
        image.save()
        bpy.data.images.remove(image)
        bpy.ops.mesh.primitive_cube_add(location=(9, 0, 0))
        external = bpy.context.object
        external.name = "UsdExternal"
        material = bpy.data.materials.new("UsdExternalMaterial")
        material.use_nodes = True
        texture = material.node_tree.nodes.new("ShaderNodeTexImage")
        texture.image = bpy.data.images.load(str(external_path))
        shader = material.node_tree.nodes.get("Principled BSDF")
        material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
        external.data.materials.append(material)
        export_usd(root / "external.usdc", [external], relative_paths=False)
        snapshot = {key: set(getattr(bpy.data, key))
                    for key in ("objects", "images", "collections")}
        try:
            bridge.dispatch("import_usd", {
                "path": "external.usdc", "name": "ExternalUsd", "lease_id": lease})
        except (ValueError, RuntimeError) as exc:
            assert "workspace" in str(exc), exc
        else:
            raise AssertionError("External USD texture was accepted")
        for key, value in snapshot.items():
            assert set(getattr(bpy.data, key)) == value, f"External import leaked {key}"

    try:
        bridge.dispatch("import_usd", {
            "path": "static.usdc", "name": "StaticUsd", "lease_id": lease})
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("Duplicate USD import name was accepted")

    pools = ["objects", "armatures", "actions", "meshes", "materials", "images", "collections"]
    snapshot = {key: set(getattr(bpy.data, key)) for key in pools}
    real_import = bridge._load_usd

    def partially_import(path):
        real_import(path)
        raise RuntimeError("simulated failure after USD import")

    with patch.object(bridge, "_load_usd", side_effect=partially_import):
        try:
            bridge.dispatch("import_usd", {
                "path": "static.usdc", "name": "FailedUsd", "lease_id": lease})
        except RuntimeError:
            pass
        else:
            raise AssertionError("Failed USD import was accepted")
    for key, value in snapshot.items():
        assert set(getattr(bpy.data, key)) == value, f"Failed import leaked {key}"

    print(json.dumps({
        "vertices": static["imported_vertices"],
        "armature": imported_rig.name,
        "bones": len(imported_rig.data.bones),
        "rollback": True,
    }))
finally:
    folder.cleanup()
