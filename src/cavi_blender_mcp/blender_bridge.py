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

from .client import DEFAULT_TIMEOUT, MAX_REQUEST_BYTES, MAX_TIMEOUT
from .geometry import validate_mesh
from .importing import MAX_BYTES, MAX_GEOMETRY, inspect_glb
from .lease import Lease
from .paths import destination
from .presets import AXIS_PRESETS

_server = None
_jobs = queue.Queue(maxsize=8)
_token = None
_connection = None
_workspace = None
_lease = Lease()
_project_epoch = secrets.token_hex(16)
LEASE_FREE = frozenset(
    {"scene_info", "object_info", "runtime_status", "inspect_mesh_quality", "render_preview",
     "review_sheet"}
)
GEOMETRY = frozenset({"decimate_to", "remesh_quad", "lod_chain", "lightmap_uv", "texel_density",
                      "collision", "cleanup_mesh"})
OBJECTS = frozenset({"apply_transforms", "set_origin", "snap_to_grid", "rename_object",
                     "add_socket"})
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
        "modifiers": [{"name": m.name, "type": m.type} for m in value.modifiers],
    }
    if value.type == "MESH":
        result.update(
            vertices=len(value.data.vertices),
            polygons=len(value.data.polygons),
            uv_layers=len(value.data.uv_layers),
            materials=[slot.material.name if slot.material else None
                       for slot in value.material_slots],
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
            value.select_set(True)
        bpy.context.view_layer.objects.active = active


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


def _load_glb(path):
    if "FINISHED" not in bpy.ops.import_scene.gltf(filepath=path):
        raise RuntimeError("Blender did not finish importing the GLB")


def import_glb(path, name):
    if not isinstance(name, str) or not name.strip() or len(name.encode("utf-8")) > 58:
        raise ValueError("Import name must be nonempty and at most 58 UTF-8 bytes")
    if name in bpy.data.collections or any(
        item.name == name or item.name.startswith(name + ".") for item in bpy.data.objects
    ):
        raise ValueError("Import name already exists; choose a new asset name")
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before importing")
    report = inspect_glb(_workspace, path)
    with Path(report["path"]).open("rb") as stream:
        payload = stream.read(MAX_BYTES + 1)
    if hashlib.sha256(payload).hexdigest() != report["sha256"]:
        raise RuntimeError("GLB changed during preflight; inspect the source before retrying")
    pools = ["objects", "collections", "meshes", "materials", "images", "node_groups",
             "curves", "cameras", "lights", "armatures", "actions", "scenes"]
    previous = {key: set(getattr(bpy.data, key)) for key in pools}
    selection = list(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    scene = bpy.context.scene
    fd, temporary = tempfile.mkstemp(prefix=".cavi-import-", suffix=".glb", dir=_workspace)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        _load_glb(temporary)
        objects = sorted(set(bpy.data.objects) - previous["objects"], key=lambda item: item.name)
        if not objects or any(
            item.type not in {"MESH", "EMPTY"} for item in objects
        ):
            raise RuntimeError("GLB did not produce only static meshes and transform nodes")
        if set(bpy.data.scenes) != previous["scenes"]:
            raise RuntimeError("GLB import unexpectedly changed the scene set")
        meshes = [item for item in objects if item.type == "MESH"]
        vertices = sum(len(item.data.vertices) for item in meshes)
        triangles = sum(len(poly.vertices) - 2 for item in meshes for poly in item.data.polygons)
        if (len(objects) > 1000 or not 0 < vertices <= MAX_GEOMETRY
                or not 0 < triangles <= MAX_GEOMETRY):
            raise RuntimeError("Imported geometry exceeds the import budget")
        collection = bpy.data.collections.new(name)
        scene.collection.children.link(collection)
        for index, item in enumerate(objects):
            item.name = name if index == 0 else f"{name}.{index:03}"
            for owner in list(item.users_collection):
                owner.objects.unlink(item)
            collection.objects.link(item)
        for image in set(bpy.data.images) - previous["images"]:
            if not image.packed_file:
                image.pack()
        return {**report, "collection": collection.name,
                "objects": [info(item) for item in objects],
                "imported_vertices": vertices, "imported_triangles": triangles}
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


def dispatch(operation, p):
    if operation == "owned_edit":
        operation, p = p["operation"], p["params"]
        if operation in {"owned_edit", "session_control", "scene_info", "object_info",
                         "runtime_status", "inspect_mesh_quality", "review_sheet"}:
            raise ValueError("Owned edit envelope requires a scene mutation")
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
    return {
        "version": bpy.app.version_string,
        "file": bpy.data.filepath,
        "workspace": str(_workspace),
        "total": len(objects),
        "offset": offset,
        "limit": limit,
        "objects": [info(objects[i]) for i in range(offset, min(offset + limit, len(objects)))],
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
    selection = list(objects)
    if empties:
        for value in objects:
            parent = value.parent
            while parent is not None:
                if (parent.type == "EMPTY" and parent not in selection
                        and parent.name in bpy.context.scene.objects):
                    selection.append(parent)
                parent = parent.parent
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
                filepath=str(path), export_format="GLB", use_selection=True, export_apply=True
            )
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
    if operation == "review_sheet":
        from .blender_review import review

        return review(p)
    if operation == "scatter":
        from .blender_scatter import scatter

        return scatter(p)
    if operation == "export_asset":
        from .blender_export import export_asset

        return export_asset(p)
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
    _workspace = Path(
        os.environ.get("CAVI_BLENDER_WORKSPACE", Path.home() / "Documents/CaviBlender")
    ).expanduser()
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
