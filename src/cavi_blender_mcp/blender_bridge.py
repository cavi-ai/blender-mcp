"""Blender-side bridge; all bpy operations execute on Blender's main thread."""

import hashlib
import hmac
import json
import math
import os
import queue
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import bpy
from mathutils import Euler, Quaternion, Vector

from .geometry import validate_mesh
from .importing import (
    MAX_BYTES,
    MAX_FBX_BYTES,
    MAX_GEOMETRY,
    inspect_fbx,
    inspect_glb,
    inspect_obj,
    inspect_usd,
)
from .lease import Lease
from .operations import (
    DEFAULT_TIMEOUT,
    LEASE_FREE,
    MAX_REQUEST_BYTES,
    MAX_TIMEOUT,
)
from .paths import destination, environment_path
from .presets import AXIS_PRESETS

_server = None
_jobs = queue.Queue(maxsize=8)
_token = None
_connection = None
_workspace = None
_lease = Lease()
_project_epoch = secrets.token_hex(16)
GEOMETRY = frozenset({"decimate_to", "remesh_quad", "lod_chain", "lightmap_uv", "texel_density",
                      "collision", "cleanup_mesh"})
COMPOSE = frozenset({"boolean_mesh", "join_meshes", "separate_mesh", "mirror_mesh",
                     "array_mesh", "solidify_mesh"})
RIG = frozenset({"create_armature", "bind_skin", "repair_weights"})
ANIMATION = frozenset({"pose_rig", "keyframe_rig", "clear_pose"})
OBJECTS = frozenset({"apply_transforms", "set_origin", "snap_to_grid", "rename_object",
                     "add_socket", "duplicate_object", "parent_object", "unparent_object",
                     "move_to_collection"})
MAX_MODIFIERS = 16
MAX_EVALUATED_FACES = 500000
COLOR_TAG = "cavi_color_owner"
RENDERLESS = frozenset({"CAMERA", "LIGHT", "LIGHT_PROBE", "LIGHTPROBE", "SPEAKER"})


@bpy.app.handlers.persistent
def project_loaded(_):
    global _project_epoch
    _project_epoch = secrets.token_hex(16)


def project_identity():
    value = (os.getpid(), _project_epoch, bpy.data.filepath, bpy.context.scene.as_pointer())
    return hashlib.sha256(repr(value).encode()).hexdigest()


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
        raise ValueError("Mesh data is shared; make it single-user in Blender before editing")
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


def info(value):
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
        "modifiers": [{"name": m.name, "type": m.type} for m in value.modifiers],
    }
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
    target = destination(_workspace, path, extensions)
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


def check_import_name(name):
    if not isinstance(name, str) or not name.strip() or len(name.encode("utf-8")) > 58:
        raise ValueError("Import name must be nonempty and at most 58 UTF-8 bytes")
    if name in bpy.data.collections or any(
        item.name == name or item.name.startswith(name + ".") for item in bpy.data.objects
    ):
        raise ValueError("Import name already exists; choose a new asset name")
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before importing")


def validate_imported(objects, previous, animations_allowed=True, shape_keys_allowed=True):
    if not objects or any(
        item.type not in {"MESH", "EMPTY", "ARMATURE"} for item in objects
    ):
        raise RuntimeError("Import produced an unsupported object type")
    if set(bpy.data.scenes) != previous["scenes"]:
        raise RuntimeError("Import unexpectedly changed the scene set")
    armatures = [item for item in objects if item.type == "ARMATURE"]
    if len(armatures) > 16:
        raise RuntimeError("Imported armatures exceed the import budget")
    bones = sum(len(item.data.bones) for item in armatures)
    if any(not item.data.bones for item in armatures):
        raise RuntimeError("Imported armatures need at least one bone")
    if bones > 1024 or any(len(item.data.bones) > 512 for item in armatures):
        raise RuntimeError("Imported bones exceed the import budget")
    meshes = [item for item in objects if item.type == "MESH"]
    if not shape_keys_allowed and any(item.data.shape_keys is not None for item in meshes):
        raise RuntimeError("Shape keys need a separate import workflow")
    skinned = []
    for item in meshes:
        modifiers = [modifier for modifier in item.modifiers
                     if modifier.type == "ARMATURE" and modifier.object is not None]
        if not modifiers:
            continue
        if len(modifiers) != 1 or modifiers[0].object not in armatures:
            raise RuntimeError("Imported skins need one armature modifier on an imported rig")
        if not item.vertex_groups or len(item.vertex_groups) > 512:
            raise RuntimeError("Imported skins exceed the vertex-group budget")
        skinned.append(item)
    if len(skinned) > 64:
        raise RuntimeError("Imported skinned meshes exceed the import budget")
    vertices = sum(len(item.data.vertices) for item in meshes)
    triangles = sum(len(poly.vertices) - 2 for item in meshes for poly in item.data.polygons)
    if (len(objects) > 1000 or not 0 < vertices <= MAX_GEOMETRY
            or not 0 < triangles <= MAX_GEOMETRY):
        raise RuntimeError("Imported geometry exceeds the import budget")
    if len(set(bpy.data.materials) - previous["materials"]) > 64:
        raise RuntimeError("Imported materials exceed the import budget")
    if len(set(bpy.data.images) - previous["images"]) > 64:
        raise RuntimeError("Imported images exceed the import budget")
    actions = sorted(set(bpy.data.actions) - previous["actions"], key=lambda item: item.name)
    if not animations_allowed and actions:
        raise RuntimeError("Animation clips need the animated import workflow")
    if len(actions) > 32:
        raise RuntimeError("Imported actions exceed the import budget")
    for action in actions:
        start, end = action.frame_range
        if not math.isfinite(start) or not math.isfinite(end) or end < start:
            raise RuntimeError("Imported action has an invalid frame range")
    return armatures, meshes, skinned, actions, bones, vertices, triangles


