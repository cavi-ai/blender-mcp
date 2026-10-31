"""Native OBJ import, workspace texture, validation and rollback checks."""

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
    "action": "claim", "owner": "obj-import-fixture",
    "expected_project": state["project_id"]})["lease_id"]


def export_obj(path, objects, **extra):
    for value in bpy.context.selected_objects:
        value.select_set(False)
    for value in objects:
        value.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    result = bpy.ops.wm.obj_export(
        filepath=str(path), export_selected_objects=True, export_uv=True,
        export_normals=True, export_materials=True, apply_modifiers=False, **extra)
    assert "FINISHED" in result


try:
    bpy.ops.mesh.primitive_cube_add(location=(2, 3, 4))
    source = bpy.context.object
    source.name = source.data.name = "ObjSource"
    export_obj(root / "static.obj", [source], path_mode="RELATIVE")
    before = bridge.dispatch("scene_info", {})
    static = bridge.dispatch("import_obj", {
        "path": "static.obj", "name": "StaticObj", "lease_id": lease})
    assert static["format"] == "obj" and static["objects"], static
    meshes = [bpy.data.objects[item["name"]] for item in static["objects"]
              if item["type"] == "MESH"]
    assert len(meshes) == 1
    assert len(meshes[0].data.vertices) == 8
    assert len(meshes[0].data.uv_layers) == 1
    source_positions = {tuple(round(value, 5) for value in source.matrix_world @ point.co)
                        for point in source.data.vertices}
    imported_positions = {tuple(round(value, 5) for value in
                                meshes[0].matrix_world @ point.co)
                          for point in meshes[0].data.vertices}
    assert imported_positions == source_positions
    after = bridge.dispatch("scene_info", {})
    for original in before["objects"]:
        assert next(item for item in after["objects"] if item["name"] == original["name"]) == original

    inside_path = root / "inside.png"
    image = bpy.data.images.new("InsideTexture", 2, 2)
    image.filepath_raw = str(inside_path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    bpy.ops.mesh.primitive_cube_add(location=(6, 0, 0))
    textured = bpy.context.object
    textured.name = "ObjTextured"
    material = bpy.data.materials.new("ObjMaterial")
    material.use_nodes = True
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(str(inside_path))
    shader = material.node_tree.nodes.get("Principled BSDF")
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    textured.data.materials.append(material)
    export_obj(root / "inside.obj", [textured], path_mode="RELATIVE")
    images_before = set(bpy.data.images)
    inside = bridge.dispatch("import_obj", {
        "path": "inside.obj", "name": "TexturedObj", "lease_id": lease})
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
        bpy.ops.mesh.primitive_cube_add(location=(9, 0, 0))
        external = bpy.context.object
        external.name = "ObjExternal"
        material = bpy.data.materials.new("ExternalMaterial")
        material.use_nodes = True
        texture = material.node_tree.nodes.new("ShaderNodeTexImage")
        texture.image = bpy.data.images.load(str(external_path))
        shader = material.node_tree.nodes.get("Principled BSDF")
        material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
        external.data.materials.append(material)
        export_obj(root / "external.obj", [external], path_mode="ABSOLUTE")
        snapshot = {key: set(getattr(bpy.data, key))
                    for key in ("objects", "images", "collections")}
        try:
            bridge.dispatch("import_obj", {
                "path": "external.obj", "name": "ExternalObj", "lease_id": lease})
        except (ValueError, RuntimeError) as exc:
            assert "workspace" in str(exc), exc
        else:
            raise AssertionError("External OBJ texture was accepted")
        for key, value in snapshot.items():
            assert set(getattr(bpy.data, key)) == value, f"External import leaked {key}"

    try:
        bridge.dispatch("import_obj", {
            "path": "static.obj", "name": "StaticObj", "lease_id": lease})
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("Duplicate OBJ import name was accepted")

    pools = ["objects", "meshes", "materials", "images", "collections", "armatures", "actions"]
    snapshot = {key: set(getattr(bpy.data, key)) for key in pools}
    real_import = bridge._load_obj

    def partially_import(path):
        real_import(path)
        raise RuntimeError("simulated failure after OBJ import")

    with patch.object(bridge, "_load_obj", side_effect=partially_import):
        try:
            bridge.dispatch("import_obj", {
                "path": "static.obj", "name": "FailedObj", "lease_id": lease})
        except RuntimeError:
            pass
        else:
            raise AssertionError("Failed OBJ import was accepted")
    for key, value in snapshot.items():
        assert set(getattr(bpy.data, key)) == value, f"Failed import leaked {key}"

    print(json.dumps({
        "vertices": len(meshes[0].data.vertices),
        "textures_packed": bool(new_images),
        "rollback": True,
    }))
finally:
    folder.cleanup()
