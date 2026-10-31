"""Pose authoring and atomic action creation for armatures."""

import math

import bpy
from mathutils import Euler

from .blender_bridge import info, obj, vector

MAX_BONES = 128
MAX_POSES = 128
MAX_FRAMES = 32
MAX_TOTAL_POSES = 2048
POSE_KEYS = {"bone", "rotation_degrees", "location", "scale"}
FRAME_MIN = 1
FRAME_MAX = 1000000
ACTION_TAG = "cavi_rig_action"


def rig(params):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before posing")
    value = obj(params.get("name"))
    if value.type != "ARMATURE":
        raise ValueError("name must be an armature object")
    if len(value.data.bones) > MAX_BONES:
        raise ValueError(f"Pose authoring is limited to {MAX_BONES} bones")
    return value


def frame_number(value):
    if type(value) is not int or not FRAME_MIN <= value <= FRAME_MAX:
        raise ValueError(f"frame must be an integer from {FRAME_MIN} to {FRAME_MAX}")
    return value


def parse_poses(specs, armature):
    if not isinstance(specs, list) or not 1 <= len(specs) <= MAX_POSES:
        raise ValueError(f"poses must list 1 to {MAX_POSES} bone transforms")
    parsed, names = [], set()
    for spec in specs:
        if not isinstance(spec, dict) or not set(spec) <= POSE_KEYS:
            raise ValueError("poses contains an unsupported specification")
        name = spec.get("bone")
        if not isinstance(name, str) or not name or len(name.encode()) > 63:
            raise ValueError("bone names must be nonempty and at most 63 UTF-8 bytes")
        if name in names:
            raise ValueError(f"Bone {name} is repeated")
        names.add(name)
        if name not in armature.pose.bones:
            raise ValueError(f"Bone {name} does not exist on {armature.name}")
        item = {"bone": name}
        for key in ("rotation_degrees", "location", "scale"):
            value = spec.get(key)
            if value is not None:
                item[key] = vector(value)
        if "scale" in item and any(value <= 0 for value in item["scale"]):
            raise ValueError("Pose scale components must be positive")
        if len(item) == 1:
            raise ValueError(f"Pose for {name} needs rotation, location or scale")
        parsed.append(item)
    return parsed


def parse_keyframes(value, armature):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_FRAMES:
        raise ValueError(f"keyframes must list 1 to {MAX_FRAMES} frames")
    parsed, last, total = [], 0, 0
    for item in value:
        if not isinstance(item, dict) or not set(item) <= {"frame", "poses"}:
            raise ValueError("keyframes contains an unsupported specification")
        frame = frame_number(item.get("frame"))
        if frame <= last:
            raise ValueError("keyframe frames must be strictly increasing")
        poses = parse_poses(item.get("poses"), armature)
        total += len(poses)
        if total > MAX_TOTAL_POSES:
            raise ValueError(f"Action is limited to {MAX_TOTAL_POSES} poses")
        parsed.append((frame, poses))
        last = frame
    return parsed


def snapshot(armature):
    return {bone.name: {
        "rotation_mode": bone.rotation_mode,
        "rotation_euler": bone.rotation_euler.copy(),
        "rotation_quaternion": bone.rotation_quaternion.copy(),
        "rotation_axis_angle": tuple(bone.rotation_axis_angle),
        "location": bone.location.copy(),
        "scale": bone.scale.copy(),
    } for bone in armature.pose.bones}


def restore(armature, state):
    for name, saved in state.items():
        bone = armature.pose.bones.get(name)
        if bone is None:
            continue
        bone.rotation_mode = saved["rotation_mode"]
        bone.rotation_euler = saved["rotation_euler"]
        bone.rotation_quaternion = saved["rotation_quaternion"]
        bone.rotation_axis_angle = saved["rotation_axis_angle"]
        bone.location = saved["location"]
        bone.scale = saved["scale"]


def reset(armature):
    for bone in armature.pose.bones:
        if bone.rotation_mode == "QUATERNION":
            bone.rotation_quaternion = (1, 0, 0, 0)
        elif bone.rotation_mode == "AXIS_ANGLE":
            bone.rotation_axis_angle = (0, 0, 1, 0)
        else:
            bone.rotation_euler = (0, 0, 0)
        bone.location = (0, 0, 0)
        bone.scale = (1, 1, 1)


