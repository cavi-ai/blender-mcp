"""Native PBR material checks: maps, QA, updates, rollback and GLB round trip."""

import json
import math
import struct
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    bridge._workspace = root

    def image(name, rgba, file_format="PNG"):
        value = bpy.data.images.new(name, 8, 8, alpha=True)
        value.pixels = list(rgba) * 64
        value.filepath_raw = str(root / name)
        value.file_format = file_format
        value.save()
        bpy.data.images.remove(value)

    image("base.png", (1, 0, 0, 1))
    image("normal.png", (.5, .5, 1, 1))
    image("rough.png", (.4, .4, .4, 1))
    image("metal.png", (.2, .2, .2, 1))
    image("emit.png", (1, .5, 0, 1))
    image("alpha.png", (1, 1, 1, 1))
    image("base.jpg", (0, 1, 0, 1), "JPEG")

    state = bridge.dispatch("session_control", {"action": "inspect"})
    lease = bridge.dispatch("session_control", {
        "action": "claim", "owner": "pbr-fixture",
        "expected_project": state["project_id"]})["lease_id"]
    cube = bpy.data.objects["Cube"]

    def assign(**params):
        return bridge.dispatch("assign_material", {**params, "lease_id": lease})

    def images(material):
        return {node.image.name: node.image for node in material.node_tree.nodes
                if node.type == "TEX_IMAGE" and node.image}

    result = assign(names=["Cube"], material_name="PBR", base_color_texture="base.png",
                    base_color=[.8, .6, .4, 1], roughness_texture="rough.png",
                    metallic_texture="metal.png", normal_texture="normal.png",
                    normal_strength=.8, emission_texture="emit.png", emission_strength=2,
                    alpha_texture="alpha.png", alpha_mode="clip", uv_scale=[2, 3],
                    uv_offset=[.1, .2], uv_rotation_degrees=45)
    material = cube.material_slots[0].material
    assert material.name == "PBR" and result["updated"] is False, result
    assert result["texture_packed"] and result["material_users"] >= 1
    assert set(result["textures"]) == {
        "base_color_texture", "roughness_texture", "metallic_texture", "normal_texture",
        "emission_texture", "alpha_texture"}
    loaded = images(material)
    assert set(loaded) == {"PBR_Base_Color", "PBR_Roughness", "PBR_Metallic", "PBR_Normal",
                           "PBR_Emission", "PBR_Alpha"}, loaded
    assert loaded["PBR_Base_Color"].colorspace_settings.name == "sRGB"
    assert loaded["PBR_Emission"].colorspace_settings.name == "sRGB"
    for name in ("PBR_Roughness", "PBR_Metallic", "PBR_Normal", "PBR_Alpha"):
        assert loaded[name].colorspace_settings.name == "Non-Color", name
    assert all(value.packed_file for value in loaded.values())
    shader = material.node_tree.nodes.get("Principled BSDF")
    normal = next(node for node in material.node_tree.nodes if node.type == "NORMAL_MAP")
    assert abs(normal.inputs["Strength"].default_value - .8) < 1e-6
    assert abs(shader.inputs["Emission Strength"].default_value - 2) < 1e-6
    assert shader.inputs["Normal"].is_linked and shader.inputs["Alpha"].is_linked
    assert shader.inputs["Roughness"].is_linked and shader.inputs["Metallic"].is_linked
    mapping = next(node for node in material.node_tree.nodes if node.type == "MAPPING")
    assert [round(value, 4) for value in mapping.inputs["Scale"].default_value[:2]] == [2, 3]
    assert [round(value, 4) for value in mapping.inputs["Location"].default_value[:2]] == [
        .1, .2]
    assert abs(math.degrees(mapping.inputs["Rotation"].default_value[2]) - 45) < 1e-4
    assert material.surface_render_method == "DITHERED"
    config = json.loads(material["cavi_material_config"])
    assert config["normal_texture"] == "normal.png" and config["alpha_mode"] == "clip"
    assert config["uv_scale"] == [2, 3] and config["uv_rotation_degrees"] == 45

    updated = assign(names=["Cube"], material_name="PBR", update_existing=True,
                     normal_strength=1.5, base_color=[.5, .5, .5, 1])
    assert updated["updated"] is True and updated["base_color_srgb"] == [.5, .5, .5, 1]
    assert updated["config"]["roughness_texture"] == "rough.png"
    shader = material.node_tree.nodes.get("Principled BSDF")
    normal = next(node for node in material.node_tree.nodes if node.type == "NORMAL_MAP")
    assert abs(normal.inputs["Strength"].default_value - 1.5) < 1e-6
    loaded = images(material)
    assert set(loaded) == {"PBR_Base_Color", "PBR_Roughness", "PBR_Metallic", "PBR_Normal",
                           "PBR_Emission", "PBR_Alpha"}, loaded

    before = (set(images(material)), normal.inputs["Strength"].default_value)
    try:
        assign(names=["Cube"], material_name="PBR", update_existing=True,
               normal_texture="missing.png")
        raise AssertionError("Missing texture update succeeded")
    except (ValueError, OSError) as exc:
        assert "workspace" in str(exc).lower() or "exist" in str(exc).lower(), exc
    assert set(images(material)) == before[0]
    assert abs(normal.inputs["Strength"].default_value - before[1]) < 1e-6

    custom = bpy.data.materials.new("Custom")
    cube.data.materials.append(custom)
    try:
        assign(names=["Cube"], material_name="Custom", update_existing=True, slot=1)
        raise AssertionError("Untagged material update succeeded")
    except ValueError as exc:
        assert "created by assign_material" in str(exc), exc
    cube.data.materials.pop(index=1)

    try:
        assign(names=["Cube"], material_name="BadAlpha", alpha_texture="alpha.png",
               alpha_mode="opaque")
        raise AssertionError("Opaque alpha texture succeeded")
    except ValueError as exc:
        assert "clip or blend" in str(exc), exc
    assert "BadAlpha" not in bpy.data.materials

    bpy.ops.mesh.primitive_cube_add(location=(4, 0, 0))
    jpeg_cube = bpy.context.object
    jpeg_cube.name = "JPEGCube"
    jpeg = assign(names=["JPEGCube"], material_name="JPEGMat", base_color_texture="base.jpg")
    assert jpeg["base_color_texture"]["format"] == "jpg", jpeg
    jpeg_material = jpeg_cube.material_slots[0].material
    assert images(jpeg_material)["JPEGMat_Base_Color"].colorspace_settings.name == "sRGB"

    report = bridge.dispatch("inspect_mesh_quality", {
        "names": ["Cube"], "checks": ["materials"], "texture_resolution": [64, 64]})
    slots = report["objects"][0]["checks"]["materials"]
    pbr_slot = next(slot for slot in slots if slot["material"] == "PBR")
    assert pbr_slot["bindings"]["Base Color"]["images"] == ["PBR_Base_Color"]
    assert pbr_slot["bindings"]["Normal"]["images"] == ["PBR_Normal"]
    assert pbr_slot["bindings"]["Roughness"]["images"] == ["PBR_Roughness"]
    assert pbr_slot["bindings"]["Metallic"]["images"] == ["PBR_Metallic"]
    assert pbr_slot["bindings"]["Emission Color"]["images"] == ["PBR_Emission"]
    assert pbr_slot["bindings"]["Alpha"]["images"] == ["PBR_Alpha"]
    assert not pbr_slot["issues"], pbr_slot["issues"]
    assert abs(pbr_slot["normal_strength"] - 1.5) < 1e-6
    assert pbr_slot["uv_transform"]["scale"][:2] == [2, 3]

    bad = bpy.data.materials.new("BadNormal")
    bad.use_nodes = True
    bad_shader = bad.node_tree.nodes.get("Principled BSDF")
    bad_image = bpy.data.images.load(str(root / "base.png"))
    bad_image.colorspace_settings.name = "sRGB"
    bad_texture = bad.node_tree.nodes.new("ShaderNodeTexImage")
    bad_texture.image = bad_image
    bad.node_tree.links.new(bad_texture.outputs["Color"], bad_shader.inputs["Normal"])
    cube.data.materials.append(bad)
    report = bridge.dispatch("inspect_mesh_quality", {
        "names": ["Cube"], "checks": ["materials"], "texture_resolution": [64, 64]})
    bad_slot = next(slot for slot in report["objects"][0]["checks"]["materials"]
                    if slot["material"] == "BadNormal")
    assert "Normal:wrong_color_space" in bad_slot["issues"], bad_slot["issues"]
    cube.data.materials.pop(index=1)
    bpy.data.images.remove(bad_image)

    exported = bridge.dispatch("export_mesh", {
        "names": ["Cube"], "path": "pbr.glb", "lease_id": lease})
    assert exported["bytes"] > 0
    data = (root / "pbr.glb").read_bytes()
    offset, chunks = 12, []
    while offset + 8 <= len(data):
        length, kind = struct.unpack("<II", data[offset:offset + 8])
        offset += 8
        chunks.append((kind, data[offset:offset + length]))
        offset += length
    document = json.loads(chunks[0][1])
    exported_material = next(item for item in document["materials"] if item["name"] == "PBR")
    assert exported_material["alphaMode"] == "MASK", exported_material
    assert abs(exported_material["pbrMetallicRoughness"]["baseColorFactor"][0]
               - 0.21404114) < 1e-4
    assert "normalTexture" in exported_material
    assert "emissiveTexture" in exported_material
    assert "baseColorTexture" in exported_material["pbrMetallicRoughness"]
    assert "metallicRoughnessTexture" in exported_material["pbrMetallicRoughness"]
    imported = bridge.dispatch("import_mesh", {
        "path": "pbr.glb", "name": "PBRImport", "lease_id": lease})
    imported_mesh = next(item["name"] for item in imported["objects"] if item["type"] == "MESH")
    imported_report = bridge.dispatch("inspect_mesh_quality", {
        "names": [imported_mesh], "checks": ["materials"], "texture_resolution": [64, 64]})
    imported_materials = imported_report["objects"][0]["checks"]["materials"]
    assert imported_materials, imported_report
    imported_pbr = imported_materials[0]
    for name in ("Base Color", "Normal", "Emission Color", "Roughness", "Metallic", "Alpha"):
        assert imported_pbr["bindings"][name]["images"], (name, imported_pbr)
    assert not any("wrong_color_space" in issue or "missing_image_data" in issue
                   for issue in imported_pbr["issues"]), imported_pbr["issues"]
    imported_images = {name for slot in imported_materials
                       for binding in slot["bindings"].values()
                       for name in binding["images"]}
    assert imported_images, imported_report

    print(json.dumps({
        "maps": sorted(loaded),
        "updated": True,
        "qa_issues": pbr_slot["issues"],
        "glb_bytes": exported["bytes"],
        "imported_images": sorted(imported_images),
    }))
