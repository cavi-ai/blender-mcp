"""Native FBX and USD texture sidecar export and refusal checks."""

import json
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
    "action": "claim", "owner": "sidecar-fixture",
    "expected_project": state["project_id"]})["lease_id"]


def refused(path, message, **params):
    try:
        bridge.dispatch("export_asset", {**params, "path": path, "lease_id": lease})
    except (ValueError, RuntimeError, FileExistsError) as exc:
        assert message in str(exc), exc
    else:
        raise AssertionError(f"export accepted {params}")


try:
    image_path = root / "source.png"
    image = bpy.data.images.new("SidecarTexture", 2, 2)
    image.filepath_raw = str(image_path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.object
    cube.name = cube.data.name = "SidecarCube"
    material = bpy.data.materials.new("SidecarMaterial")
    material.use_nodes = True
    node = material.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.load(str(image_path))
    node.image.pack()
    shader = material.node_tree.nodes.get("Principled BSDF")
    material.node_tree.links.new(node.outputs["Color"], shader.inputs["Base Color"])
    cube.data.materials.append(material)

    export = bridge.dispatch("export_asset", {
        "names": ["SidecarCube"], "path": "model.fbx", "textures": True,
        "lease_id": lease})
    assert export["bytes"] > 0 and export["textures"], export
    directory = root / "model.fbm"
    assert directory.is_dir()
    assert all(Path(item["path"]).is_file() for item in export["textures"])
    assert all(Path(item["path"]).resolve().is_relative_to(directory.resolve())
               for item in export["textures"])

    plain = bridge.dispatch("export_asset", {
        "names": ["SidecarCube"], "path": "plain.fbx", "lease_id": lease})
    assert plain["textures"] == [] and not (root / "plain.fbm").exists()

    usd = bridge.dispatch("export_asset", {
        "names": ["SidecarCube"], "path": "scene.usdc", "textures": True,
        "lease_id": lease})
    assert usd["bytes"] > 0 and usd["textures"], usd
    usd_directory = root / "scene.fbm"
    assert usd_directory.is_dir()
    assert all(Path(item["path"]).is_file() for item in usd["textures"])
    assert all(Path(item["path"]).resolve().is_relative_to(usd_directory.resolve())
               for item in usd["textures"])

    ascii_usd = bridge.dispatch("export_asset", {
        "names": ["SidecarCube"], "path": "scene-ascii.usda", "textures": True,
        "lease_id": lease})
    assert ascii_usd["textures"]
    assert b"@scene-ascii.fbm/" in (root / "scene-ascii.usda").read_bytes()
    assert node.image.packed_file is not None
    assert Path(node.image.filepath) == image_path

    (root / "existing.fbm").mkdir()
    refused("existing.fbx", "overwrite", names=["SidecarCube"], textures=True)
    refused("existing.usdc", "overwrite", names=["SidecarCube"], textures=True)
    assert not (root / "existing.fbx").exists() and not (root / "existing.usdc").exists()
    refused("model.glb", "FBX", names=["SidecarCube"], textures=True)

    try:
        bridge.dispatch("export_asset", {
            "names": ["SidecarCube"], "path": "unowned.fbx", "textures": True})
        raise AssertionError("Unowned texture export succeeded")
    except RuntimeError as exc:
        assert "lease_id" in str(exc)

    print(json.dumps({
        "textures": [item["name"] for item in export["textures"]],
        "usd_textures": [item["name"] for item in usd["textures"]],
        "sidecar_dir": directory.name,
        "rollback": True,
    }))
finally:
    folder.cleanup()
