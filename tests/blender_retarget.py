"""Native animation retargeting, mapping and rollback checks."""

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
    "action": "claim", "owner": "retarget-fixture",
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


def rig(name, bones):
    edit("create_armature", name=name, bones=bones)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12)
    skin = bpy.context.object
    skin.name = skin.data.name = name.replace("Rig", "Skin")
    edit("bind_skin", name=name, names=[skin.name])
    return skin.name


try:
    source_skin = rig("SourceRig", [
        {"name": "Root", "head": [0, 0, -1], "tail": [0, 0, 0]},
        {"name": "Spine", "parent": "Root", "head": [0, 0, 0], "tail": [0, 0, 1],
         "connect": True},
    ])
    target_skin = rig("TargetRig", [
        {"name": "Root", "head": [0, 0, -1], "tail": [0, 0, 0]},
        {"name": "Spine", "parent": "Root", "head": [0, 0, 0], "tail": [0, 0, 1],
         "connect": True},
    ])
    mapped_skin = rig("MappedRig", [
        {"name": "BoneA", "head": [0, 0, -1], "tail": [0, 0, 0]},
        {"name": "BoneB", "parent": "BoneA", "head": [0, 0, 0], "tail": [0, 0, 1],
         "connect": True},
    ])
    edit("keyframe_rig", name="SourceRig", action_name="Walk", keyframes=[
        {"frame": 1, "poses": [{"bone": "Root", "location": [0, 0, 0]}]},
        {"frame": 11, "poses": [{"bone": "Root", "location": [2, 0, 0]}]},
    ])
    source = bpy.data.objects["SourceRig"]
    target = bpy.data.objects["TargetRig"]
    source.animation_data.action = bpy.data.actions["Walk"]
    bpy.context.scene.frame_set(7)
    source_action = source.animation_data.action
    frame = bpy.context.scene.frame_current

    copied = edit("retarget_rig", name="TargetRig", source="SourceRig",
                  source_action="Walk", action_name="Retargeted")
    assert copied["action"] == "Retargeted" and copied["source_action"] == "Walk", copied
    assert copied["frames"] == [1, 11] and copied["samples"] == 11, copied
    assert copied["keyed_bones"] == ["Root", "Spine"], copied
    assert copied["action_slot"], copied
    assert source.animation_data.action is source_action
    assert bpy.context.scene.frame_current == frame
    assert target.animation_data.action == bpy.data.actions["Retargeted"]

    inspected = bridge.dispatch("inspect_rig", {
        "armature": "TargetRig", "meshes": [target_skin],
        "action": "Retargeted", "checks": ["root_motion"], "samples": 4})
    root = inspected["animation_checks"]["root_motion"]["root_bones"][0]
    assert abs(root["displacement"] - 2) < 1e-3, root
    assert abs(root["horizontal"] - 2) < 1e-3, root

    mapped = edit("retarget_rig", name="MappedRig", source="SourceRig",
                  source_action="Walk", action_name="MappedWalk",
                  mapping={"Root": "BoneA", "Spine": "BoneB"})
    assert mapped["keyed_bones"] == ["BoneA", "BoneB"], mapped
    assert mapped["unmapped_source"] == [] and mapped["unmapped_target"] == []
    inspected = bridge.dispatch("inspect_rig", {
        "armature": "MappedRig", "meshes": [mapped_skin],
        "action": "MappedWalk", "checks": ["root_motion"], "samples": 4})
    assert abs(inspected["animation_checks"]["root_motion"]["root_bones"][0]
               ["displacement"] - 2) < 1e-3

    before_actions = set(bpy.data.actions)
    refused("retarget_rig", "different", name="SourceRig", source="SourceRig",
            source_action="Walk", action_name="SameRig")
    refused("retarget_rig", "does not exist", name="TargetRig", source="SourceRig",
            source_action="Missing", action_name="MissingAction")
    refused("retarget_rig", "Source bone", name="TargetRig", source="SourceRig",
            source_action="Walk", action_name="BadMapping",
            mapping={"Missing": "Root"})
    refused("retarget_rig", "Target bone", name="TargetRig", source="SourceRig",
            source_action="Walk", action_name="BadMapping",
            mapping={"Root": "Missing"})
    refused("retarget_rig", "at most once", name="TargetRig", source="SourceRig",
            source_action="Walk", action_name="BadMapping",
            mapping={"Root": "Spine", "Spine": "Spine"})
    refused("retarget_rig", "already exists", name="TargetRig", source="SourceRig",
            source_action="Walk", action_name="Retargeted")
    refused("retarget_rig", "2 to 256", name="TargetRig", source="SourceRig",
            source_action="Walk", action_name="BadSamples", samples=1)
    assert set(bpy.data.actions) == before_actions

    try:
        bridge.dispatch("retarget_rig", {
            "name": "TargetRig", "source": "SourceRig", "source_action": "Walk",
            "action_name": "Unowned"})
        raise AssertionError("Unowned retarget succeeded")
    except RuntimeError as exc:
        assert "lease_id" in str(exc)

    print(json.dumps({
        "action": copied["action"],
        "frames": copied["frames"],
        "mapped": mapped["keyed_bones"],
        "root_motion": root["displacement"],
        "rollback": True,
    }))
finally:
    folder.cleanup()
