"""Native static and rigged FBX import, validation and rollback checks."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp.presets import AXIS_PRESETS

folder = tempfile.TemporaryDirectory()
root = Path(folder.name)
bridge._workspace = root
state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "fbx-import-fixture",
    "expected_project": state["project_id"]})["lease_id"]


def edit(operation, **params):
    return bridge.dispatch("owned_edit", {"operation": operation,
                                          "params": {**params, "lease_id": lease}})


def export_selected(path, objects, types, **extra):
    for value in bpy.context.selected_objects:
        value.select_set(False)
    for value in objects:
        value.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    options = {"bake_anim": False, "path_mode": "STRIP", **extra,
               **AXIS_PRESETS["unity"]}
    result = bpy.ops.export_scene.fbx(
        filepath=str(path), use_selection=True, object_types=types,
        mesh_smooth_type="FACE", use_tspace=True, add_leaf_bones=False,
        global_scale=1, **options)
    assert "FINISHED" in result


try:
    bpy.ops.mesh.primitive_cube_add(location=(2, 3, 4))
    source = bpy.context.object
    source.name = source.data.name = "FbxSource"
    edit("export_mesh", names=["FbxSource"], path="static.fbx")
    before = bridge.dispatch("scene_info", {})
    static = bridge.dispatch("import_fbx", {
        "path": "static.fbx", "name": "StaticFbx", "lease_id": lease})
    assert static["format"] == "fbx" and static["binary"], static
    assert static["armatures"] == [] and static["skinned_meshes"] == []
    static_meshes = [bpy.data.objects[item["name"]] for item in static["objects"]
                     if item["type"] == "MESH"]
    assert len(static_meshes) == 1
    assert len(static_meshes[0].data.vertices) == 8
    assert len(static_meshes[0].data.uv_layers) == 1
    assert sum(len(poly.vertices) - 2 for poly in static_meshes[0].data.polygons) == 12
    source_positions = {tuple(round(value, 5) for value in source.matrix_world @ point.co)
                        for point in source.data.vertices}
    imported_positions = {tuple(round(value, 5) for value in
                                static_meshes[0].matrix_world @ point.co)
                          for point in static_meshes[0].data.vertices}
    assert imported_positions == source_positions
    after = bridge.dispatch("scene_info", {})
    for original in before["objects"]:
        assert next(item for item in after["objects"] if item["name"] == original["name"]) == original

    edit("create_armature", name="FbxRig", bones=[
        {"name": "Root", "head": [0, 0, -1], "tail": [0, 0, 0]},
        {"name": "Spine", "parent": "Root", "head": [0, 0, 0], "tail": [0, 0, 1],
         "connect": True},
    ])
    bpy.ops.mesh.primitive_uv_sphere_add(location=(0, 0, 0))
    skin = bpy.context.object
    skin.name = skin.data.name = "FbxSkin"
    edit("bind_skin", name="FbxRig", names=["FbxSkin"])
    rig = bpy.data.objects["FbxRig"]
    export_selected(root / "rigged.fbx", [rig, skin], {"MESH", "ARMATURE"})

    rigged = bridge.dispatch("import_fbx", {
        "path": "rigged.fbx", "name": "RiggedFbx", "lease_id": lease})
    assert rigged["armatures"] and rigged["skinned_meshes"], rigged
    assert rigged["bone_count"] == 2, rigged
    imported_rig = bpy.data.objects[rigged["armatures"][0]]
    imported_skin = bpy.data.objects[rigged["skinned_meshes"][0]]
    assert imported_rig.type == "ARMATURE" and len(imported_rig.data.bones) == 2
    assert imported_skin.find_armature() == imported_rig
    assert len(imported_skin.vertex_groups) >= 2
    inspected = bridge.dispatch("inspect_rig", {
        "armature": imported_rig.name, "meshes": [imported_skin.name]})
    assert inspected["root_bones"] == ["Root"]
    assert imported_rig.name == "RiggedFbx"

    edit("keyframe_rig", name="FbxRig", action_name="FbxWalk", keyframes=[
        {"frame": 1, "poses": [{"bone": "Spine", "rotation_degrees": [0, 0, 0]}]},
        {"frame": 11, "poses": [{"bone": "Spine", "rotation_degrees": [0, 0, 45]}]},
    ])
    export_selected(root / "animated.fbx", [rig, skin], {"MESH", "ARMATURE"},
                    bake_anim=True)
    snapshot = {key: set(getattr(bpy.data, key))
                for key in ("objects", "actions", "armatures", "collections")}
    try:
        bridge.dispatch("import_fbx", {
            "path": "animated.fbx", "name": "AnimatedFbx", "lease_id": lease})
    except RuntimeError as exc:
        assert "animated import workflow" in str(exc), exc
    else:
        raise AssertionError("Animated FBX import bypassed the animated workflow")
    for key, value in snapshot.items():
        assert set(getattr(bpy.data, key)) == value, f"Animated import leaked {key}"

    inside_path = root / "inside.png"
    image = bpy.data.images.new("InsideTexture", 2, 2)
    image.filepath_raw = str(inside_path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    bpy.ops.mesh.primitive_cube_add(location=(6, 0, 0))
    textured = bpy.context.object
    textured.name = "InsideSource"
    material = bpy.data.materials.new("InsideMaterial")
    material.use_nodes = True
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(str(inside_path))
    shader = material.node_tree.nodes.get("Principled BSDF")
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    textured.data.materials.append(material)
    export_selected(root / "inside.fbx", [textured], {"MESH"},
                    path_mode="RELATIVE", embed_textures=False)
    images_before = set(bpy.data.images)
    inside = bridge.dispatch("import_fbx", {
        "path": "inside.fbx", "name": "TexturedFbx", "lease_id": lease})
    assert inside["objects"], inside
    new_images = set(bpy.data.images) - images_before
    assert new_images and all(image.packed_file for image in new_images)

    with tempfile.TemporaryDirectory() as outside:
        external_path = Path(outside) / "external.png"
        image = bpy.data.images.new("ExternalTexture", 2, 2)
        image.filepath_raw = str(external_path)
        image.file_format = "PNG"
        image.save()
        bpy.data.images.remove(image)
        bpy.ops.mesh.primitive_cube_add(location=(8, 0, 0))
        textured = bpy.context.object
        textured.name = "ExternalSource"
        material = bpy.data.materials.new("ExternalMaterial")
        material.use_nodes = True
        texture = material.node_tree.nodes.new("ShaderNodeTexImage")
        texture.image = bpy.data.images.load(str(external_path))
        shader = material.node_tree.nodes.get("Principled BSDF")
        material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
        textured.data.materials.append(material)
        export_selected(root / "external.fbx", [textured], {"MESH"},
                        path_mode="ABSOLUTE", embed_textures=False)
        snapshot = {key: set(getattr(bpy.data, key))
                    for key in ("objects", "images", "collections")}
        try:
            bridge.dispatch("import_fbx", {
                "path": "external.fbx", "name": "ExternalFbx", "lease_id": lease})
        except RuntimeError as exc:
            assert "workspace" in str(exc), exc
        else:
            raise AssertionError("External FBX texture was accepted")
        for key, value in snapshot.items():
            assert set(getattr(bpy.data, key)) == value, f"External import leaked {key}"

    bpy.ops.object.camera_add(location=(0, 0, 10))
    camera = bpy.context.object
    bpy.ops.object.light_add(type="POINT", location=(0, 0, 5))
    light = bpy.context.object
    bpy.ops.mesh.primitive_cube_add(location=(12, 0, 0))
    mixed = bpy.context.object
    mixed.name = "MixedSource"
    export_selected(root / "camera.fbx", [mixed, camera, light],
                    {"MESH", "CAMERA", "LIGHT"})
    try:
        bridge.dispatch("import_fbx", {
            "path": "camera.fbx", "name": "CameraFbx", "lease_id": lease})
    except RuntimeError as exc:
        assert "unsupported object type" in str(exc), exc
    else:
        raise AssertionError("FBX cameras and lights were accepted")

    bpy.ops.mesh.primitive_cube_add(location=(16, 0, 0))
    shaped = bpy.context.object
    shaped.name = "ShapeSource"
    shaped.shape_key_add(name="Basis")
    shaped.shape_key_add(name="Expand")
    export_selected(root / "shape.fbx", [shaped], {"MESH"})
    try:
        bridge.dispatch("import_fbx", {
            "path": "shape.fbx", "name": "ShapeFbx", "lease_id": lease})
    except RuntimeError as exc:
        assert "Shape keys" in str(exc), exc
    else:
        raise AssertionError("FBX shape keys were accepted")

    try:
        bridge.dispatch("import_fbx", {
            "path": "static.fbx", "name": "StaticFbx", "lease_id": lease})
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("Duplicate FBX import name was accepted")

    pools = ["objects", "armatures", "actions", "meshes", "materials", "images", "collections"]
    snapshot = {key: set(getattr(bpy.data, key)) for key in pools}
    real_import = bridge._load_fbx

    def partially_import(path):
        real_import(path)
        raise RuntimeError("simulated failure after FBX import")

    with patch.object(bridge, "_load_fbx", side_effect=partially_import):
        try:
            bridge.dispatch("import_fbx", {
                "path": "static.fbx", "name": "FailedFbx", "lease_id": lease})
        except RuntimeError:
            pass
        else:
            raise AssertionError("Failed FBX import was accepted")
    for key in pools:
        assert set(getattr(bpy.data, key)) == snapshot[key], f"Failed import leaked {key}"

    print(json.dumps({
        "static_vertices": len(static_meshes[0].data.vertices),
        "armature": imported_rig.name,
        "bones": len(imported_rig.data.bones),
        "skinned_meshes": rigged["skinned_meshes"],
        "rollback": True,
    }))
finally:
    folder.cleanup()
