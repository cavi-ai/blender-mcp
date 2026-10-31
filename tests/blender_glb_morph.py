"""Native GLB morph-target and shape-key round-trip checks."""

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
    "action": "claim", "owner": "glb-morph-fixture",
    "expected_project": state["project_id"]})["lease_id"]


try:
    bpy.ops.mesh.primitive_cube_add()
    source = bpy.context.object
    source.name = source.data.name = "MorphSource"
    source.shape_key_add(name="Basis")
    expand = source.shape_key_add(name="Expand")
    for point in expand.data:
        point.co.x *= 1.5
    expand.value = 0.5
    squash = source.shape_key_add(name="Squash")
    for point in squash.data:
        point.co.z *= 1.5
    squash.value = 0.25

    bridge.dispatch("export_mesh", {
        "names": ["MorphSource"], "path": "morph.glb", "lease_id": lease})
    imported = bridge.dispatch("import_mesh", {
        "path": "morph.glb", "name": "MorphImport", "lease_id": lease})
    assert imported["morph_targets"] == 2, imported
    assert len(imported["shape_key_meshes"]) == 1, imported
    assert imported["shape_key_meshes"][0]["shape_keys"] == 2
    mesh = bpy.data.objects[imported["shape_key_meshes"][0]["name"]]
    blocks = mesh.data.shape_keys.key_blocks
    names = [block.name for block in blocks]
    assert len(blocks) == 3 and names[0] == "Basis", names
    assert any("Expand" in name for name in names[1:]), names
    assert any("Squash" in name for name in names[1:]), names
    detail = bridge.dispatch("object_info", {"name": mesh.name})
    assert detail["shape_keys"] == 2, detail
    assert len(detail["shape_key_names"]) == 2, detail

    bridge.dispatch("export_mesh", {
        "names": [mesh.name], "path": "morph-again.glb", "lease_id": lease})
    again = bridge.dispatch("import_mesh", {
        "path": "morph-again.glb", "name": "MorphAgain", "lease_id": lease})
    assert again["morph_targets"] == 2, again
    assert len(again["shape_key_meshes"]) == 1, again
    again_mesh = bpy.data.objects[again["shape_key_meshes"][0]["name"]]
    assert len(again_mesh.data.shape_keys.key_blocks) == 3

    print(json.dumps({
        "morph_targets": imported["morph_targets"],
        "shape_key_meshes": len(imported["shape_key_meshes"]),
        "names": detail["shape_key_names"],
        "round_trip": again["morph_targets"],
    }))
finally:
    folder.cleanup()