def workspace_images(previous, objects, require_workspace=False):
    root = Path(_workspace).resolve()
    images = set(bpy.data.images) - previous["images"]
    materials = set(bpy.data.materials) - previous["materials"]
    for value in objects:
        for slot in value.material_slots:
            if slot.material is not None:
                materials.add(slot.material)
    for material in materials:
        if material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image is not None:
                    images.add(node.image)
    for image in images:
        if image.packed_file is not None and not require_workspace:
            continue
        if not image.filepath:
            raise RuntimeError("Imported images need packed data or a workspace path")
        candidates = [Path(image.filepath)]
        if not Path(image.filepath).is_absolute():
            candidates += [Path(bpy.path.abspath(image.filepath)), root / image.filepath]
        valid = [candidate for candidate in candidates
                 if candidate.resolve().is_relative_to(root) and candidate.is_file()]
        if not valid:
            raise RuntimeError("Imported images must stay inside the workspace")
        if valid[0].stat().st_size > 16 * 1024 * 1024:
            raise RuntimeError("Imported textures must be at most 16 MiB")
    return images


def install_collection(name, objects, scene):
    collection = bpy.data.collections.new(name)
    scene.collection.children.link(collection)
    for index, item in enumerate(objects):
        item.name = name if index == 0 else f"{name}.{index:03}"
        for owner in list(item.users_collection):
            owner.objects.unlink(item)
        collection.objects.link(item)
    return collection


