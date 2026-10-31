"""Native action inventory, assignment and NLA clip management checks."""

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
    "action": "claim", "owner": "nla-fixture",
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
    edit("create_armature", name="NlaRig", bones=[
        {"name": "Root", "head": [0, 0, -1], "tail": [0, 0, 0]},
        {"name": "Spine", "parent": "Root", "head": [0, 0, 0], "tail": [0, 0, 1],
         "connect": True},
    ])
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12)
    skin = bpy.context.object
    skin.name = skin.data.name = "NlaSkin"
    edit("bind_skin", name="NlaRig", names=["NlaSkin"])
    rig = bpy.data.objects["NlaRig"]
    for name, angle in (("Walk", 15), ("Run", 30)):
        edit("keyframe_rig", name="NlaRig", action_name=name, keyframes=[
            {"frame": 1, "poses": [{"bone": "Spine", "rotation_degrees": [0, 0, 0]}]},
            {"frame": 11, "poses": [{"bone": "Spine", "rotation_degrees": [0, 0, angle]}]},
        ])
    inventory = bridge.dispatch("inspect_rig", {
        "armature": "NlaRig", "meshes": ["NlaSkin"]})
    assert {"Walk", "Run"} <= {item["name"] for item in inventory["actions"]}, inventory

    assigned = edit("set_action", name="NlaRig", action_name="Walk")
    assert assigned["active_action"] == "Walk", assigned
    assigned = edit("set_action", name="NlaRig")
    assert assigned["active_action"] is None, assigned
    assigned = edit("set_action", name="NlaRig", action_name="Walk")
    assert assigned["active_action"] == "Walk"

    pushed = edit("nla_push", name="NlaRig", action_name="Walk",
                  track_name="Locomotion", strip_name="Walk", start_frame=1)
    assert pushed["active_action"] is None and pushed["track"] == "Locomotion", pushed
    assert pushed["nla_strips"] == 1 and pushed["strip"] == "Walk"
    assert bpy.data.actions["Walk"].use_fake_user
    pushed = edit("nla_push", name="NlaRig", action_name="Run",
                  track_name="Locomotion", strip_name="Run", start_frame=12)
    assert pushed["nla_strips"] == 2, pushed
    clips = bridge.dispatch("inspect_rig", {"armature": "NlaRig", "meshes": ["NlaSkin"]})
    assert {clip["name"] for clip in clips["clips"]} >= {"Walk", "Run"}, clips["clips"]

    exported = bridge.dispatch("export_asset", {
        "names": ["NlaSkin"], "path": "nla.fbx", "animations": True, "lease_id": lease})
    assert {item["name"] for item in exported["animations"]} >= {"Walk", "Run"}, exported

    removed = edit("nla_remove", name="NlaRig", track_name="Locomotion",
                   strip_name="Walk")
    assert removed["removed_strips"] == 1 and removed["nla_strips"] == 1, removed
    removed = edit("nla_remove", name="NlaRig", track_name="Locomotion")
    assert removed["removed_tracks"] == ["Locomotion"] and removed["nla_strips"] == 0

    renamed = edit("rename_action", name="NlaRig", action_name="Walk",
                   new_name="WalkRenamed")
    assert renamed["action"] == "WalkRenamed" and renamed["previous"] == "Walk"
    refused("rename_action", "already exists", name="NlaRig",
            action_name="WalkRenamed", new_name="Run")
    deleted = edit("delete_action", name="NlaRig", action_name="Run")
    assert deleted["deleted"] == "Run" and "Run" not in bpy.data.actions
    edit("set_action", name="NlaRig", action_name="WalkRenamed")
    refused("delete_action", "in use", name="NlaRig", action_name="WalkRenamed")
    edit("set_action", name="NlaRig")

    refused("nla_push", "Provide action_name", name="NlaRig")
    refused("nla_remove", "does not exist", name="NlaRig", track_name="Missing")
    refused("nla_remove", "requires track_name", name="NlaRig", strip_name="Walk")
    refused("delete_action", "does not exist", name="NlaRig", action_name="Missing")
    try:
        bridge.dispatch("nla_push", {"name": "NlaRig", "action_name": "WalkRenamed"})
        raise AssertionError("Unowned NLA push succeeded")
    except RuntimeError as exc:
        assert "lease_id" in str(exc)

    print(json.dumps({
        "actions": sorted(item["name"] for item in inventory["actions"]),
        "exported": sorted(item["name"] for item in exported["animations"]),
        "rollback": True,
    }))
finally:
    folder.cleanup()
