"""Rest-axis mapping and clip-time alignment must not hide delivered position errors."""

import json
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Quaternion

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

folder = tempfile.TemporaryDirectory()
bridge._workspace = Path(folder.name)
state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch(
    "session_control",
    {"action": "claim", "owner": "delivered-contact-test", "expected_project": state["project_id"]},
)["lease_id"]


def edit(operation, **params):
    return bridge.dispatch(
        "owned_edit", {"operation": operation, "params": {**params, "lease_id": lease}}
    )


for name, roll, offset in [("Source", 0, 0), ("Candidate", 90, 2.5)]:
    edit(
        "create_armature",
        name=name,
        bones=[
            {"name": "Root", "head": [0, 0, 0], "tail": [0, 0, 0.3]},
            {
                "name": "Foot",
                "parent": "Root",
                "head": [0, 0, 0.1],
                "tail": [0, 0.3, 0.1],
                "roll_degrees": roll,
            },
        ],
    )
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8)
    skin = bpy.context.object
    skin.name = name + "Skin"
    edit("bind_skin", name=name, names=[skin.name])
    edit(
        "keyframe_rig",
        name=name,
        action_name=name + "Walk",
        keyframes=[
            {"frame": 1, "poses": [{"bone": "Root", "location": [0, 0, 0]}]},
            {"frame": 25, "poses": [{"bone": "Root", "location": [0, 0, 0]}]},
        ],
    )
    rig = bpy.data.objects[name]
    action = rig.animation_data.action
    action.frame_start = 1 + offset
    action.frame_end = 25 + offset
    rig.rotation_mode = "QUATERNION"
    for frame, angle in [(1 + offset, 0), (25 + offset, 0.4)]:
        rig.rotation_quaternion = Quaternion((0, 1, 0), angle)
        rig.keyframe_insert("rotation_quaternion", frame=frame)
    for layer in action.layers:
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", ()):
                for curve in bag.fcurves:
                    for point in curve.keyframe_points:
                        point.interpolation = "LINEAR"
window = {
    "bone": "Foot",
    "point": [0, 0, -0.1],
    "start_frame": 1,
    "end_frame": 25,
    "samples": 32,
    "max_drift_m": 0.0005,
    "max_height_error_m": 0.0005,
    "ground_z_m": 0,
}
scene = bpy.context.scene
scene.frame_set(9, subframe=0.25)
previous = (scene.frame_current, scene.frame_subframe)
args = {
    "armature": "Candidate",
    "meshes": ["CandidateSkin"],
    "action": "CandidateWalk",
    "contacts": [window],
    "contact_reference": {"armature": "Source", "action": "SourceWalk"},
    "contact_frame_offset": 2.5,
}
result = bridge.dispatch("inspect_rig", args)["animation_checks"]["contacts"][0]
assert result["passed"], result
assert (scene.frame_current, scene.frame_subframe) == previous
assert result["sample_frames"][0] == 3.5 and result["sample_frames"][-1] == 27.5, result
assert result["reference_basis_stable"], result
parent = bpy.data.objects.new("DeliveredOffset", None)
scene.collection.objects.link(parent)
bpy.data.objects["Candidate"].parent = parent
parent.location.z = 0.002
biased = bridge.dispatch("inspect_rig", args)["animation_checks"]["contacts"][0]
assert not biased["passed"] and biased["max_height_error_m"] > 0.0019, biased
assert (scene.frame_current, scene.frame_subframe) == previous
parent.location.z = 0
for frame, scale in [(3.5, 1), (27.5, 1.1)]:
    parent.scale.x = scale
    parent.keyframe_insert('scale', frame=frame)
unstable = bridge.dispatch("inspect_rig", args)["animation_checks"]["contacts"][0]
assert not unstable['passed'] and not unstable['reference_basis_stable'], unstable
assert (scene.frame_current, scene.frame_subframe) == previous
print(json.dumps({"aligned": result, "translated_candidate": biased, "unstable_axes": unstable}))
folder.cleanup()
