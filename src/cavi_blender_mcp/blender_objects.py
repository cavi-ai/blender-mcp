"""Object-level pipeline edits: transforms, origins, names and sockets."""

import math

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

from .blender_bridge import editable_mesh, info, new_name, number, obj, vector
from .blender_errors import preflight

COMPONENTS = ("location", "rotation", "scale")
ORIGINS = {"bounds_bottom_center", "bounds_center", "world_origin", "point"}


def object_mode():
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before this operation")


def make_single_user(p):
    with preflight():
        object_mode()
        value = obj(p['name'], mesh=True)
        if not value.is_editable:
            raise ValueError('Mesh ownership requires an editable scene object')
        source = value.data
        previous_users = source.users
        needed = source.users > 1 or source.library is not None
    clone, key = None, None
    try:
        if needed:
            clone = source.copy()
            key = clone.shape_keys if clone.shape_keys != source.shape_keys else None
            clone.use_fake_user = False
            value.data = clone
            value.update_tag()
            bpy.context.view_layer.update()
            if clone.library is not None or clone.users != 1:
                raise RuntimeError('Native copy did not produce single-user local mesh data')
        return {**info(value), 'mesh_copy':{'copied':needed, 'source':source.name,
            'mesh':value.data.name, 'previous_users':previous_users,
            'source_users':source.users, 'users':value.data.users,
            'shape_keys':value.data.shape_keys.name if value.data.shape_keys else None}}
    except Exception:
        if clone is not None:
            value.data = source
            bpy.data.batch_remove(ids=tuple(v for v in (clone, key) if v is not None))
            value.update_tag()
            bpy.context.view_layer.update()
        raise


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
    bpy.context.view_layer.update()
    # Snap the world position with halves rounded up; rotation and scale stay untouched.
    world = value.matrix_world.translation
    delta = Vector([math.floor(c / grid + 0.5) * grid for c in world]) - world
    parent = (value.matrix_world @ value.matrix_basis.inverted_safe()).to_3x3()
    value.location += parent.inverted_safe() @ delta
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


