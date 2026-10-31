"""Native GLB shape-key animation export/import round-trip checks."""

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
    "action": "claim", "owner": "morph-animation-fixture",
    "expected_project": state["project_id"]})["lease_id"]


try:
    bpy.ops.mesh.primitive_cube_add()
    source = bpy.context.object
    source.name = source.data.name = "MorphAnimSource"
    source.shape_key_add(name="Basis")
    expand = source.shape_key_add(name="Expand")
    for point in expand.data:
        point.co.x *= 1.5
    expand.value = 0
    expand.keyframe_insert("value", frame=1)
    expand.value = 1
    expand.keyframe_insert("value", frame=11)

    exported = bridge.dispatch("export_asset", {
        "names": ["MorphAnimSource"], "path": "morph-anim.glb",
        "animations": True, "lease_id": lease})
    assert exported["bytes"] > 0 and exported["shape_key_animations"], exported
    clip = exported["shape_key_animations"][0]
    assert clip["frame_range"] == [1, 11], clip

    imported = bridge.dispatch("import_mesh", {
        "path": "morph-anim.glb", "name": "MorphAnimImport", "lease_id": lease})
    assert imported["shape_key_animations"], imported
    clip = imported["shape_key_animations"][0]
    assert clip["frame_range"] == [1, 11], clip
    assert clip["mesh"] in imported["skinned_meshes"] or clip["mesh"] in [
        item["name"] for item in imported["objects"] if item["type"] == "MESH"]
    mesh = bpy.data.objects[clip["mesh"]]
    assert len(mesh.data.shape_keys.key_blocks) == 2
    detail = bridge.dispatch("object_info", {"name": mesh.name})
    assert detail["shape_key_action"] == clip["name"], detail

    again = bridge.dispatch("export_asset", {
        "names": [mesh.name], "path": "morph-again.glb",
        "animations": True, "lease_id": lease})
    assert again["shape_key_animations"], again
    reimported = bridge.dispatch("import_mesh", {
        "path": "morph-again.glb", "name": "MorphAnimAgain", "lease_id": lease})
    assert reimported["shape_key_animations"], reimported

    print(json.dumps({
        "action": clip["name"],
        "frames": clip["frame_range"],
        "shape_keys": len(mesh.data.shape_keys.key_blocks) - 1,
        "reimported": len(reimported["shape_key_animations"]),
    }))
finally:
    folder.cleanup()