def _import_asset(loader, inspector, path, name, suffix, maximum, *,
                  animations_allowed, shape_keys_allowed, require_workspace=False,
                  temp_root=None, cleanup=None):
    check_import_name(name)
    report = inspector(_workspace, path)
    with Path(report["path"]).open("rb") as stream:
        payload = stream.read(maximum + 1)
    if hashlib.sha256(payload).hexdigest() != report["sha256"]:
        raise RuntimeError(f"{suffix.upper()} changed during preflight; inspect the source before retrying")
    pools = ["objects", "collections", "meshes", "materials", "images", "node_groups",
             "curves", "cameras", "lights", "armatures", "actions", "scenes"]
    previous = {key: set(getattr(bpy.data, key)) for key in pools}
    selection = list(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    scene = bpy.context.scene
    root = Path(temp_root or Path(report["path"]).parent).resolve()
    fd, temporary = tempfile.mkstemp(prefix=".cavi-import-", suffix=suffix, dir=root)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        loader(temporary)
        objects = sorted(set(bpy.data.objects) - previous["objects"],
                         key=lambda item: (item.type != "ARMATURE", item.name))
        armatures, meshes, skinned, actions, bones, vertices, triangles = validate_imported(
            objects, previous, animations_allowed=animations_allowed,
            shape_keys_allowed=shape_keys_allowed)
        images = workspace_images(previous, objects, require_workspace=require_workspace)
        collection = install_collection(name, objects, scene)
        for image in images:
            if not image.packed_file:
                image.pack()
        if cleanup is not None:
            cleanup(previous, collection)
        result = {
            **report,
            "collection": collection.name,
            "objects": [info(item) for item in objects],
            "armatures": [item.name for item in armatures],
            "skinned_meshes": [item.name for item in skinned],
            "bone_count": bones,
            "animations": [{"name": action.name, "frame_range": list(action.frame_range)}
                           for action in actions],
            "imported_vertices": vertices,
            "imported_triangles": triangles,
        }
        if shape_keys_allowed:
            shape_key_meshes = []
            morph_targets = 0
            for item in meshes:
                if item.data.shape_keys is None:
                    continue
                blocks = item.data.shape_keys.key_blocks
                count = len(blocks) - 1
                if count <= 0:
                    continue
                if count > 64:
                    raise RuntimeError("Imported shape keys exceed the import budget")
                names = [block.name for block in blocks[1:]]
                if len(set(names)) != len(names) or any(
                        len(block.encode()) > 63 for block in names):
                    raise RuntimeError("Imported shape keys have invalid names")
                morph_targets += count
                if morph_targets > 256:
                    raise RuntimeError("Imported morph targets exceed the import budget")
                shape_key_meshes.append({"name": item.name, "shape_keys": count,
                                         "names": names})
            result["shape_key_meshes"] = shape_key_meshes
            result["morph_targets"] = morph_targets
            shape_key_animations = []
            for item in meshes:
                keys = item.data.shape_keys
                if keys is None or keys.animation_data is None:
                    continue
                animation = keys.animation_data
                linked = []
                if animation.action is not None:
                    linked.append((animation.action, "active", animation.action_slot))
                for track in animation.nla_tracks:
                    for strip in track.strips:
                        if strip.action is not None:
                            linked.append((strip.action, "nla:" + track.name,
                                           strip.action_slot))
                for action, binding, slot in linked:
                    start, end = action.frame_range
                    if not math.isfinite(start) or not math.isfinite(end) or end < start:
                        raise RuntimeError("Imported shape-key action has an invalid frame range")
                    shape_key_animations.append({
                        "name": action.name, "mesh": item.name, "binding": binding,
                        "frame_range": list(action.frame_range),
                        "slot": slot.identifier if slot else None})
                    if len(shape_key_animations) > 32:
                        raise RuntimeError("Imported shape-key actions exceed the import budget")
            result["shape_key_animations"] = shape_key_animations
        return result
    except Exception:
        for key in pools:
            pool = getattr(bpy.data, key)
            for item in set(pool) - previous[key]:
                pool.remove(item, do_unlink=True)
        raise
    finally:
        if bpy.context.window and bpy.context.window.scene != scene:
            bpy.context.window.scene = scene
        for item in bpy.context.selected_objects:
            item.select_set(False)
        for item in selection:
            item.select_set(True)
        bpy.context.view_layer.objects.active = active
        Path(temporary).unlink(missing_ok=True)


def _load_glb(path):
    if "FINISHED" not in bpy.ops.import_scene.gltf(filepath=path):
        raise RuntimeError("Blender did not finish importing the GLB")


def import_glb(path, name):
    return _import_asset(
        _load_glb, inspect_glb, path, name, ".glb", MAX_BYTES,
        animations_allowed=True, shape_keys_allowed=True, temp_root=_workspace)


def _load_fbx(path):
    if "FINISHED" not in bpy.ops.import_scene.fbx(
        filepath=str(path), use_image_search=False, use_anim=True,
        ignore_leaf_bones=False, automatic_bone_orientation=False,
        use_manual_orientation=False, use_prepost_rot=True):
        raise RuntimeError("Blender did not finish importing the FBX")


def import_fbx(path, name):
    return _import_asset(
        _load_fbx, inspect_fbx, path, name, ".fbx", MAX_FBX_BYTES,
        animations_allowed=True, shape_keys_allowed=False)


def _load_obj(path):
    if "FINISHED" not in bpy.ops.wm.obj_import(
        filepath=str(path), forward_axis="NEGATIVE_Z", up_axis="Y",
        use_split_objects=True, use_split_groups=False,
        import_vertex_groups=False, validate_meshes=True, global_scale=1.0):
        raise RuntimeError("Blender did not finish importing the OBJ")


def import_obj(path, name):
    return _import_asset(
        _load_obj, inspect_obj, path, name, ".obj", MAX_BYTES,
        animations_allowed=False, shape_keys_allowed=False)


def _load_usd(path):
    if "FINISHED" not in bpy.ops.wm.usd_import(
        filepath=str(path), scale=1.0, set_frame_range=False,
        import_cameras=False, import_curves=False, import_lights=False,
        import_materials=True, import_meshes=True, import_volumes=False,
        import_shapes=False, import_skeletons=True, import_blendshapes=False,
        import_points=False, import_subdivision=False,
        support_scene_instancing=False, import_visible_only=False,
        create_collection=False, read_mesh_uvs=True, read_mesh_colors=True,
        read_mesh_attributes=True, import_textures_mode="IMPORT_PACK",
        validate_meshes=True):
        raise RuntimeError("Blender did not finish importing the USD")


def _usd_cleanup(previous, collection):
    for item in set(bpy.data.collections) - previous["collections"]:
        if item is not collection and not item.objects and not item.children:
            bpy.data.collections.remove(item)


def import_usd(path, name):
    return _import_asset(
        _load_usd, inspect_usd, path, name, Path(path).suffix.lower(), MAX_BYTES,
        animations_allowed=False, shape_keys_allowed=False,
        require_workspace=True, cleanup=_usd_cleanup)


def dispatch(operation, p):
    if operation == "owned_edit":
        inner, params = p.get("operation"), p.get("params")
        if not isinstance(inner, str) or not isinstance(params, dict):
            raise ValueError("Owned edit envelope needs an operation and object params")
        if inner in LEASE_FREE | {"owned_edit", "session_control", "runtime_restart"}:
            raise ValueError("Owned edit envelope requires a scene mutation")
        operation, p = inner, params
    if operation == "session_control":
        return _lease.control(p, project_identity)
    if operation in LEASE_FREE:
        params = dict(p)
        params.pop("lease_id", None)
        return _dispatch(operation, params)
    params = dict(p)
    with _lease.edit(params.pop("lease_id", None), project_identity):
        return _dispatch(operation, params)


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


def scene_info(p):
    limit, offset = p.get("limit", 200), p.get("offset", 0)
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer from 1 to 1000")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a nonnegative integer")
    objects = bpy.context.scene.objects

    def collection_tree(parent, root=True):
        for child in parent.children:
            yield child, None if root else parent.name
            yield from collection_tree(child, False)

    collections = sorted(collection_tree(bpy.context.scene.collection),
                         key=lambda item: item[0].name)
    return {
        "version": bpy.app.version_string,
        "file": bpy.data.filepath,
        "workspace": str(_workspace),
        "total": len(objects),
        "offset": offset,
        "limit": limit,
        "objects": [info(objects[i]) for i in range(offset, min(offset + limit, len(objects)))],
        "collections": [
            {"name": item.name, "parent": parent,
             "objects": len(item.objects), "total_objects": len(item.all_objects)}
            for item, parent in collections
        ],
    }


