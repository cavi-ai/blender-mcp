"""Native animation QA checks for root motion, loop seams and deformation."""

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
    "action": "claim", "owner": "animation-qa-fixture",
    "expected_project": state["project_id"]})["lease_id"]


def edit(operation, **params):
    return bridge.dispatch("owned_edit", {"operation": operation,
                                          "params": {**params, "lease_id": lease}})


def inspect(action, checks, samples=4):
    return bridge.dispatch("inspect_rig", {
        "armature": "QaRig", "meshes": ["QaSkin"], "action": action,
        "checks": checks, "samples": samples})


try:
    edit("create_armature", name="QaRig", bones=[
        {"name": "Root", "head": [0, 0, -1], "tail": [0, 0, 0]},
        {"name": "Spine", "parent": "Root", "head": [0, 0, 0], "tail": [0, 0, 1],
         "connect": True},
    ])
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12)
    skin = bpy.context.object
    skin.name = skin.data.name = "QaSkin"
    edit("bind_skin", name="QaRig", names=["QaSkin"])
    rig = bpy.data.objects["QaRig"]
    edit("keyframe_rig", name="QaRig", action_name="Move", keyframes=[
        {"frame": 1, "poses": [{"bone": "Root", "location": [0, 0, 0]}]},
        {"frame": 11, "poses": [{"bone": "Root", "location": [2, 0, 0]}]},
    ])
    edit("keyframe_rig", name="QaRig", action_name="Loop", keyframes=[
        {"frame": 1, "poses": [{"bone": "Root", "location": [0, 0, 0]},
                               {"bone": "Spine", "rotation_degrees": [0, 0, 20]}]},
        {"frame": 11, "poses": [{"bone": "Root", "location": [0, 0, 0]},
                                {"bone": "Spine", "rotation_degrees": [0, 0, 20]}]},
    ])
    edit("keyframe_rig", name="QaRig", action_name="Explode", keyframes=[
        {"frame": 1, "poses": [{"bone": "Root", "scale": [1, 1, 1]}]},
        {"frame": 11, "poses": [{"bone": "Root", "scale": [10, 10, 10]}]},
    ])
    rig.animation_data.action = None
    bpy.context.scene.frame_set(7)
    bpy.context.view_layer.update()
    action = rig.animation_data.action
    frame = bpy.context.scene.frame_current

    moved = inspect("Move", ["root_motion", "loop"])
    root = moved["animation_checks"]["root_motion"]
    assert root["action"] == "Move" and root["samples"] == 4, root
    assert abs(root["root_bones"][0]["displacement"] - 2) < 1e-4, root
    assert abs(root["root_bones"][0]["horizontal"] - 2) < 1e-4, root
    assert root["loops"] is False
    assert moved["animation_checks"]["loop"]["loop_closes"] is False
    assert moved["analyzed_action"] == "Move"

    looped = inspect("Loop", ["loop"])
    assert looped["animation_checks"]["loop"]["loop_closes"] is True
    assert looped["animation_checks"]["loop"]["max_translation"] < 1e-4

    exploded = inspect("Explode", ["deformation"])
    deformation = exploded["animation_checks"]["deformation"][0]
    assert deformation["max_dimension_ratio"] > 5, deformation
    assert deformation["exploded"] is True, deformation
    assert deformation["non_finite"] is False

    assert rig.animation_data.action is action
    assert bpy.context.scene.frame_current == frame

    for params, message in [
        ({"action": "Missing", "checks": ["loop"]}, "does not exist"),
        ({"action": "Move", "checks": ["foot_slide"]}, "checks"),
        ({"action": "Move", "checks": ["deformation"], "samples": 33}, "samples"),
    ]:
        try:
            bridge.dispatch("inspect_rig", {
                "armature": "QaRig", "meshes": ["QaSkin"], **params})
        except ValueError as exc:
            assert message in str(exc), exc
        else:
            raise AssertionError(f"invalid QA accepted: {params}")

    print(json.dumps({
        "root_motion": root["root_bones"][0]["displacement"],
        "loop_closes": looped["animation_checks"]["loop"]["loop_closes"],
        "deformation_ratio": deformation["max_dimension_ratio"],
        "state_restored": True,
    }))
finally:
    folder.cleanup()
