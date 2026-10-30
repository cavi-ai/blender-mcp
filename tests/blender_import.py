"""Native GLB import, rollback and scene-preservation checks in a disposable scene."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

fixture_state = bridge.dispatch("session_control", {"action": "inspect"})
fixture_lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "native-fixture",
    "expected_project": fixture_state["project_id"],
})["lease_id"]


def owned_dispatch(operation, params):
    return bridge.dispatch(operation, {**params, "lease_id": fixture_lease}
                           if operation not in {"scene_info", "object_info", "runtime_status"}
                           else params)


with tempfile.TemporaryDirectory() as folder:
    bridge._workspace = Path(folder)
    bpy.ops.mesh.primitive_cube_add(location=(2, 3, 4))
    source = bpy.context.object
    source.name = "ImportSource"
    colors = source.data.color_attributes.new(name="Color", type="BYTE_COLOR", domain="CORNER")
    for value in colors.data:
        value.color = (0.2, 0.5, 0.8, 1)
    owned_dispatch("export_mesh", {"names": [source.name], "path": "source.glb"})
    before = owned_dispatch("scene_info", {})
    selected = {obj.name for obj in bpy.context.selected_objects}
    active = bpy.context.view_layer.objects.active
    result = owned_dispatch("import_mesh", {"path": "source.glb", "name": "ImportedProp"})
    assert result["collection"] == "ImportedProp"
    imported = [bpy.data.objects[item["name"]] for item in result["objects"]]
    meshes = [obj for obj in imported if obj.type == "MESH"]
    assert len(meshes) == 1
    assert len(meshes[0].data.vertices) >= 8
    assert len(meshes[0].data.color_attributes) == 1
    imported_color = meshes[0].data.color_attributes[0].data[0].color
    assert all(abs(a - b) < 0.01 for a, b in zip(imported_color, colors.data[0].color))
    assert len(meshes[0].data.uv_layers) == 1
    source_positions = {tuple(round(v, 5) for v in source.matrix_world @ point.co)
                        for point in source.data.vertices}
    imported_positions = {tuple(round(v, 5) for v in meshes[0].matrix_world @ point.co)
                          for point in meshes[0].data.vertices}
    assert imported_positions == source_positions
    assert sum(len(poly.vertices) - 2 for poly in meshes[0].data.polygons) == 12
    assert {obj.name for obj in bpy.context.selected_objects} == selected
    assert bpy.context.view_layer.objects.active == active
    assert bpy.data.filepath == before["file"]
    after = owned_dispatch("scene_info", {})
    for original in before["objects"]:
        assert next(obj for obj in after["objects"] if obj["name"] == original["name"]) == original
    try:
        owned_dispatch("import_mesh", {"path": "source.glb", "name": "ImportedProp"})
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate import name was accepted")
    try:
        owned_dispatch("import_mesh", {"path": "source.glb", "name": "界" * 22})
    except ValueError:
        pass
    else:
        raise AssertionError("An overlong UTF-8 name could be truncated and bypass name reuse checks")

    pools = ["objects", "meshes", "materials", "images", "collections"]
    snapshot = {name: set(getattr(bpy.data, name)) for name in pools}
    real_import = bridge._load_glb

    def partially_import(path):
        real_import(path)
        raise RuntimeError("simulated failure after native import")

    with patch.object(bridge, "_load_glb", side_effect=partially_import):
        try:
            owned_dispatch("import_mesh", {"path": "source.glb", "name": "FailedProp"})
        except RuntimeError:
            pass
        else:
            raise AssertionError("Failed import was accepted")
    for name in pools:
        assert set(getattr(bpy.data, name)) == snapshot[name], f"Failed import leaked {name}"
    assert {obj.name for obj in bpy.context.selected_objects} == selected
    assert bpy.context.view_layer.objects.active == active
    assert not list(Path(folder).glob(".cavi-import-*"))

    bpy.ops.mesh.primitive_cube_add()
    textured = bpy.context.object
    textured.name = "TexturedSource"
    image = bpy.data.images.new("SourceImage", width=2, height=2)
    image.pixels[:] = [1.0] * 16
    material = bpy.data.materials.new("SourceTextureMaterial")
    if material.node_tree is None:
        material.use_nodes = True
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    shader = material.node_tree.nodes.get("Principled BSDF")
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    textured.data.materials.append(material)
    owned_dispatch("export_mesh", {"names": [textured.name], "path": "textured.glb"})
    images_before = set(bpy.data.images)
    owned_dispatch("import_mesh", {"path": "textured.glb", "name": "TexturedProp"})
    images = set(bpy.data.images) - images_before
    assert images and all(image.packed_file for image in images)
    print(json.dumps({"native_import": "passed", "vertex_colors_preserved": True,
                      "uvs_preserved": True, "original_objects_preserved": True,
                      "failed_import_rolled_back": True, "selection_preserved": True,
                      "transforms_preserved": True, "embedded_images_packed": True}))