def create_primitive(p):
    name = new_name(p["name"])
    constructors = {
        "cube": bpy.ops.mesh.primitive_cube_add,
        "sphere": bpy.ops.mesh.primitive_uv_sphere_add,
        "cylinder": bpy.ops.mesh.primitive_cylinder_add,
        "cone": bpy.ops.mesh.primitive_cone_add,
        "plane": bpy.ops.mesh.primitive_plane_add,
    }
    if p.get("kind") not in constructors:
        raise ValueError("Unknown primitive")
    location = vector(p.get("location") or [0, 0, 0])
    constructors[p["kind"]](location=location)
    value = bpy.context.object
    value.name = name
    value.data.name = name
    root = bpy.context.scene.collection
    if root not in value.users_collection:
        root.objects.link(value)
    for owner in list(value.users_collection):
        if owner != root:
            owner.objects.unlink(value)
    return info(value)


def create_mesh(p):
    name = new_name(p["name"])
    vertices, faces = validate_mesh(p["vertices"], p["faces"])
    mesh = bpy.data.meshes.new(name)
    try:
        mesh.from_pydata(vertices, [], faces)
        if mesh.validate():
            raise ValueError("Blender rejected the supplied topology")
        mesh.update()
        value = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(value)
    except Exception:
        bpy.data.meshes.remove(mesh)
        raise
    return info(value)


def transform(p):
    value = obj(p["name"])
    updates = {
        k: vector(p[k])
        for k in ("location", "rotation_degrees", "scale")
        if p.get(k) is not None
    }
    if "scale" in updates and any(v <= 0 for v in updates["scale"]):
        raise ValueError("Scale components must be positive")
    if "location" in updates:
        value.location = updates["location"]
    if "rotation_degrees" in updates:
        set_rotation(value, updates["rotation_degrees"])
    if "scale" in updates:
        value.scale = updates["scale"]
    return info(value)


def set_color(p):
    value = editable_mesh(p["name"])
    color = vector(p["rgba"], 4)
    if any(v < 0 or v > 1 for v in color):
        raise ValueError("Color components must range from 0 to 1")
    slot = p.get("slot", 0)
    if type(slot) is not int or not 0 <= slot <= 31:
        raise ValueError("Material slot must be 0 to 31")
    slots = value.material_slots
    if slot >= len(slots) and not (slot == 0 and not slots):
        raise ValueError("Requested material slot does not exist")
    key = f"{value.name}:{slot}"
    label = f"{value.name} Color" if slot == 0 else f"{value.name} Color {slot}"
    current = slots[slot].material if slots else None
    stored = bpy.data.materials.get(label)
    if current is not None and current.get(COLOR_TAG) == key and current.users <= 1:
        material = current
    elif stored is not None and stored.get(COLOR_TAG) == key and stored.users == 0:
        material = stored
    else:
        material = bpy.data.materials.new(label)
        material[COLOR_TAG] = key
    material.diffuse_color = color
    if not slots:
        value.data.materials.append(material)
    elif current != material:
        slots[slot].material = material
    return info(value)


