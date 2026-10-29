"""Blender-side bridge; all bpy operations execute on Blender's main thread."""

import hmac
import json
import math
import os
import queue
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import bpy
from mathutils import Vector

from .paths import destination

_server = None
_jobs = queue.Queue(maxsize=8)
_token = None
_connection = None
_workspace = None


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


def dispatch(operation, p):
    if operation == "scene_info":
        return {
            "version": bpy.app.version_string,
            "file": bpy.data.filepath,
            "workspace": str(_workspace),
            "objects": [info(v) for v in bpy.context.scene.objects],
        }
    if operation == "object_info":
        return info(obj(p["name"]))
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
        value = obj(p["name"], mesh=True)
        amount = vector([p["amount"]], 1)[0]
        if p["kind"] == "bevel" and 0 < amount <= 100:
            modifier = value.modifiers.new("Bevel", "BEVEL")
            modifier.width, modifier.segments = amount, 3
        elif p["kind"] == "decimate" and 0 < amount <= 1:
            modifier = value.modifiers.new("Decimate", "DECIMATE")
            modifier.ratio = amount
        else:
            raise ValueError("Invalid modifier or amount")
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
        with output_file(p["path"], {".fbx", ".glb"}) as path, selected(objects):
            if path.suffix.lower() == ".fbx":
                result = bpy.ops.export_scene.fbx(
                    filepath=str(path),
                    use_selection=True,
                    object_types={"MESH"},
                    add_leaf_bones=False,
                    bake_anim=False,
                    axis_forward="-Z",
                    axis_up="Y",
                    path_mode="STRIP",
                )
            else:
                result = bpy.ops.export_scene.gltf(
                    filepath=str(path), export_format="GLB", use_selection=True
                )
            if "FINISHED" not in result:
                raise RuntimeError("Mesh export did not finish")
        return {"path": str(path), "objects": p["names"], "bytes": path.stat().st_size}
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
    scene = bpy.context.scene
    points = [
        v.matrix_world @ Vector(c)
        for v in scene.objects
        if v.type == "MESH" and not v.hide_render
        for c in v.bound_box
    ]
    if not points:
        raise ValueError("Scene has no visible meshes")
    center = sum(points, Vector()) / len(points)
    radius = max((v - center).length for v in points)
    camera_data = bpy.data.cameras.new("MCP Preview")
    camera = bpy.data.objects.new("MCP Preview", camera_data)
    scene.collection.objects.link(camera)
    camera.location = center + Vector((1.5, -2, 1.4)).normalized() * max(radius * 3.5, 2)
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
    try:
        scene.camera = camera
        render.engine = "BLENDER_WORKBENCH"
        render.resolution_x = render.resolution_y = resolution
        render.resolution_percentage = 100
        render.image_settings.file_format = "PNG"
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        with output_file(p["path"], {".png"}) as path:
            render.filepath = str(path)
            if "FINISHED" not in bpy.ops.render.render(write_still=True):
                raise RuntimeError("Preview render did not finish")
        return {"path": str(path)}
    finally:
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
            self.headers.get("Authorization", ""), f"Bearer {_token}"
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


def register():
    global _server, _token, _connection, _workspace
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
    _token = secrets.token_hex(32)
    _server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    _server.daemon_threads = True
    fd, temporary = tempfile.mkstemp(dir=_connection.parent, prefix=".connection-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"host": "127.0.0.1", "port": _server.server_port, "token": _token}, stream)
        os.replace(temporary, _connection)
    finally:
        Path(temporary).unlink(missing_ok=True)
    bpy.app.timers.register(pump, persistent=True)
    threading.Thread(target=_server.serve_forever, daemon=True).start()


def unregister():
    global _server
    if _server is not None:
        _server.shutdown()
        _server.server_close()
        _server = None
    if bpy.app.timers.is_registered(pump):
        bpy.app.timers.unregister(pump)
    if _connection and _connection.exists():
        try:
            if json.loads(_connection.read_text()).get("token") == _token:
                _connection.unlink()
        except (ValueError, OSError):
            pass
