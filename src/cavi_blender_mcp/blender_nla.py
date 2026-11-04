"""Armature action assignment, rename/delete and NLA clip management."""

import math

import bpy

from .blender_bridge import info, obj
from .blender_nla_settings import FIELDS, validate
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


def strip_settings(strip):
    return {key: getattr(strip, key) for key in FIELDS}


def inventory(armature):
    animation = armature.animation_data
    if animation is None:
        return []
    return [{'name': track.name, 'mute': track.mute, 'solo': track.is_solo,
             'strips': [{'name': strip.name, 'type': strip.type,
                         'action': strip.action.name if strip.action else None,
                         'frame_range': [strip.frame_start, strip.frame_end],
                         'strip_settings': strip_settings(strip) if strip.type == 'CLIP' else None}
                        for strip in track.strips]} for track in animation.nla_tracks]


def write_settings(strip, values):
    # Set the end first when moving an action range beyond its previous end.
    if values['action_frame_start'] >= strip.action_frame_end:
        strip.action_frame_end = values['action_frame_end']
        strip.action_frame_start = values['action_frame_start']
    else:
        strip.action_frame_start = values['action_frame_start']
        strip.action_frame_end = values['action_frame_end']
    strip.repeat = values['repeat']
    strip.scale = values['scale']
    duration = (values['action_frame_end']-values['action_frame_start'])*values['scale']*values['repeat']
    strip.frame_start_raw = values['frame_start']
    strip.frame_end_raw = values['frame_start']+duration
    strip.use_auto_blend = values['use_auto_blend']
    for key in FIELDS:
        if key not in {'frame_start', 'action_frame_start', 'action_frame_end', 'scale', 'repeat', 'use_auto_blend'}:
            setattr(strip, key, values[key])


def configure_strip(track, strip, changes):
    validate(changes)
    before = strip_settings(strip)
    desired = {**before, **changes}
    duration = (desired['action_frame_end']-desired['action_frame_start'])*desired['scale']*desired['repeat']
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('NLA action frame range must increase')
    if desired['blend_in']+desired['blend_out'] > duration and not desired['use_auto_blend']:
        raise ValueError('NLA fades must fit the resulting strip duration')
    if desired['use_auto_blend'] and {'blend_in', 'blend_out'} & set(changes):
        raise ValueError('Disable automatic blending before setting manual fades')
    end = desired['frame_start']+duration
    neighbors = [(other, other.frame_start, other.frame_end) for other in track.strips if other != strip]
    if any(desired['frame_start'] < last and end > first for _, first, last in neighbors):
        raise ValueError('NLA strips cannot overlap on one track; use a separate blend track')
    try:
        write_settings(strip, desired)
        actual = strip_settings(strip)
        for key, expected in desired.items():
            if key in {'blend_in', 'blend_out'} and desired['use_auto_blend']:
                continue
            observed = actual[key]
            matches = math.isclose(observed, expected, abs_tol=1e-5, rel_tol=1e-7) if type(expected) in (int, float) else observed == expected
            if not matches:
                raise ValueError('Blender clamped or changed NLA setting: ' + key)
        if not math.isclose(strip.frame_end, end, abs_tol=1e-5, rel_tol=1e-7):
            raise ValueError('Blender changed the requested NLA duration')
        if any(other.frame_start != first or other.frame_end != last for other, first, last in neighbors):
            raise ValueError('Blender changed a neighboring NLA strip')
    except Exception:
        write_settings(strip, before)
        for other, first, last in neighbors:
            other.frame_start_raw, other.frame_end_raw = first, last
        raise
    return actual


def strip_result(armature, track, strip):
    return {**result(armature), 'action': strip.action.name, 'track': track.name, 'strip': strip.name,
            'start_frame': strip.frame_start, 'frame_range': [strip.frame_start, strip.frame_end],
            'action_frame_range': [strip.action_frame_start, strip.action_frame_end],
            'strip_settings': strip_settings(strip)}


def nla_edit(p):
    armature = rig(p)
    animation = armature.animation_data
    track_name = label(p.get('track_name'), 'track_name')
    strip_name = label(p.get('strip_name'), 'strip_name')
    track = animation.nla_tracks.get(track_name) if animation else None
    strip = track.strips.get(strip_name) if track else None
    if strip is None or strip.type != 'CLIP' or strip.action is None:
        raise ValueError('Named NLA action strip does not exist')
    if animation.use_tweak_mode:
        raise ValueError('Exit NLA Tweak Mode before editing strip settings')
    configure_strip(track, strip, p.get('strip_settings'))
    return strip_result(armature, track, strip)


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
        if p.get('strip_settings') is not None:
            configure_strip(track, strip, p['strip_settings'])
        value.use_fake_user = True
        animation.action = None
        animation.use_nla = True
    except Exception:
        if strip is not None and strip.name in track.strips:
            track.strips.remove(strip)
        if created_track and track is not None and not track.strips and track.name == track_name:
            animation.nla_tracks.remove(track)
        raise
    return strip_result(armature, track, strip)


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
            "nla_edit": nla_edit, "nla_remove": nla_remove}