def add_modifier(p):
    bake = p.get("apply", False)
    if type(bake) is not bool:
        raise ValueError("apply must be boolean")
    value = editable_mesh(p["name"]) if bake else obj(p["name"], mesh=True)
    if bake and (value.modifiers or bpy.context.mode != "OBJECT"):
        raise ValueError("Baking requires Object Mode and no existing modifiers")
    if len(value.modifiers) >= MAX_MODIFIERS:
        raise ValueError(f"Modifier stack is limited to {MAX_MODIFIERS}; apply or remove some")
    amount = vector([p["amount"]], 1)[0]
    if p["kind"] == "bevel" and 0 < amount <= 100:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = value.evaluated_get(depsgraph).data
        segments = 3
        estimate = (len(evaluated.polygons) + len(evaluated.edges) * segments
                    + len(evaluated.vertices) * segments * segments)
        if estimate > MAX_EVALUATED_FACES:
            raise ValueError(f"Bevel would exceed {MAX_EVALUATED_FACES} estimated faces")
        modifier = value.modifiers.new("Bevel", "BEVEL")
        modifier.width, modifier.segments = amount, segments
    elif p["kind"] == "decimate" and 0 < amount <= 1:
        modifier = value.modifiers.new("Decimate", "DECIMATE")
        modifier.ratio = amount
    elif p["kind"] in {"subdivision", "voxel_remesh"}:
        # Refuse stacked surface operations: their combined cost is not bounded by base counts.
        if value.modifiers:
            raise ValueError("Organic modifiers require a mesh without existing modifiers")
        if p["kind"] == "subdivision":
            facets = sum(max(4, len(face.vertices)) for face in value.data.polygons)
            if amount not in (1, 2, 3) or facets * 4 ** (amount - 1) > MAX_EVALUATED_FACES:
                raise ValueError(
                    "Subdivision needs integer levels 1–3 and at most 500000 faces"
                )
            modifier = value.modifiers.new("Subdivision", "SUBSURF")
            modifier.levels = modifier.render_levels = int(amount)
        else:
            bpy.context.view_layer.update()
            local = [Vector(c) for c in value.bound_box]
            extents = [max(v[i] for v in local) - min(v[i] for v in local) for i in range(3)]
            if (
                not 0.005 <= amount <= 1
                or math.prod(max(v, amount) / amount + 2 for v in extents) > 2000000
            ):
                raise ValueError("Voxel size must be [0.005,1] and fit 2000000 bounding voxels")
            modifier = value.modifiers.new("Voxel Remesh", "REMESH")
            modifier.mode = "VOXEL"
            modifier.voxel_size = amount
            modifier.use_smooth_shade = True
    else:
        raise ValueError("Invalid modifier or amount")
    if bake:
        with selected([value]):
            if "FINISHED" not in bpy.ops.object.modifier_apply(modifier=modifier.name):
                raise RuntimeError("Modifier baking did not finish")
    return info(value)


def unwrap(p):
    value = editable_mesh(p["name"])
    angle = number(p.get("angle_limit_degrees", 66), 1, 89, "angle_limit_degrees")
    margin = number(p.get("island_margin", 0.02), 0, 0.5, "island_margin")
    name = p.get("uv_layer")
    if name is not None and (
        not isinstance(name, str) or not name.strip() or len(name.encode()) > 63
    ):
        raise ValueError("UV layer name must be nonempty and at most 63 UTF-8 bytes")
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before this operation")
    layers = value.data.uv_layers
    created = None
    previous = layers.active
    if name is not None and layers.get(name) is None:
        if len(layers) >= 8:
            raise ValueError("Mesh already has the maximum of 8 UV layers")
        created = layers.new(name=name)
    try:
        if name is not None:
            layers.active = layers[name]
        with selected([value]):
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            if "FINISHED" not in bpy.ops.uv.smart_project(
                angle_limit=math.radians(angle), island_margin=margin
            ):
                raise RuntimeError("Smart UV Project did not finish")
            bpy.ops.uv.select_all(action="SELECT")
            if "FINISHED" not in bpy.ops.uv.pack_islands(margin=margin):
                raise RuntimeError("UV island packing did not finish")
    except Exception:
        if created is not None:
            layers.remove(layers[name])
            if previous is not None:
                layers.active = previous
        raise
    return {**info(value), "uv_layer": layers.active.name}


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


def export_mesh(p):
    if not isinstance(p["names"], list) or not p["names"] or len(p["names"]) > 1000:
        raise ValueError("Provide between 1 and 1000 mesh names")
    objects = [obj(n, mesh=True) for n in p["names"]]
    preserve = p.get("preserve_instances", False)
    empties = p.get("include_empties", False)
    if type(preserve) is not bool or type(empties) is not bool:
        raise ValueError("preserve_instances and include_empties must be booleans")
    if preserve and Path(p["path"]).suffix.lower() != ".fbx":
        raise ValueError("preserve_instances applies to static FBX exports")
    selection = with_empties(objects) if empties else list(objects)
    with output_file(p["path"], {".fbx", ".glb"}) as path, selected(selection):
        if path.suffix.lower() == ".fbx":
            from .export_instances import instance_meshes

            with instance_meshes(objects) if preserve else nullcontext():
                result = bpy.ops.export_scene.fbx(
                    filepath=str(path),
                    use_selection=True,
                    object_types={"MESH", "EMPTY"} if empties else {"MESH"},
                    mesh_smooth_type="FACE",
                    use_tspace=True,
                    add_leaf_bones=False,
                    bake_anim=False,
                    global_scale=1,
                    path_mode="STRIP",
                    **AXIS_PRESETS["unity"],
                )
        else:
            result = bpy.ops.export_scene.gltf(
                filepath=str(path), export_format="GLB", use_selection=True,
                export_apply=True, export_morph=True, export_morph_animation=False)
        if "FINISHED" not in result:
            raise RuntimeError("Mesh export did not finish")
    return {"path": str(path), "objects": p["names"], "bytes": path.stat().st_size,
            "preserve_instances": preserve, "include_empties": empties}


