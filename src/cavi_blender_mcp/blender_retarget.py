"""Bake a source armature action onto a target rig by bone mapping."""

import math

import bpy

from .blender_animation import ACTION_TAG, previous_action, restore, restore_action, snapshot
from .blender_bridge import info, obj
from .blender_rig import action_slot, sample_frames

MAX_BONES = 512
MAX_MAPPING = 128
MAX_FRAMES = 1000
MAX_KEYFRAMES = 100000


def armature(name):
    value = obj(name)
    if value.type != "ARMATURE":
        raise ValueError("source and target must be armature objects")
    if len(value.data.bones) > MAX_BONES:
        raise ValueError(f"Retargeting is limited to {MAX_BONES} bones")
    return value


def mapping_for(source, target, value):
    if value is None:
        pairs = {bone.name: bone.name for bone in source.data.bones
                 if bone.name in target.pose.bones}
    else:
        if not isinstance(value, dict) or not 1 <= len(value) <= MAX_MAPPING:
            raise ValueError(f"mapping must list 1 to {MAX_MAPPING} bone pairs")
        pairs = {}
        for key, item in value.items():
            if (not isinstance(key, str) or not isinstance(item, str) or not key or not item
                    or len(key.encode()) > 63 or len(item.encode()) > 63):
                raise ValueError("mapping needs nonempty bone names of at most 63 bytes")
            if key not in source.pose.bones:
                raise ValueError(f"Source bone {key} does not exist")
            if item not in target.pose.bones:
                raise ValueError(f"Target bone {item} does not exist")
            pairs[key] = item
        if len(set(pairs.values())) != len(pairs):
            raise ValueError("mapping must use each target bone at most once")
    if not pairs:
        raise ValueError("No matching bones; provide a mapping")
    return pairs


def frames_for(action, samples):
    start, end = action.frame_range
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError("Source action needs a finite non-empty frame range")
    if samples is not None:
        if type(samples) is not int or not 2 <= samples <= 256:
            raise ValueError("samples must be an integer from 2 to 256")
        return sample_frames(action, samples)
    frames = list(range(math.ceil(start), math.floor(end) + 1))
    if not 1 <= len(frames) <= MAX_FRAMES:
        raise ValueError(f"Source action needs 1 to {MAX_FRAMES} frames or explicit samples")
    return frames


def depth_order(target, pairs):
    depths = {}
    for bone in target.data.bones:
        depth, parent = 0, bone.parent
        while parent is not None:
            depth += 1
            parent = parent.parent
        depths[bone.name] = depth
    return sorted(pairs.items(), key=lambda item: depths[item[1]])


def retarget(p):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before retargeting")
    target = armature(p.get("name"))
    source = armature(p.get("source"))
    if source == target:
        raise ValueError("source and target must be different armatures")
    source_name = p.get("source_action")
    if (not isinstance(source_name, str) or not source_name
            or len(source_name.encode()) > 63):
        raise ValueError("source_action must be a nonempty action name")
    source_action = bpy.data.actions.get(source_name)
    if source_action is None:
        raise ValueError("Source action does not exist")
    target_name = p.get("action_name")
    if (not isinstance(target_name, str) or not target_name
            or len(target_name.encode()) > 63):
        raise ValueError("action_name must be a nonempty action name")
    if target_name in bpy.data.actions:
        raise ValueError("Action name already exists")
    pairs = mapping_for(source, target, p.get("mapping"))
    frames = frames_for(source_action, p.get("samples"))
    if len(frames) * len(pairs) > MAX_KEYFRAMES:
        raise ValueError(f"Retargeting is limited to {MAX_KEYFRAMES} keyframes")
    ordered = depth_order(target, pairs)
    scene = bpy.context.scene
    previous_frame = scene.frame_current
    source_action_old, source_slot_old = previous_action(source)
    target_action_old, target_slot_old = previous_action(target)
    pose = snapshot(target)
    action = None
    try:
        if source.animation_data is None:
            source.animation_data_create()
        source.animation_data.action = source_action
        source.animation_data.action_slot = action_slot(source, source_action)
        target.animation_data_create()
        action = bpy.data.actions.new(target_name)
        action.use_fake_user = True
        action[ACTION_TAG] = target.name
        target.animation_data.action = action
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            for src_bone, dst_bone in ordered:
                target_bone = target.pose.bones[dst_bone]
                target_bone.rotation_mode = "QUATERNION"
                target_bone.matrix = (target.matrix_world.inverted()
                                      @ source.matrix_world
                                      @ source.pose.bones[src_bone].matrix)
            for src_bone, dst_bone in ordered:
                target_bone = target.pose.bones[dst_bone]
                if not target_bone.keyframe_insert("location", frame=frame):
                    raise RuntimeError(f"Could not key {dst_bone} location")
                if not target_bone.keyframe_insert("rotation_quaternion", frame=frame):
                    raise RuntimeError(f"Could not key {dst_bone} rotation")
                if not target_bone.keyframe_insert("scale", frame=frame):
                    raise RuntimeError(f"Could not key {dst_bone} scale")
        action.use_frame_range = True
        action.frame_start, action.frame_end = frames[0], frames[-1]
    except Exception:
        if action is not None:
            restore_action(target, target_action_old, target_slot_old)
            bpy.data.actions.remove(action)
        restore_action(source, source_action_old, source_slot_old)
        scene.frame_set(previous_frame)
        restore(target, pose)
        raise
    restore_action(source, source_action_old, source_slot_old)
    scene.frame_set(previous_frame)
    slot = target.animation_data.action_slot
    mapped = [{"source": src, "target": dst} for src, dst in ordered]
    return {**info(target), "armature": target.name, "source": source.name,
            "source_action": source_action.name, "action": action.name,
            "action_slot": slot.identifier if slot else None,
            "frames": [frames[0], frames[-1]], "samples": len(frames),
            "mapped": mapped,
            "unmapped_source": sorted(bone.name for bone in source.data.bones
                                      if bone.name not in pairs),
            "unmapped_target": sorted(bone.name for bone in target.data.bones
                                      if bone.name not in set(pairs.values())),
            "keyed_bones": [dst for _, dst in ordered]}
