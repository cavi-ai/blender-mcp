"""Armature action assignment, rename/delete and NLA clip management."""

import bpy

from .blender_bridge import info, obj
from .blender_rig import action_slot

MAX_STRIPS = 32
FRAME_MIN = 1
FRAME_MAX = 1000000


def label(value, field="name"):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > 63:
        raise ValueError(f"{field} must be nonempty and at most 63 UTF-8 bytes")
    return value


def rig(params):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before managing clips")
    value = obj(params.get("name"))
    if value.type != "ARMATURE":
        raise ValueError("name must be an armature object")
    return value


def action(name):
    value = bpy.data.actions.get(name)
    if value is None:
        raise ValueError("Action does not exist")
    return value


def frame(value):
    if type(value) is not int or not FRAME_MIN <= value <= FRAME_MAX:
        raise ValueError(f"start_frame must be an integer from {FRAME_MIN} to {FRAME_MAX}")
    return value


def result(armature):
    animation = armature.animation_data
    slot = animation.action_slot if animation else None
    return {**info(armature), "active_action": animation.action.name
            if animation and animation.action else None,
            "action_slot": slot.identifier if slot else None,
            "nla_enabled": animation.use_nla if animation else False,
            "nla_tracks": [track.name for track in animation.nla_tracks]
            if animation else [],
            "nla_strips": sum(len(track.strips) for track in animation.nla_tracks)
            if animation else 0}


def set_action(p):
    armature = rig(p)
    if armature.animation_data is None:
        armature.animation_data_create()
    animation = armature.animation_data
    name = p.get("action_name")
    if name is None:
        animation.action = None
        return result(armature)
    value = action(name)
    animation.action = value
    animation.action_slot = action_slot(armature, value)
    return result(armature)


def rename_action(p):
    value = action(label(p.get("action_name"), "action_name"))
    new = label(p.get("new_name"), "new_name")
    if new == value.name:
        return {"action": value.name, "previous": value.name}
    if new in bpy.data.actions:
        raise ValueError("Action name already exists")
    previous = value.name
    value.name = new
    return {"action": value.name, "previous": previous}


def delete_action(p):
    value = action(label(p.get("action_name"), "action_name"))
    users = value.users - (1 if value.use_fake_user else 0)
    if users > 0:
        raise ValueError("Action is in use; clear active and NLA references first")
    name = value.name
    value.use_fake_user = False
    bpy.data.actions.remove(value)
    return {"deleted": name, "action_count": len(bpy.data.actions)}


def total_strips(animation):
    return sum(len(track.strips) for track in animation.nla_tracks)


def nla_push(p):
    armature = rig(p)
    if armature.animation_data is None:
        armature.animation_data_create()
    animation = armature.animation_data
    name = p.get("action_name")
    value = animation.action if name is None else action(label(name, "action_name"))
    if value is None:
        raise ValueError("Provide action_name or set an active action")
    slot = action_slot(armature, value)
    track_name = label(p.get("track_name") or value.name, "track_name")
    strip_name = label(p.get("strip_name") or value.name, "strip_name")
    start = frame(p.get("start_frame", 1))
    if total_strips(animation) >= MAX_STRIPS:
        raise ValueError(f"Rigs are limited to {MAX_STRIPS} NLA strips")
    track = next((item for item in animation.nla_tracks if item.name == track_name), None)
    created_track = track is None
    strip = None
    try:
        if track is None:
            track = animation.nla_tracks.new()
            track.name = track_name
        if any(item.name == strip_name for item in track.strips):
            raise ValueError("Strip name already exists on this track")
        strip = track.strips.new(strip_name, start, value)
        strip.name = strip_name
        strip.action_slot = slot
        value.use_fake_user = True
        animation.action = None
        animation.use_nla = True
    except Exception:
        if strip is not None and strip.name in track.strips:
            track.strips.remove(strip)
        if created_track and track is not None and not track.strips and track.name == track_name:
            animation.nla_tracks.remove(track)
        raise
    return {**result(armature), "action": value.name, "track": track.name,
            "strip": strip.name, "start_frame": start,
            "frame_range": [strip.frame_start, strip.frame_end],
            "action_frame_range": list(value.frame_range)}


def nla_remove(p):
    armature = rig(p)
    animation = armature.animation_data
    if animation is None:
        return {**result(armature), "removed_tracks": [], "removed_strips": 0}
    track_name = p.get("track_name")
    strip_name = p.get("strip_name")
    if strip_name is not None and track_name is None:
        raise ValueError("strip_name requires track_name")
    if track_name is None:
        removed = [track.name for track in animation.nla_tracks]
        for track in list(animation.nla_tracks):
            animation.nla_tracks.remove(track)
        strips = 0
    else:
        label(track_name, "track_name")
        track = next((item for item in animation.nla_tracks if item.name == track_name), None)
        if track is None:
            raise ValueError("NLA track does not exist")
        removed, strips = [], 0
        if strip_name is None:
            strips = len(track.strips)
            removed = [track.name]
            animation.nla_tracks.remove(track)
        else:
            label(strip_name, "strip_name")
            strip = next((item for item in track.strips if item.name == strip_name), None)
            if strip is None:
                raise ValueError("NLA strip does not exist")
            track.strips.remove(strip)
            strips = 1
            if not track.strips:
                removed = [track.name]
                animation.nla_tracks.remove(track)
    return {**result(armature), "removed_tracks": removed, "removed_strips": strips}


HANDLERS = {"set_action": set_action, "rename_action": rename_action,
            "delete_action": delete_action, "nla_push": nla_push,
            "nla_remove": nla_remove}
