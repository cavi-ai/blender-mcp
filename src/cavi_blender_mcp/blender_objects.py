"""Object-level pipeline edits: transforms, origins, names and sockets."""

import math

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

from .blender_bridge import editable_mesh, info, new_name, number, obj, vector

COMPONENTS = ("location", "rotation", "scale")
ORIGINS = {"bounds_bottom_center", "bounds_center", "world_origin", "point"}


def object_mode():
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before this operation")


def reparent_children(value, delta):
    for child in value.children:
        child.matrix_parent_inverse = delta @ child.matrix_parent_inverse


def apply_transforms(p):
    object_mode()
    value = obj(p["name"], mesh=True)
    components = p.get("components", ["rotation", "scale"])
    if (not isinstance(components, list) or not components
            or len(set(components)) != len(components)
            or any(c not in COMPONENTS for c in components)):
        raise ValueError("components must list location, rotation and/or scale once")
    single = p.get("make_single_user", False)
    if type(single) is not bool:
        raise ValueError("make_single_user must be boolean")
    if value.data.users > 1:
        if not single:
            raise ValueError("Mesh data is shared; pass make_single_user=true to copy it")
        value.data = value.data.copy()
    location, rotation, scale = value.matrix_basis.decompose()
    kept = Matrix.LocRotScale(
        None if "location" in components else location,
        None if "rotation" in components else rotation,
        None if "scale" in components else scale,
    )
    delta = kept.inverted_safe() @ value.matrix_basis
    value.data.transform(delta, shape_keys=True)
    if delta.determinant() < 0:
        value.data.flip_normals()
    value.data.update()
    value.matrix_basis = kept
    reparent_children(value, delta)
    return {**info(value), "applied": components, "single_user": value.data.users == 1}


def local_bounds(value):
    count = len(value.data.vertices)
    if not count:
        raise ValueError("Mesh has no vertices")
    co = np.empty(count * 3, np.float64)
    value.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    return co.min(axis=0), co.max(axis=0)


def set_origin(p):
    object_mode()
    value = editable_mesh(p["name"])
    mode = p.get("origin", "bounds_bottom_center")
    if mode not in ORIGINS:
        raise ValueError(f"origin must be one of {sorted(ORIGINS)}")
    point = p.get("location")
    if (mode == "point") != (point is not None):
        raise ValueError("location is required for origin=point and refused otherwise")
    low, high = local_bounds(value)
    if mode == "bounds_center":
        pivot = Vector((low + high) / 2)
    elif mode == "bounds_bottom_center":
        pivot = Vector(((low[0] + high[0]) / 2, (low[1] + high[1]) / 2, low[2]))
    else:
        target = Vector(vector(point)) if mode == "point" else Vector()
        inverse = value.matrix_world.inverted_safe()
        pivot = inverse @ target
    value.data.transform(Matrix.Translation(-pivot), shape_keys=True)
    value.data.update()
    value.matrix_basis = value.matrix_basis @ Matrix.Translation(pivot)
    reparent_children(value, Matrix.Translation(-pivot))
    return {**info(value), "origin": mode, "moved_local": list(pivot)}


def snap_to_grid(p):
    object_mode()
    value = obj(p["name"])
    grid = number(p.get("grid"), 0.001, 100, "grid")
    before = list(value.location)
    value.location = [round(c / grid) * grid for c in value.location]
    return {**info(value), "grid": grid, "location_before": before}


def rename(p):
    object_mode()
    value = obj(p["name"])
    label = new_name(p.get("new_name"))
    value.name = label
    data = value.data
    renamed = bool(data is not None and data.users == 1 and value.type == "MESH"
                   and label not in bpy.data.meshes)
    if renamed:
        data.name = label
    return {**info(value), "mesh_renamed": renamed,
            "mesh": data.name if value.type == "MESH" else None}


def add_socket(p):
    object_mode()
    parent = obj(p["name"])
    suffix = p.get("new_name")
    if not isinstance(suffix, str) or not suffix.strip():
        raise ValueError("new_name must name the socket")
    label = new_name(suffix if suffix.startswith("SOCKET_") else "SOCKET_" + suffix)
    offset = vector(p.get("location") or [0, 0, 0])
    degrees = vector(p.get("rotation_degrees") or [0, 0, 0])
    socket = bpy.data.objects.new(label, None)
    socket.empty_display_type = "ARROWS"
    size = max(parent.dimensions) if parent.type == "MESH" else 1
    socket.empty_display_size = max(0.01, min(10, size * 0.1))
    (parent.users_collection or [bpy.context.scene.collection])[0].objects.link(socket)
    socket.parent = parent
    socket.matrix_parent_inverse = Matrix.Identity(4)
    socket.location = offset
    socket.rotation_euler = Euler([math.radians(v) for v in degrees], "XYZ")
    return {**info(socket), "parent": parent.name}


HANDLERS = {"apply_transforms": apply_transforms, "set_origin": set_origin,
            "snap_to_grid": snap_to_grid, "rename_object": rename, "add_socket": add_socket}
