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
from mathutils import Vector

from .geometry import validate_mesh
from .importing import MAX_BYTES, MAX_GEOMETRY, inspect_glb
from .lease import Lease
from .paths import destination

_server = None
_jobs = queue.Queue(maxsize=8)
_token = None
_connection = None
_workspace = None
_lease = Lease()
_project_epoch = secrets.token_hex(16)


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


def info(value):
    result = {
        "name": value.name,
        "type": value.type,
        "location": list(value.location),
        "rotation_degrees": [math.degrees(v) for v in value.rotation_euler],
        "scale": list(value.scale),
        "modifiers": [{"name": m.name, "type": m.type} for m in value.modifiers],
    }
    if value.type == "MESH":
        result.update(
            vertices=len(value.data.vertices),
            polygons=len(value.data.polygons),
            uv_layers=len(value.data.uv_layers),
            materials=[m.name if m else None for m in value.data.materials],
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
        if operation in {"owned_edit", "session_control", "scene_info", "object_info", "runtime_status", "inspect_mesh_quality"}:
            raise ValueError("Owned edit envelope requires a scene mutation")
    if operation == "session_control":
        return _lease.control(p, project_identity)
    if operation in {"scene_info", "object_info", "runtime_status", "inspect_mesh_quality"}:
        return _dispatch(operation, p)
    params = dict(p)
    with _lease.edit(params.pop("lease_id", None), project_identity):
        return _dispatch(operation, params)


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
    if operation in {"runtime_status", "runtime_restart"}:
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
        }
    if operation == "scene_info":
        return {
            "version": bpy.app.version_string,
            "file": bpy.data.filepath,
            "workspace": str(_workspace),
            "objects": [info(v) for v in bpy.context.scene.objects],
        }
    if operation == "object_info":
        return info(obj(p["name"]))
    if operation == "create_mesh":
        name = p["name"]
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 63
            or name in bpy.data.objects
        ):
            raise ValueError("Object name must be unique, nonempty, and at most 63 characters")
        if bpy.context.mode != "OBJECT":
            raise ValueError("Switch Blender to Object Mode before creating geometry")
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
    if operation == "create_primitive":
        name = p["name"]
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 63
            or name in bpy.data.objects
        ):
            raise ValueError("Object name must be unique, nonempty, and at most 63 characters")
        constructors = {
            "cube": bpy.ops.mesh.primitive_cube_add,
            "sphere": bpy.ops.mesh.primitive_uv_sphere_add,
            "cylinder": bpy.ops.mesh.primitive_cylinder_add,
            "cone": bpy.ops.mesh.primitive_cone_add,
            "plane": bpy.ops.mesh.primitive_plane_add,
        }
        if p["kind"] not in constructors:
            raise ValueError("Unknown primitive")
        if bpy.context.mode != "OBJECT":
            raise ValueError("Switch Blender to Object Mode before creating geometry")
        constructors[p["kind"]](location=vector(p.get("location", [0, 0, 0])))
        value = bpy.context.object
        value.name = name
        return info(value)
    if operation == "transform_object":
        value = obj(p["name"])
        updates = {
            k: vector(p[k])
            for k in ("location", "rotation_degrees", "scale")
            if p.get(k) is not None
        }
        if "scale" in updates and any(v <= 0 for v in updates["scale"]):
            raise ValueError("Scale components must be positive")
        for key, values in updates.items():
            setattr(
                value,
                "rotation_euler" if key == "rotation_degrees" else key,
                [math.radians(v) for v in values] if key == "rotation_degrees" else values,
            )
        return info(value)
    if operation == "set_color":
        value = editable_mesh(p["name"])
        color = vector(p["rgba"], 4)
        if any(v < 0 or v > 1 for v in color):
            raise ValueError("Color components must range from 0 to 1")
        material = bpy.data.materials.new(f"{value.name} Color")
        material.diffuse_color = color
        value.data.materials.clear()
        value.data.materials.append(material)
        return info(value)
    if operation == "add_modifier":
        bake = p.get("apply", False)
        if type(bake) is not bool:
            raise ValueError("apply must be boolean")
        value = editable_mesh(p["name"]) if bake else obj(p["name"], mesh=True)
        if bake and (value.modifiers or bpy.context.mode != "OBJECT"):
            raise ValueError("Baking requires Object Mode and no existing modifiers")
        amount = vector([p["amount"]], 1)[0]
        if p["kind"] == "bevel" and 0 < amount <= 100:
            modifier = value.modifiers.new("Bevel", "BEVEL")
            modifier.width, modifier.segments = amount, 3
        elif p["kind"] == "decimate" and 0 < amount <= 1:
            modifier = value.modifiers.new("Decimate", "DECIMATE")
            modifier.ratio = amount
        elif p["kind"] in {"subdivision", "voxel_remesh"}:
            # Refuse stacked surface operations: their combined cost is not bounded by base counts.
            if value.modifiers:
                raise ValueError("Organic modifiers require a mesh without existing modifiers")
            if p["kind"] == "subdivision":
                facets = sum(max(4, len(face.vertices)) for face in value.data.polygons)
                if amount not in (1, 2, 3) or facets * 4 ** (amount - 1) > 500000:
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
    if operation == "shade_mesh":
        value = editable_mesh(p["name"])
        if type(p["smooth"]) is not bool:
            raise ValueError("smooth must be boolean")
        for polygon in value.data.polygons:
            polygon.use_smooth = p["smooth"]
        return info(value)
    if operation == "unwrap_mesh":
        value = editable_mesh(p["name"])
        with selected([value]):
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project()
        return info(value)
    if operation == "export_mesh":
        if not isinstance(p["names"], list) or not p["names"] or len(p["names"]) > 1000:
            raise ValueError("Provide between 1 and 1000 mesh names")
        objects = [obj(n, mesh=True) for n in p["names"]]
        preserve = p.get("preserve_instances", False)
        if type(preserve) is not bool:
            raise ValueError("preserve_instances must be a boolean")
        if preserve and Path(p["path"]).suffix.lower() != ".fbx":
            raise ValueError("preserve_instances applies to static FBX exports")
        with output_file(p["path"], {".fbx", ".glb"}) as path, selected(objects):
            if path.suffix.lower() == ".fbx":
                from .export_instances import instance_meshes

                with instance_meshes(objects) if preserve else nullcontext():
                    result = bpy.ops.export_scene.fbx(
                        filepath=str(path),
                        use_selection=True,
                        object_types={"MESH"},
                        add_leaf_bones=False,
                        bake_anim=False,
                        axis_forward="-Z",
                        axis_up="Y",
                        global_scale=1,
                        apply_unit_scale=True,
                        apply_scale_options="FBX_SCALE_UNITS",
                        bake_space_transform=True,
                        path_mode="STRIP",
                    )
            else:
                result = bpy.ops.export_scene.gltf(
                    filepath=str(path), export_format="GLB", use_selection=True
                )
            if "FINISHED" not in result:
                raise RuntimeError("Mesh export did not finish")
        return {"path": str(path), "objects": p["names"], "bytes": path.stat().st_size,
                "preserve_instances": preserve}
    if operation == "save_project":
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
    if operation == "render_preview":
        return preview(p)
    raise ValueError(f"Unknown operation: {operation}")


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
    radius = max((v - center).length for v in points)
    camera_data = bpy.data.cameras.new("MCP Preview")
    camera = bpy.data.objects.new("MCP Preview", camera_data)
    scene.collection.objects.link(camera)
    camera.location = center + direction.normalized() * max(radius * 3.5, 2)
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
    visibility = [(v, v.hide_render) for v in scene.objects if v.type == "MESH"]
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
            job["error"] = "Request expired before execution"
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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path != "/rpc" or not hmac.compare_digest(
            self.headers.get("Authorization", ""), f"Bearer {self.server.bridge_token}"
        ):
            self.send_error(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_048_576:
                raise ValueError("Invalid request size")
            self.connection.settimeout(5)
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict) or not isinstance(request.get("id"), str):
                raise TypeError("Invalid request")
            job = {
                "operation": request["operation"],
                "params": request.get("params", {}),
                "done": threading.Event(),
                "lock": threading.Lock(),
                "started": False,
                "cancelled": False,
                "deadline": time.monotonic() + 60,
            }
            _jobs.put_nowait(job)
            if not job["done"].wait(60):
                with job["lock"]:
                    job["cancelled"] = not job["started"]
                result = {
                    "error": "Timed out; inspect the scene before retrying. Outcome may be unknown."
                }
            else:
                result = (
                    {"error": job["error"]}
                    if "error" in job
                    else {
                        "result": job.get("result"),
                    }
                )
            body = json.dumps({"id": request["id"], **result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ValueError, TypeError, KeyError, queue.Full):
            self.send_error(400)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass


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
                {"host": "127.0.0.1", "port": server.server_port, "token": server.bridge_token},
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
    _connection = Path(
        os.environ.get("CAVI_BLENDER_CONNECTION", Path.home() / ".cavi/blender-mcp/connection.json")
    )
    _connection.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if _connection.exists():
        from .client import BridgeClient

        try:
            BridgeClient(_connection).call("scene_info")
        except (ConnectionError, ValueError):
            pass
        else:
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