def apply(armature, poses):
    for item in poses:
        bone = armature.pose.bones[item["bone"]]
        if "rotation_degrees" in item:
            bone.rotation_mode = "XYZ"
            bone.rotation_euler = Euler(
                [math.radians(value) for value in item["rotation_degrees"]], "XYZ")
        if "location" in item:
            bone.location = item["location"]
        if "scale" in item:
            bone.scale = item["scale"]


def pose_rig(p):
    armature = rig(p)
    poses = parse_poses(p.get("poses"), armature)
    reset_first = p.get("reset", False)
    if type(reset_first) is not bool:
        raise ValueError("reset must be boolean")
    frame = p.get("frame")
    if frame is not None:
        frame = frame_number(frame)
    state = snapshot(armature)
    try:
        if frame is not None:
            bpy.context.scene.frame_set(frame)
        if reset_first:
            reset(armature)
        apply(armature, poses)
    except Exception:
        restore(armature, state)
        raise
    return {**info(armature), "frame": frame, "reset": reset_first,
            "posed": [item["bone"] for item in poses]}


def clear_pose(p):
    armature = rig(p)
    frame = p.get("frame")
    if frame is not None:
        frame = frame_number(frame)
    state = snapshot(armature)
    try:
        if frame is not None:
            bpy.context.scene.frame_set(frame)
        reset(armature)
    except Exception:
        restore(armature, state)
        raise
    return {**info(armature), "frame": frame, "reset_bones": len(armature.pose.bones)}


def previous_action(armature):
    if armature.animation_data is None:
        return None, None
    return armature.animation_data.action, armature.animation_data.action_slot


def restore_action(armature, action, slot):
    if armature.animation_data is None:
        armature.animation_data_create()
    armature.animation_data.action = action
    if action is not None and slot is not None:
        try:
            armature.animation_data.action_slot = slot
        except (TypeError, RuntimeError):
            pass


def keyframe_rig(p):
    armature = rig(p)
    name = p.get("action_name")
    if not isinstance(name, str) or not name.strip() or len(name.encode()) > 63:
        raise ValueError("action_name must be nonempty and at most 63 UTF-8 bytes")
    if name in bpy.data.actions:
        raise ValueError("Action name already exists")
    keyframes = parse_keyframes(p.get("keyframes"), armature)
    state, action = snapshot(armature), None
    old_action, old_slot = previous_action(armature)
    try:
        armature.animation_data_create()
        action = bpy.data.actions.new(name)
        action.use_fake_user = True
        action[ACTION_TAG] = armature.name
        armature.animation_data.action = action
        keyed = set()
        for frame, poses in keyframes:
            for item in poses:
                bone = armature.pose.bones[item["bone"]]
                if "rotation_degrees" in item:
                    bone.rotation_mode = "XYZ"
                    bone.rotation_euler = Euler(
                        [math.radians(value) for value in item["rotation_degrees"]], "XYZ")
                    if not bone.keyframe_insert("rotation_euler", frame=frame):
                        raise RuntimeError(f"Could not key {item['bone']} rotation")
                if "location" in item:
                    bone.location = item["location"]
                    if not bone.keyframe_insert("location", frame=frame):
                        raise RuntimeError(f"Could not key {item['bone']} location")
                if "scale" in item:
                    bone.scale = item["scale"]
                    if not bone.keyframe_insert("scale", frame=frame):
                        raise RuntimeError(f"Could not key {item['bone']} scale")
                keyed.add(item["bone"])
        action.use_frame_range = True
        action.frame_start, action.frame_end = keyframes[0][0], keyframes[-1][0]
    except Exception:
        if action is not None:
            restore_action(armature, old_action, old_slot)
            bpy.data.actions.remove(action)
        restore(armature, state)
        raise
    slot = armature.animation_data.action_slot
    return {**info(armature), "armature": armature.name, "action": action.name,
            "action_slot": slot.identifier if slot else None,
            "frame_range": [keyframes[0][0], keyframes[-1][0]],
            "frames": [frame for frame, _ in keyframes],
            "keyed_bones": sorted(keyed), "pose_keys": sum(len(poses) for _, poses in keyframes)}


HANDLERS = {"pose_rig": pose_rig, "keyframe_rig": keyframe_rig, "clear_pose": clear_pose}
