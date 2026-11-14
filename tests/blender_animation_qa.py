"""Native animation QA checks for root motion, loop seams and deformation."""

import json
import math
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
    assert root["coordinate_space"] == "armature"
    world = root["world_space"]
    assert world["coordinate_space"] == "world" and world["distance_unit"] == "m"
    assert abs(world["root_bones"][0]["displacement_m"] - 2) < 1e-4
    rig.scale = (0.01, 0.01, 0.01)
    bpy.context.view_layer.update()
    scaled = inspect("Move", ["root_motion"])["animation_checks"]["root_motion"]
    assert abs(scaled["root_bones"][0]["displacement"] - 2) < 1e-4
    assert abs(scaled["world_space"]["root_bones"][0]["displacement_m"] - .02) < 1e-4
    old_scale, old_rotation = rig.scale.copy(), rig.rotation_euler.copy()
    old_system = bpy.context.scene.unit_settings.system
    old_factor = bpy.context.scene.unit_settings.scale_length
    try:
        rig.rotation_euler = (0, math.pi / 2, 0)
        bpy.context.scene.unit_settings.system = "METRIC"
        bpy.context.scene.unit_settings.scale_length = 2
        bpy.context.view_layer.update()
        rotated = inspect("Move", ["root_motion"])["animation_checks"]["root_motion"]
        entry = rotated["world_space"]["root_bones"][0]
        assert abs(entry["vertical_m"] - .04) < 1e-4, entry
        assert entry["horizontal_m"] < 1e-4, entry
    finally:
        rig.scale, rig.rotation_euler = old_scale, old_rotation
        bpy.context.scene.unit_settings.system = old_system
        bpy.context.scene.unit_settings.scale_length = old_factor
    rig.scale = (1, 1, 1)
    parent = bpy.data.objects.new("QaMotionParent", None)
    bpy.context.scene.collection.objects.link(parent)
    old_parent = rig.parent
    try:
        rig.parent = parent
        for key_frame, x in ((1, 0), (6, 3), (11, 0)):
            parent.location.x = x
            parent.keyframe_insert(data_path="location", frame=key_frame)
        bpy.context.scene.frame_set(7)
        parented = inspect("Loop", ["root_motion"], samples=3)["animation_checks"]["root_motion"]
        assert parented["max_travel"] < 1e-4, parented
        assert parented["world_space"]["max_travel_m"] > 2.9, parented
        assert parented["world_space"]["loop_distance_m"] < 1e-4, parented
        assert bpy.context.scene.frame_current == 7
    finally:
        rig.parent = old_parent
        bpy.data.objects.remove(parent, do_unlink=True)
        bpy.context.view_layer.update()
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
