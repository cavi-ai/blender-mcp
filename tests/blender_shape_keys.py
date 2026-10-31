"""Native shape-key authoring, value and animation checks."""

import json
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

folder = tempfile.TemporaryDirectory()
bridge._workspace = Path(folder.name)
state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "shape-key-fixture",
    "expected_project": state["project_id"]})["lease_id"]


def edit(operation, **params):
    return bridge.dispatch("owned_edit", {"operation": operation,
                                          "params": {**params, "lease_id": lease}})


def refused(operation, message, **params):
    try:
        edit(operation, **params)
    except (ValueError, RuntimeError) as exc:
        assert message in str(exc), exc
    else:
        raise AssertionError(f"{operation} accepted {params}")


try:
    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    target.name = target.data.name = "ShapeTarget"
    added = edit("shape_key_add", name="ShapeTarget", new_name="Smile", value=.5,
                 offsets=[[0, 0, 0, .2]])
    assert added["shape_keys"] == 1 and added["shape_key_names"] == ["Smile"], added
    keys = target.data.shape_keys.key_blocks
    assert keys[0].name == "Basis" and keys["Smile"].value == .5
    assert abs(keys["Smile"].data[0].co.z - target.data.vertices[0].co.z - .2) < 1e-6

    bpy.ops.mesh.primitive_cube_add(location=(5, 0, 0))
    source = bpy.context.object
    source.name = source.data.name = "ShapeCopy"
    source.data.vertices[0].co.x += .3
    copied = edit("shape_key_add", name="ShapeTarget", new_name="FromCopy",
                  source="ShapeCopy")
    assert "FromCopy" in copied["shape_key_names"]
    assert abs(target.data.shape_keys.key_blocks["FromCopy"].data[0].co.x
               - source.data.vertices[0].co.x) < 1e-6

    action = edit("shape_key_keyframe", name="ShapeTarget", new_name="Smile",
                  action_name="SmileAction", keyframes=[
                      {"frame": 1, "value": 0}, {"frame": 11, "value": 1}])
    assert action["action"] == "SmileAction" and action["frame_range"] == [1, 11], action
    assert action["action_slot"], action
    assert target.data.shape_keys.animation_data.action.name == "SmileAction"
    detail = bridge.dispatch("object_info", {"name": "ShapeTarget"})
    assert detail["shape_key_action"] == "SmileAction", detail
    bpy.context.scene.frame_set(11)
    bpy.context.view_layer.update()
    assert abs(target.data.shape_keys.key_blocks["Smile"].value - 1) < 1e-6

    removed = edit("shape_key_remove", name="ShapeTarget", new_name="FromCopy")
    assert "FromCopy" not in removed["shape_key_names"]
    refused("shape_key_remove", "Basis", name="ShapeTarget", new_name="Basis")
    refused("shape_key_add", "already exists", name="ShapeTarget", new_name="Smile")
    refused("shape_key_add", "does not exist", name="ShapeTarget", new_name="Bad",
            offsets=[[9999, 0, 0, 0]])
    assert "Bad" not in target.data.shape_keys.key_blocks

    bpy.ops.mesh.primitive_uv_sphere_add(location=(8, 0, 0))
    sphere = bpy.context.object
    sphere.name = "ShapeSphere"
    refused("shape_key_add", "vertex count", name="ShapeTarget", new_name="BadSource",
            source="ShapeSphere")

    before_actions = set(bpy.data.actions)
    refused("shape_key_keyframe", "already exists", name="ShapeTarget", new_name="Smile",
            action_name="SmileAction", keyframes=[{"frame": 1, "value": 0}])
    assert set(bpy.data.actions) == before_actions

    shared = bpy.data.objects.new("ShapeShared", target.data)
    bpy.context.scene.collection.objects.link(shared)
    refused("shape_key_add", "single-user", name="ShapeShared", new_name="SharedKey")

    try:
        bridge.dispatch("shape_key_add", {"name": "ShapeTarget", "new_name": "NoLease"})
        raise AssertionError("Unowned shape-key add succeeded")
    except RuntimeError as exc:
        assert "lease_id" in str(exc)

    print(json.dumps({
        "shape_keys": added["shape_key_names"],
        "action": action["action"],
        "frames": action["frame_range"],
        "rollback": True,
    }))
finally:
    folder.cleanup()
