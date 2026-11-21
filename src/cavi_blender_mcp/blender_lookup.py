"""Scene object lookup and exclusive output reservation."""

import math
import os
from contextlib import contextmanager

import bpy
from mathutils import Euler, Quaternion, Vector

from .paths import destination

MAX_MODIFIERS = 16
RENDERLESS = frozenset({"CAMERA", "LIGHT", "LIGHT_PROBE", "LIGHTPROBE", "SPEAKER"})

_workspace = None


def set_workspace(path):
    global _workspace
    _workspace = path


def workspace():
    return _workspace


def vector(values, size=3):
    if not isinstance(values, (tuple, list)) or len(values) != size:
        raise ValueError(f"Expected {size} components")
    if any(type(v) not in (float, int) or not math.isfinite(v) or abs(v) > 1e6 for v in values):
        raise ValueError("Expected bounded finite numbers")
    return values


def number(value, low, high, label):
    if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be a number from {low} to {high}")
    return float(value)


def obj(name, mesh=False):
    value = bpy.data.objects.get(name)
    if value is None or value.name not in bpy.context.scene.objects:
        raise ValueError("Object does not exist in the current scene")
    if mesh and value.type != "MESH":
        raise ValueError("Object must be a mesh")
    return value


def editable_mesh(name):
    value = obj(name, mesh=True)
    if value.data.users > 1:
        raise ValueError("Mesh data is shared; use object_edit make_single_user before editing")
    return value


def rotation(value):
    mode = value.rotation_mode
    if mode == "QUATERNION":
        return value.rotation_quaternion.normalized()
    if mode == "AXIS_ANGLE":
        angle, *axis = value.rotation_axis_angle
        axis = Vector(axis)
        return Quaternion() if axis.length < 1e-12 else Quaternion(axis.normalized(), angle)
    return value.rotation_euler.to_quaternion()


def set_rotation(value, degrees):
    euler = Euler([math.radians(v) for v in degrees], "XYZ")
    mode = value.rotation_mode
    if mode == "QUATERNION":
        value.rotation_quaternion = euler.to_quaternion()
    elif mode == "AXIS_ANGLE":
        axis, angle = euler.to_quaternion().to_axis_angle()
        value.rotation_axis_angle = (angle, *axis)
    elif mode == "XYZ":
        value.rotation_euler = euler
    else:
        value.rotation_euler = euler.to_matrix().to_euler(mode, value.rotation_euler)


def info(value,*,modifier_schema=False):
    from .blender_modifiers import inspect as inspect_modifier

    angles = (
        value.rotation_euler if value.rotation_mode == "XYZ" else rotation(value).to_euler("XYZ")
    )
    result = {
        "name": value.name,
        "type": value.type,
        "location": list(value.location),
        "rotation_degrees": [math.degrees(v) for v in angles],
        "rotation_mode": value.rotation_mode,
        "scale": list(value.scale),
        "dimensions": list(value.dimensions),
        "parent": value.parent.name if value.parent else None,
        "children": len(value.children),
        "collections": [item.name for item in value.users_collection],
        "modifiers": [inspect_modifier(m,detailed=modifier_schema) for m in value.modifiers],
    }
    if value.type == 'CAMERA':
        data = value.data
        result['camera'] = {'projection': data.type, 'focal_length_mm': data.lens,
            'sensor_width_mm': data.sensor_width, 'ortho_scale': data.ortho_scale,
            'clip': [data.clip_start, data.clip_end], 'shift': [data.shift_x, data.shift_y],
            'depth_of_field': data.dof.use_dof, 'focus_distance': data.dof.focus_distance,
            'fstop': data.dof.aperture_fstop}
    elif value.type == 'LIGHT':
        data = value.data
        result['light'] = {'type': data.type, 'energy': data.energy, 'color': list(data.color)}
    if value.type == "MESH":
        result.update(
            vertices=len(value.data.vertices),
            polygons=len(value.data.polygons),
            uv_layers=len(value.data.uv_layers),
            materials=[slot.material.name if slot.material else None
                       for slot in value.material_slots],
            shape_keys=(len(value.data.shape_keys.key_blocks) - 1
                       if value.data.shape_keys is not None else 0),
            shape_key_names=([block.name for block in
                              value.data.shape_keys.key_blocks[1:]][:64]
                             if value.data.shape_keys is not None else []),
            shape_key_action=(
                value.data.shape_keys.animation_data.action.name
                if value.data.shape_keys is not None
                and value.data.shape_keys.animation_data is not None
                and value.data.shape_keys.animation_data.action is not None else None),
        )
    return result


@contextmanager
def selected(objects):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before this operation")
    previous = list(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    try:
        for value in previous:
            value.select_set(False)
        for value in objects:
            if value.hide_get() or value.hide_viewport:
                raise ValueError("Requested object is hidden")
            value.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        yield
    finally:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for value in bpy.context.selected_objects:
            value.select_set(False)
        for value in previous:
            try:
                value.select_set(True)
            except ReferenceError:
                continue
        if active is not None:
            try:
                bpy.context.view_layer.objects.active = active
            except ReferenceError:
                pass


@contextmanager
def output_file(path, extensions):
    target = destination(workspace(), path, extensions)
    # Reserve exclusively before asking Blender to write; never clobber an existing asset.
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        yield target
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError("Blender did not produce an output file")
    except Exception:
        target.unlink(missing_ok=True)
        raise


def new_name(name):
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 63
        or name in bpy.data.objects
    ):
        raise ValueError("Object name must be unique, nonempty, and at most 63 characters")
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before creating geometry")
    return name


def with_empties(objects):
    """Empty ancestors for hierarchy plus empty descendants such as sockets."""
    scene = bpy.context.scene.objects
    selection = list(objects)
    for value in objects:
        parent = value.parent
        while parent is not None:
            if parent.type == "EMPTY" and parent not in selection and parent.name in scene:
                selection.append(parent)
            parent = parent.parent
    stack = [child for value in objects for child in value.children]
    while stack:
        child = stack.pop()
        if child.type == "EMPTY" and child not in selection and child.name in scene:
            selection.append(child)
            stack.extend(child.children)
    return selection