def duplicate(p):
    object_mode()
    value = obj(p["name"])
    base = new_name(p.get("new_name"))
    count = p.get("count", 1)
    if type(count) is not int or not 1 <= count <= 256:
        raise ValueError("count must be an integer from 1 to 256")
    offset = vector(p.get("offset") or [0, 0, 0])
    linked = p.get("linked", False)
    if type(linked) is not bool:
        raise ValueError("linked must be boolean")
    names = [base] if count == 1 else [f"{base}_{index:02d}" for index in range(1, count + 1)]
    for label in names:
        if label in bpy.data.objects:
            raise ValueError(f"{label} already exists")
    owner = (value.users_collection or [bpy.context.scene.collection])[0]
    created = []
    try:
        for index, label in enumerate(names, start=1):
            copy = value.copy()
            if not linked and value.data is not None:
                copy.data = value.data.copy()
            owner.objects.link(copy)
            copy.name = label
            copy.matrix_world = Matrix.Translation(Vector(offset) * index) @ value.matrix_world
            created.append(copy)
    except Exception:
        for item in created:
            mesh = item.data
            bpy.data.objects.remove(item, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        raise
    return {"source": value.name, "count": count, "linked": linked,
            "offset": list(offset), "objects": [item.name for item in created]}


def parent(p):
    object_mode()
    child = obj(p["name"])
    target = obj(p.get("new_name"))
    if child == target:
        raise ValueError("An object cannot be its own parent")
    walk = target
    while walk is not None:
        if walk == child:
            raise ValueError("Parenting would create a cycle")
        walk = walk.parent
    world = child.matrix_world.copy()
    child.parent = target
    child.matrix_parent_inverse = target.matrix_world.inverted_safe()
    child.matrix_world = world
    return {**info(child), "parent": target.name}


def unparent(p):
    object_mode()
    child = obj(p["name"])
    world = child.matrix_world.copy()
    previous = child.parent.name if child.parent else None
    child.parent = None
    child.matrix_world = world
    return {**info(child), "previous_parent": previous}


def move_to_collection(p):
    object_mode()
    value = obj(p["name"])
    label = p.get("new_name")
    if not isinstance(label, str) or not label.strip() or len(label.encode()) > 63:
        raise ValueError("new_name must name a collection of at most 63 UTF-8 bytes")
    create = p.get("create", True)
    if type(create) is not bool:
        raise ValueError("create must be boolean")
    collection = bpy.data.collections.get(label)
    if collection is None:
        if not create:
            raise ValueError("Collection does not exist")
        collection = bpy.data.collections.new(label)
        bpy.context.scene.collection.children.link(collection)
    elif collection not in bpy.context.scene.collection.children_recursive:
        bpy.context.scene.collection.children.link(collection)
    for owner in list(value.users_collection):
        owner.objects.unlink(value)
    collection.objects.link(value)
    return {**info(value), "collection": collection.name}


def visibility(p):
    object_mode()
    value = obj(p["name"])
    changes = {key: p[key] for key in ("hide_viewport", "hide_render") if p.get(key) is not None}
    if not changes or any(type(flag) is not bool for flag in changes.values()):
        raise ValueError("visibility needs boolean hide_viewport or hide_render")
    layer = bpy.context.view_layer
    before = {"hide_viewport": value.hide_viewport or value.hide_get(view_layer=layer),
              "hide_render": value.hide_render}
    if "hide_render" in changes:
        value.hide_render = changes["hide_render"]
    if "hide_viewport" in changes:
        # The viewport flag and the view-layer eye both hide it; set them together.
        value.hide_viewport = changes["hide_viewport"]
        if value.name in layer.objects:
            value.hide_set(changes["hide_viewport"], view_layer=layer)
    return {**info(value), "visibility_before": before,
            "hide_viewport": value.hide_viewport or value.hide_get(view_layer=layer),
            "hide_render": value.hide_render}


KEY_CHANNELS = {"location": "location", "rotation_degrees": "rotation_euler", "scale": "scale"}
INTERPOLATIONS = {"BEZIER", "LINEAR", "CONSTANT"}


def keyframes(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 32:
        raise ValueError("keyframes must list 1 to 32 frames")
    parsed, last = [], 0
    for item in value:
        if not isinstance(item, dict) or set(item) - {*KEY_CHANNELS, "frame", "interpolation"}:
            raise ValueError("keyframes contain an unsupported entry")
        frame, interpolation = item.get("frame"), item.get("interpolation", "BEZIER")
        if type(frame) is not int or not last < frame <= 1000000:
            raise ValueError("keyframe frames must be strictly increasing integers from 1")
        if interpolation not in INTERPOLATIONS:
            raise ValueError(f"interpolation must be one of {sorted(INTERPOLATIONS)}")
        channels = {key: vector(item[key]) for key in KEY_CHANNELS if item.get(key) is not None}
        if not channels or ("scale" in channels and 0 in channels["scale"]):
            raise ValueError("Each keyframe needs location, rotation_degrees or a nonzero scale")
        parsed.append((frame, interpolation, channels))
        last = frame
    return parsed


def object_keyframe(p):
    with preflight():
        object_mode()
        value = obj(p["name"])
        label = p.get("action_name")
        if not isinstance(label, str) or not label.strip() or len(label.encode()) > 63:
            raise ValueError("action_name must be nonempty and at most 63 UTF-8 bytes")
        if label in bpy.data.actions:
            raise ValueError("Action name already exists")
        sequence = keyframes(p.get("keyframes"))
        if (value.rotation_mode in {"QUATERNION", "AXIS_ANGLE"}
                and any("rotation_degrees" in channels for _, _, channels in sequence)):
            raise ValueError("rotation_degrees keys need an Euler rotation mode")
    animation = value.animation_data or value.animation_data_create()
    previous = (animation.action, animation.action_slot, value.matrix_basis.copy())
    frame = bpy.context.scene.frame_current
    action = None
    try:
        action = bpy.data.actions.new(label)
        animation.action = action
        for number_, _, channels in sequence:
            for key, path in KEY_CHANNELS.items():
                if key in channels:
                    data = channels[key]
                    setattr(value, path, [math.radians(c) for c in data] if key == "rotation_degrees" else data)
                    if not value.keyframe_insert(path, frame=number_):
                        raise RuntimeError(f"Could not key {key} at frame {number_}")
        modes = {number_: interpolation for number_, interpolation, _ in sequence}
        for layer in action.layers:
            for strip in layer.strips:
                for bag in getattr(strip, "channelbags", ()):
                    for curve in bag.fcurves:
                        for point in curve.keyframe_points:
                            point.interpolation = modes[round(point.co.x)]
        action.use_frame_range = True
        action.frame_start, action.frame_end = sequence[0][0], sequence[-1][0]
    except Exception:
        if action is not None:
            animation.action = previous[0]
            if previous[0] is not None and previous[1] is not None:
                try:
                    animation.action_slot = previous[1]
                except (TypeError, RuntimeError):
                    pass
            bpy.data.actions.remove(action)
        value.matrix_basis = previous[2]
        raise
    finally:
        bpy.context.scene.frame_set(frame)
    slot = animation.action_slot
    return {**info(value), "action": action.name, "action_slot": slot.identifier if slot else None,
            "frame_range": [sequence[0][0], sequence[-1][0]],
            "frames": [number_ for number_, _, _ in sequence],
            "channels": [key for key in KEY_CHANNELS
                         if any(key in channels for _, _, channels in sequence)]}


HANDLERS = {"make_mesh_single_user": make_single_user,
            "apply_transforms": apply_transforms, "set_origin": set_origin,
            "snap_to_grid": snap_to_grid, "rename_object": rename, "add_socket": add_socket,
            "duplicate_object": duplicate, "parent_object": parent,
            "unparent_object": unparent, "move_to_collection": move_to_collection,
            "object_keyframe": object_keyframe, "set_visibility": visibility}