def save_project(p):
    previous = bpy.context.preferences.filepaths.save_version
    try:
        bpy.context.preferences.filepaths.save_version = 0
        with output_file(p["path"], {".blend"}) as path:
            if "FINISHED" not in bpy.ops.wm.save_as_mainfile(
                filepath=str(path), check_existing=False
            ):
                raise RuntimeError("Project save did not finish")
    finally:
        bpy.context.preferences.filepaths.save_version = previous
    return {"path": str(path), "bytes": path.stat().st_size}


def runtime(operation, p):
    if p:
        raise ValueError("Runtime commands do not accept parameters")
    if _server is None:
        raise RuntimeError("Blender bridge is not running")
    if operation == "runtime_restart":
        replace_server()
    return {
        "connected": True,
        "pid": os.getpid(),
        "generation": _server.bridge_generation,
        "version": bpy.app.version_string,
        "file": bpy.data.filepath,
        "workspace": str(_workspace),
        "object_count": len(bpy.context.scene.objects),
        "dirty": bpy.data.is_dirty,
        "background": bpy.app.background,
    }


def shade(p):
    value = editable_mesh(p["name"])
    if type(p["smooth"]) is not bool:
        raise ValueError("smooth must be boolean")
    for polygon in value.data.polygons:
        polygon.use_smooth = p["smooth"]
    return info(value)


def _dispatch(operation, p):
    if operation == "inspect_rig":
        from .blender_rig import inspect

        return {**inspect(p, obj), "project_id": project_identity()}
    if operation == "export_instances":
        operation, p = "export_mesh", {**p, "preserve_instances": True}
    if operation == "inspect_mesh_quality":
        from .blender_quality import inspect

        return {**inspect(p, obj), "project_id": project_identity()}
    if operation == "assign_material":
        from .blender_materials import assign

        return assign(p, _workspace, obj)
    if operation == "import_mesh":
        return import_glb(p["path"], p["name"])
    if operation == "import_fbx":
        return import_fbx(p["path"], p["name"])
    if operation == "import_obj":
        return import_obj(p["path"], p["name"])
    if operation == "import_usd":
        return import_usd(p["path"], p["name"])
    if operation in {"shape_key_add", "shape_key_value", "shape_key_remove",
                     "shape_key_keyframe"}:
        from .blender_shape_keys import HANDLERS

        return HANDLERS[operation](p)
    if operation in {"set_action", "rename_action", "delete_action", "nla_push",
                     "nla_remove"}:
        from .blender_nla import HANDLERS

        return HANDLERS[operation](p)
    if operation == "bake_map":
        from .blender_bake import bake

        return bake(p)
    if operation == "retarget_rig":
        from .blender_retarget import retarget

        return retarget(p)
    if operation == "review_sheet":
        from .blender_review import review

        return review(p)
    if operation == "scatter":
        from .blender_scatter import scatter

        return scatter(p)
    if operation in {"create_terrain", "place_objects", "snap_to_surface"}:
        from .blender_level import HANDLERS

        if operation == "create_terrain":
            return HANDLERS[operation](p, _workspace)
        return HANDLERS[operation](p)
    if operation == "export_asset":
        from .blender_export import export_asset

        return export_asset(p)
    if operation in ANIMATION:
        from .blender_animation import HANDLERS

        return HANDLERS[operation](p)
    if operation in RIG:
        from .blender_rigging import HANDLERS

        return HANDLERS[operation](p)
    if operation in COMPOSE:
        from .blender_compose import HANDLERS

        return HANDLERS[operation](p)
    if operation in GEOMETRY:
        from .blender_geometry import HANDLERS

        return HANDLERS[operation](p)
    if operation in OBJECTS:
        from .blender_objects import HANDLERS

        return HANDLERS[operation](p)
    if operation in {"runtime_status", "runtime_restart"}:
        return runtime(operation, p)
    if operation == "object_info":
        return info(obj(p["name"]))
    handlers = {
        "scene_info": scene_info,
        "create_mesh": create_mesh,
        "create_primitive": create_primitive,
        "transform_object": transform,
        "set_color": set_color,
        "add_modifier": add_modifier,
        "shade_mesh": shade,
        "unwrap_mesh": unwrap,
        "export_mesh": export_mesh,
        "save_project": save_project,
        "render_preview": preview,
    }
    if operation not in handlers:
        raise ValueError(f"Unknown operation: {operation}")
    return handlers[operation](p)


