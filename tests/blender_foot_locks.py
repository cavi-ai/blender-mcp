"""Native editable foot locking: contact, ramps, authored action and rollback."""

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
lease = bridge.dispatch(
    "session_control",
    {"action": "claim", "owner": "foot-lock-native", "expected_project": state["project_id"]},
)["lease_id"]


def edit(operation, **params):
    return bridge.dispatch(
        "owned_edit", {"operation": operation, "params": {**params, "lease_id": lease}}
    )


edit(
    "create_armature",
    name="Rig",
    bones=[
        {"name": "Root", "head": [0, 0, 1.7], "tail": [0, 0, 1.9]},
        {"name": "Thigh", "parent": "Root", "head": [0, 0, 1.7], "tail": [0, -0.15, 0.9]},
        {
            "name": "Shin",
            "parent": "Thigh",
            "head": [0, -0.15, 0.9],
            "tail": [0, 0, 0.1],
            "connect": True,
        },
        {
            "name": "Foot",
            "parent": "Shin",
            "head": [0, 0, 0.1],
            "tail": [0, -0.3, 0.1],
            "connect": True,
        },
        {"name": "Head", "parent": "Root", "head": [0, 0, 1.9], "tail": [0, 0, 2.1]},
    ],
)
rig = bpy.data.objects["Rig"]
scene = bpy.context.scene
bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8)
skin = bpy.context.object
skin.name = "Skin"
edit("bind_skin", name="Rig", names=["Skin"])
edit(
    "keyframe_rig",
    name="Rig",
    action_name="Sliding",
    keyframes=[
        {"frame": 1, "poses": [{"bone": "Root", "location": [0, 0, 0]}]},
        {"frame": 13, "poses": [{"bone": "Root", "location": [0.12, 0, 0]}]},
        {"frame": 25, "poses": [{"bone": "Root", "location": [0, 0, 0]}]},
    ],
)


def inspect(window, action, name="Rig", meshes=None):
    return bridge.dispatch(
        "inspect_rig",
        {"armature": name, "meshes": meshes or ["Skin"], "action": action, "contacts": [window]},
    )["animation_checks"]["contacts"][0]


window = {
    "bone": "Foot",
    "point": [0, 0, -0.1],
    "start_frame": 5,
    "end_frame": 21,
    "samples": 32,
    "max_drift_m": 0.0005,
    "max_height_error_m": 0.0005,
    "ground_z_m": 0,
}
before = inspect(window, "Sliding")
assert not before["passed"] and before["max_drift_m"] > 0.05, before
source = bpy.data.actions["Sliding"]
original = source.as_pointer()
scene.frame_set(10, subframe=0.25)
frame = (scene.frame_current, scene.frame_subframe)
result = edit(
    "lock_rig_contacts",
    name="Rig",
    source_action="Sliding",
    action_name="Planted",
    new_name="GroundedRig",
    names=["Skin"],
    foot_locks=[
        {
            **window,
            "pole": [0, -2, 1],
            "pole_angle_degrees": 0,
            "blend_in_frames": 3,
            "blend_out_frames": 3,
        }
    ],
)
assert (scene.frame_current, scene.frame_subframe) == frame
assert bpy.data.actions["Sliding"].as_pointer() == original
assert inspect(window, "Sliding") == before
corrected = inspect(window, "Planted", "GroundedRig", ["GroundedRig_Skin1"])
assert corrected["passed"], corrected
assert rig.animation_data.action.name == "Sliding"
rig = bpy.data.objects["GroundedRig"]
assert rig.animation_data.action.name == "Planted"
for f, influence in [(1, 0), (5, 1), (21, 1), (25, 0)]:
    scene.frame_set(f)
    bpy.context.view_layer.update()
    assert abs(rig.pose.bones["Shin"].constraints["ContactLock_00_IK"].influence - influence) < 1e-6
assert rig.pose.bones["Foot"].constraints["ContactLock_00_Rotation"].type == "COPY_ROTATION"
# Invalid overlapping windows must not create actions, controls or constraints.
objects, actions = set(bpy.data.objects), set(bpy.data.actions)
try:
    edit(
        "lock_rig_contacts",
        name="Rig",
        source_action="Sliding",
        action_name="Bad",
        new_name="BadRig",
        foot_locks=[{**window, "pole": [0, -2, 1]}] * 2,
    )
except ValueError:
    pass
else:
    raise AssertionError("Overlapping corrections accepted")
assert objects == set(bpy.data.objects) and actions == set(bpy.data.actions)
# A failure after creating controls must remove only the generated copy and controls.
from unittest.mock import patch

from cavi_blender_mcp import blender_foot_locks

pools = {key: set(getattr(bpy.data, key)) for key in ("objects", "meshes", "armatures", "actions")}
with patch.object(
    blender_foot_locks, "influence_keys", side_effect=RuntimeError("injected key failure")
):
    try:
        edit(
            "lock_rig_contacts",
            name="Rig",
            source_action="Sliding",
            action_name="Interrupted",
            new_name="InterruptedRig",
            names=["Skin"],
            foot_locks=[{**window, "pole": [0, -2, 1]}],
        )
    except RuntimeError as exc:
        assert "injected" in str(exc)
    else:
        raise AssertionError("Failure injection did not run")
assert all(set(getattr(bpy.data, key)) == values for key, values in pools.items())
assert inspect(window, "Sliding") == before
print(json.dumps({"before": before, "corrected": corrected, "receipt": result}))
folder.cleanup()
