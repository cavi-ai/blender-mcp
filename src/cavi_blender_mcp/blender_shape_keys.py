"""Shape-key authoring, value changes and atomic shape-key actions."""

import math

import bpy
from mathutils import Vector

from .blender_animation import ACTION_TAG
from .blender_bridge import info, number, obj

MAX_KEYS = 64
MAX_OFFSETS = 10000
MAX_FRAMES = 32
FRAME_MIN = 1
FRAME_MAX = 1000000
BASIS = "Basis"


def mesh(name):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before editing shape keys")
    value = obj(name, mesh=True)
    if value.data.users != 1:
        raise ValueError("Shape keys require single-user mesh data")
    return value


def key_name(value):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > 63:
        raise ValueError("Shape key names must be nonempty and at most 63 UTF-8 bytes")
    return value


def key_frame(value):
    if type(value) is not int or not FRAME_MIN <= value <= FRAME_MAX:
        raise ValueError(f"frame must be an integer from {FRAME_MIN} to {FRAME_MAX}")
    return value


def key_value(value):
    return number(value, 0, 1, "value")


def offsets(value):
    if not isinstance(value, list) or len(value) > MAX_OFFSETS:
        raise ValueError(f"offsets must list at most {MAX_OFFSETS} vertices")
    parsed = []
    for item in value:
        if not isinstance(item, list) or len(item) != 4:
            raise ValueError("offsets require [vertex_index, x, y, z]")
        index = item[0]
        if (type(index) not in (int, float) or not math.isfinite(index) or index < 0
                or int(index) != index):
            raise ValueError("offset vertex indices must be nonnegative integers")
        parsed.append((int(index), Vector(item[1:])))
    return parsed


def result(value):
    keys = value.data.shape_keys
    blocks = list(keys.key_blocks) if keys else []
    return {**info(value), "shape_keys": max(0, len(blocks) - 1),
            "shape_key_names": [block.name for block in blocks[1:]],
            "shape_key_action": keys.animation_data.action.name
            if keys and keys.animation_data and keys.animation_data.action else None}


def add(p):
    value = mesh(p["name"])
    name = key_name(p.get("new_name"))
    initial = key_value(p.get("value", 0))
    parsed = offsets(p.get("offsets")) if p.get("offsets") is not None else []
    source_name = p.get("source")
    source = mesh(source_name) if source_name is not None else None
    if source is not None and len(source.data.vertices) != len(value.data.vertices):
        raise ValueError("Source mesh must match the target vertex count")
    keys = value.data.shape_keys
    created_basis = False
    created = None
    try:
        if keys is None:
            value.shape_key_add(name=BASIS, from_mix=False)
            created_basis = True
            keys = value.data.shape_keys
        if len(keys.key_blocks) >= MAX_KEYS:
            raise ValueError(f"Meshes are limited to {MAX_KEYS} shape keys including Basis")
        if name in keys.key_blocks:
            raise ValueError("Shape key name already exists")
        created = value.shape_key_add(name=name, from_mix=False)
        if source is not None:
            for index, vertex in enumerate(source.data.vertices):
                created.data[index].co = vertex.co.copy()
        for index, offset in parsed:
            if index >= len(created.data):
                raise ValueError("Offset vertex index does not exist")
            created.data[index].co += offset
        created.value = initial
        value.data.update()
    except Exception:
        if created is not None:
            value.shape_key_remove(created)
        if created_basis:
            value.shape_key_clear()
        raise
    return result(value)


def set_value(p):
    value = mesh(p["name"])
    name = key_name(p.get("new_name"))
    keys = value.data.shape_keys
    key = keys.key_blocks.get(name) if keys else None
    if key is None:
        raise ValueError("Shape key does not exist")
    key.value = key_value(p.get("value"))
    value.data.update()
    return result(value)


def remove(p):
    value = mesh(p["name"])
    name = key_name(p.get("new_name"))
    keys = value.data.shape_keys
    key = keys.key_blocks.get(name) if keys else None
    if key is None:
        raise ValueError("Shape key does not exist")
    if key.name == BASIS:
        raise ValueError("Cannot remove the Basis shape key")
    value.shape_key_remove(key)
    value.data.update()
    return result(value)


def frames(value):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_FRAMES:
        raise ValueError(f"keyframes must list 1 to {MAX_FRAMES} frames")
    parsed, last = [], 0
    for item in value:
        if not isinstance(item, dict) or not set(item) <= {"frame", "value"}:
            raise ValueError("keyframes contain an unsupported entry")
        frame = key_frame(item.get("frame"))
        if frame <= last:
            raise ValueError("keyframe frames must be strictly increasing")
        parsed.append((frame, key_value(item.get("value"))))
        last = frame
    return parsed


def keyframe(p):
    value = mesh(p["name"])
    name = key_name(p.get("new_name"))
    action_name = p.get("action_name")
    if not isinstance(action_name, str) or not action_name.strip() or len(
            action_name.encode()) > 63:
        raise ValueError("action_name must be nonempty and at most 63 UTF-8 bytes")
    if action_name in bpy.data.actions:
        raise ValueError("Action name already exists")
    keys = value.data.shape_keys
    key = keys.key_blocks.get(name) if keys else None
    if key is None:
        raise ValueError("Shape key does not exist")
    sequence = frames(p.get("keyframes"))
    if keys.animation_data is None:
        keys.animation_data_create()
    animation = keys.animation_data
    previous_action = animation.action
    previous_slot = animation.action_slot
    previous_frame = bpy.context.scene.frame_current
    previous_value = key.value
    action = None
    try:
        action = bpy.data.actions.new(action_name)
        action.use_fake_user = True
        action[ACTION_TAG] = value.name
        animation.action = action
        for frame, amount in sequence:
            key.value = amount
            if not key.keyframe_insert("value", frame=frame):
                raise RuntimeError(f"Could not key {name} at frame {frame}")
        action.use_frame_range = True
        action.frame_start, action.frame_end = sequence[0][0], sequence[-1][0]
    except Exception:
        if action is not None:
            animation.action = previous_action
            if previous_action is not None and previous_slot is not None:
                try:
                    animation.action_slot = previous_slot
                except (TypeError, RuntimeError):
                    pass
            bpy.data.actions.remove(action)
        key.value = previous_value
        bpy.context.scene.frame_set(previous_frame)
        raise
    bpy.context.scene.frame_set(previous_frame)
    slot = animation.action_slot
    return {**result(value), "action": action.name,
            "action_slot": slot.identifier if slot else None,
            "frame_range": [sequence[0][0], sequence[-1][0]],
            "frames": [frame for frame, _ in sequence],
            "key": name}


HANDLERS = {"shape_key_add": add, "shape_key_value": set_value,
            "shape_key_remove": remove, "shape_key_keyframe": keyframe}