def preview(p):
    resolution = p.get("resolution", 512)
    if type(resolution) is not int or not 64 <= resolution <= 2048:
        raise ValueError("Resolution must be between 64 and 2048")
    color_mode = p.get("color_mode", "material")
    if color_mode not in {"material", "vertex"}:
        raise ValueError("Color mode must be material or vertex")
    renderer = p.get("renderer", "workbench")
    if renderer not in {"workbench", "eevee"}:
        raise ValueError("Renderer must be workbench or eevee")
    if renderer == "eevee" and (resolution > 1024 or color_mode != "material"):
        raise ValueError("Eevee previews require material colors and at most 1024 pixels")
    orthographic = p.get("orthographic", False)
    if type(orthographic) is not bool:
        raise ValueError("orthographic must be boolean")
    scene = bpy.context.scene
    direction = Vector(vector(p.get("direction", [1.5, -2, 1.4])))
    if direction.length < 1e-6:
        raise ValueError("Camera direction must be nonzero")
    names = p.get("names")
    if names is not None:
        if not isinstance(names, list) or not 1 <= len(names) <= 1000:
            raise ValueError("Provide between 1 and 1000 mesh names")
        meshes = [obj(name, mesh=True) for name in names]
    else:
        meshes = [v for v in scene.objects if v.type == "MESH" and not v.hide_render]
    bpy.context.view_layer.update()
    points = [v.matrix_world @ Vector(c) for v in meshes for c in v.bound_box]
    if not points:
        raise ValueError("Scene has no visible meshes")
    center = Vector([(min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in range(3)])
    radius = max(max((v - center).length for v in points), 1e-4)
    distance = max(radius * 3.5, 2)
    camera_data = bpy.data.cameras.new("MCP Preview")
    camera_data.clip_start = max(1e-4, min(0.1, (distance - radius) * 0.5))
    camera_data.clip_end = distance + radius * 2
    if orthographic:
        camera_data.type = "ORTHO"
        camera_data.ortho_scale = radius * 2.2
    camera = bpy.data.objects.new("MCP Preview", camera_data)
    scene.collection.objects.link(camera)
    camera.location = center + direction.normalized() * distance
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    render = scene.render
    original = (
        scene.camera,
        render.engine,
        render.filepath,
        render.resolution_x,
        render.resolution_y,
        render.resolution_percentage,
        render.image_settings.file_format,
        scene.display.shading.light,
        scene.display.shading.color_type,
    )
    visibility = [(v, v.hide_render) for v in scene.objects
                  if v.type not in RENDERLESS and v != camera]
    try:
        if names is not None:
            for value, _ in visibility:
                value.hide_render = value not in meshes
        scene.camera = camera
        if renderer == "eevee":
            try:
                render.engine = "BLENDER_EEVEE"
            except TypeError:
                render.engine = "BLENDER_EEVEE_NEXT"
        else:
            render.engine = "BLENDER_WORKBENCH"
        render.resolution_x = render.resolution_y = resolution
        render.resolution_percentage = 100
        render.image_settings.file_format = "PNG"
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = color_mode.upper()
        if renderer == "eevee":
            from .preview_studio import studio

            lighting = studio(scene, center, radius, min(point.z for point in points))
        else:
            lighting = nullcontext()
        with lighting, output_file(p["path"], {".png"}) as path:
            render.filepath = str(path)
            if "FINISHED" not in bpy.ops.render.render(write_still=True):
                raise RuntimeError("Preview render did not finish")
        return {"path": str(path)}
    finally:
        for value, hidden in visibility:
            value.hide_render = hidden
        (
            scene.camera,
            render.engine,
            render.filepath,
            render.resolution_x,
            render.resolution_y,
            render.resolution_percentage,
            render.image_settings.file_format,
            scene.display.shading.light,
            scene.display.shading.color_type,
        ) = original
        bpy.data.objects.remove(camera, do_unlink=True)
        bpy.data.cameras.remove(camera_data)


def pump():
    try:
        job = _jobs.get_nowait()
    except queue.Empty:
        return 0.05
    with job["lock"]:
        if job["cancelled"] or time.monotonic() > job["deadline"]:
            job["expired"] = True
            job["done"].set()
            return 0.01
        job["started"] = True
    try:
        job["result"] = dispatch(job["operation"], job["params"])
    except Exception as exc:  # noqa: BLE001 -- serialize application failures at the RPC boundary
        job["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        job["done"].set()
    return 0.01


def serve_background():
    """Block Blender's main thread on the job queue; used when timers cannot run."""
    import signal

    def stop(*_):
        raise SystemExit(0)

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        while _server is not None:
            with _jobs.not_empty:
                _jobs.not_empty.wait_for(lambda: bool(_jobs.queue), timeout=0.5)
            pump()
    finally:
        signal.signal(signal.SIGTERM, previous)
        unregister()


def request_timeout(value):
    if value is None:
        return DEFAULT_TIMEOUT
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= MAX_TIMEOUT:
        raise ValueError(f"timeout must be a number in (0, {MAX_TIMEOUT}]")
    return float(value)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            self.handle_rpc()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    def handle_rpc(self):
        if self.path != "/rpc" or not hmac.compare_digest(
            self.headers.get("Authorization", ""), f"Bearer {self.server.bridge_token}"
        ):
            self.close_connection = True
            return self.reply(403, {"error": "Unauthorized bridge request"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > MAX_REQUEST_BYTES:
            self.close_connection = True
            return self.reply(413, {"error": f"Request exceeds {MAX_REQUEST_BYTES} bytes"})
        request_id = None
        try:
            if length <= 0:
                raise ValueError("Missing request body")
            self.connection.settimeout(30)
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict) or not isinstance(request.get("id"), str):
                raise TypeError("Request needs a string id")
            request_id = request["id"]
            operation, params = request.get("operation"), request.get("params", {})
            if not isinstance(operation, str) or not isinstance(params, dict):
                raise TypeError("Request needs an operation name and object params")
            timeout = request_timeout(request.get("timeout"))
        except (ValueError, TypeError) as exc:
            self.close_connection = True
            return self.reply(400, {"id": request_id, "error": f"Bad request: {exc}"})
        job = {
            "operation": operation,
            "params": params,
            "done": threading.Event(),
            "lock": threading.Lock(),
            "started": False,
            "cancelled": False,
            "deadline": time.monotonic() + timeout,
        }
        try:
            _jobs.put_nowait(job)
        except queue.Full:
            return self.reply(503, {"id": request_id,
                                    "error": "Bridge queue is full; request was not executed"})
        finished = job["done"].wait(timeout)
        with job["lock"]:
            if not finished and not job["started"]:
                job["cancelled"] = True
            not_started = job["cancelled"] or job.get("expired", False)
        if not_started:
            return self.reply(504, {"id": request_id, "error": (
                f"Request was not started within {timeout:g}s; it was not executed")})
        if not finished:
            result = {"error": "Timed out; inspect the scene before retrying. Outcome may be unknown."}
        elif "error" in job:
            result = {"error": job["error"]}
        else:
            result = {"result": job.get("result")}
        self.reply(200, {"id": request_id, **result})


def replace_server():
    """Publish a fresh listener before retiring the old one; never touch scene data."""
    global _server, _token
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.bridge_token = secrets.token_hex(32)
    server.bridge_generation = secrets.token_hex(16)
    temporary = None
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        fd, temporary = tempfile.mkstemp(dir=_connection.parent, prefix=".connection-")
        with os.fdopen(fd, "w") as stream:
            json.dump(
                {"host": "127.0.0.1", "port": server.server_port, "token": server.bridge_token,
                 "pid": os.getpid()},
                stream,
            )
        os.replace(temporary, _connection)
    except Exception:
        server.shutdown()
        server.server_close()
        raise
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
    previous = _server
    _server, _token = server, server.bridge_token
    if previous is not None:
        previous.shutdown()
        previous.server_close()


def register():
    global _connection, _workspace
    if _server is not None:
        return
    from .client import BridgeClient, BridgeOperationError, default_connection

    _connection = default_connection()
    _connection.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if _connection.exists():
        try:
            BridgeClient(_connection).call("scene_info", {"limit": 1}, timeout=5)
        except BridgeOperationError:
            owned = True
        except (ConnectionError, ValueError, OSError, RuntimeError):
            owned = False
        else:
            owned = True
        if owned:
            raise RuntimeError(
                "Another Blender bridge owns this connection; choose CAVI_BLENDER_CONNECTION explicitly"
            )
    _workspace = environment_path(
        "CAVI_BLENDER_WORKSPACE", Path.home() / "Documents/CaviBlender"
    )
    _workspace.mkdir(parents=True, exist_ok=True)
    _workspace = _workspace.resolve()
    replace_server()
    if project_loaded not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(project_loaded)
    bpy.app.timers.register(pump, persistent=True)


def unregister():
    global _server
    if _server is not None:
        _server.shutdown()
        _server.server_close()
        _server = None
    if bpy.app.timers.is_registered(pump):
        bpy.app.timers.unregister(pump)
    if project_loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(project_loaded)
    if _connection and _connection.exists():
        try:
            if json.loads(_connection.read_text()).get("token") == _token:
                _connection.unlink()
        except (ValueError, OSError):
            pass
