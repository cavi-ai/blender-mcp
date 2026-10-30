"""Native checks for rotation modes, materials, UVs, previews, exports and bridge errors."""

import http.client
import json
import math
import os
import sys
import tempfile
import threading
from pathlib import Path

import bpy
from mathutils import Euler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp.client import BridgeClient

folder = tempfile.TemporaryDirectory()
root = Path(folder.name)
os.environ["CAVI_BLENDER_CONNECTION"] = str(root / "connection.json")
os.environ["CAVI_BLENDER_WORKSPACE"] = str(root / "assets")
(root / "connection.json").write_text(json.dumps(
    {"host": "127.0.0.1", "port": 1, "token": "x" * 64, "pid": 2 ** 22 + 12345}))
(root / "connection.json").chmod(0o600)
bridge.register()
assert json.loads((root / "connection.json").read_text())["pid"] == os.getpid()
workspace = bridge._workspace

state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "harden-fixture", "expected_project": state["project_id"]})["lease_id"]


def edit(operation, **params):
    return bridge.dispatch(operation, {**params, "lease_id": lease})


def refused(operation, message, **params):
    try:
        edit(operation, **params)
    except (ValueError, RuntimeError) as exc:
        assert message in str(exc), exc
    else:
        raise AssertionError(f"{operation} accepted {params}")


# Deterministic primitive collection and mesh naming.
other = bpy.data.collections.new("Other")
bpy.context.scene.collection.children.link(other)
bpy.context.view_layer.active_layer_collection = (
    bpy.context.view_layer.layer_collection.children["Other"])
edit("create_primitive", name="Rot", kind="cube")
rot = bpy.data.objects["Rot"]
assert rot.data.name == "Rot", rot.data.name
assert list(rot.users_collection) == [bpy.context.scene.collection]

# Rotation modes.
expected = Euler([math.radians(v) for v in (30, 45, 60)], "XYZ").to_matrix()
for mode in ("XYZ", "QUATERNION", "AXIS_ANGLE", "ZXY"):
    rot.rotation_mode = mode
    result = edit("transform_object", name="Rot", rotation_degrees=[30, 45, 60])
    bpy.context.view_layer.update()
    actual = rot.matrix_world.to_3x3().normalized()
    assert all(abs(actual[i][j] - expected[i][j]) < 1e-5 for i in range(3) for j in range(3)), mode
    assert result["rotation_mode"] == mode
    assert all(abs(a - b) < 1e-3 for a, b in zip(result["rotation_degrees"], (30, 45, 60))), result

# set_color reuses one material per slot and preserves other slots.
first, second = bpy.data.materials.new("First"), bpy.data.materials.new("Second")
rot.data.materials.append(first)
rot.data.materials.append(second)
count = len(bpy.data.materials)
edit("set_color", name="Rot", rgba=[1, 0, 0, 1], slot=1)
edit("set_color", name="Rot", rgba=[0, 1, 0, 1], slot=1)
assert len(bpy.data.materials) == count + 1, "set_color created an orphan material"
assert rot.material_slots[0].material == first
color = rot.material_slots[1].material
assert color.name == "Rot Color 1" and tuple(color.diffuse_color) == (0, 1, 0, 1)
refused("set_color", "slot does not exist", name="Rot", rgba=[0, 0, 0, 1], slot=2)
edit("create_primitive", name="Bare", kind="plane")
edit("set_color", name="Bare", rgba=[0, 0, 1, 1])
edit("set_color", name="Bare", rgba=[0, 0, .5, 1])
assert [m.name for m in bpy.data.objects["Bare"].data.materials] == ["Bare Color"]
assert not [m for m in bpy.data.materials if m.users == 0 and m.get(bridge.COLOR_TAG)]

# Unwrap into a named layer with explicit parameters.
before = [layer.name for layer in rot.data.uv_layers]
result = edit("unwrap_mesh", name="Rot", uv_layer="Lightmap", angle_limit_degrees=45,
              island_margin=0.01)
assert result["uv_layer"] == "Lightmap" and result["uv_layers"] == len(before) + 1
uvs = [tuple(loop.uv) for loop in rot.data.uv_layers["Lightmap"].data]
assert all(-1e-4 <= c <= 1 + 1e-4 for uv in uvs for c in uv)
assert len(set(uvs)) > 4
refused("unwrap_mesh", "angle_limit_degrees", name="Rot", angle_limit_degrees=120)

# Modifier stack depth and evaluated bevel budget.
edit("create_primitive", name="Stack", kind="cube")
for _ in range(bridge.MAX_MODIFIERS):
    edit("add_modifier", name="Stack", kind="decimate", amount=0.9)
refused("add_modifier", "limited to 16", name="Stack", kind="decimate", amount=0.9)
grid = [[x * 0.01, y * 0.01, 0] for y in range(100) for x in range(100)]
triangles = []
for y in range(99):
    for x in range(99):
        a = y * 100 + x
        triangles += [[a, a + 1, a + 101], [a, a + 101, a + 100]]
edit("create_mesh", name="Dense", vertices=grid, faces=triangles)
edit("add_modifier", name="Dense", kind="subdivision", amount=2)
refused("add_modifier", "Bevel would exceed", name="Dense", kind="bevel", amount=0.001)

# Preview needs no lease; orthographic, clip range and isolation of non-mesh renderables.
text = bpy.data.objects.new("Label", bpy.data.curves.new("Label", "FONT"))
curve = bpy.data.objects.new("Path", bpy.data.curves.new("Path", "CURVE"))
for value in (text, curve):
    bpy.context.scene.collection.objects.link(value)
edit("create_primitive", name="Huge", kind="cube")
bpy.data.objects["Huge"].scale = (1000, 1000, 1000)
seen = []


def inspect_render(scene):
    seen.append((scene.camera.data.type, scene.camera.data.clip_end,
                 (scene.camera.location - bpy.data.objects["Huge"].location).length,
                 text.hide_render, curve.hide_render, bpy.data.objects["Rot"].hide_render))


bpy.app.handlers.render_pre.append(inspect_render)
try:
    bridge.dispatch("render_preview", {"path": "huge.png", "resolution": 64, "names": ["Huge"],
                                       "orthographic": True})
finally:
    bpy.app.handlers.render_pre.remove(inspect_render)
kind, clip_end, distance, text_hidden, curve_hidden, rot_hidden = seen[0]
assert kind == "ORTHO" and clip_end > distance + 1732, (clip_end, distance)
assert text_hidden and curve_hidden and rot_hidden
assert not text.hide_render and not curve.hide_render and not bpy.data.objects["Rot"].hide_render
assert (workspace / "huge.png").stat().st_size > 0

# Scene pagination.
page = bridge.dispatch("scene_info", {"limit": 2, "offset": 1})
assert page["total"] == len(bpy.context.scene.objects)
assert [o["name"] for o in page["objects"]] == [o.name for o in bpy.context.scene.objects[1:3]]
assert bridge.dispatch("scene_info", {"offset": 10 ** 6})["objects"] == []
for params in ({"limit": 0}, {"limit": 1001}, {"offset": -1}, {"limit": True}):
    try:
        bridge.dispatch("scene_info", params)
    except ValueError:
        pass
    else:
        raise AssertionError(params)

# Textured material uses ShaderNodeMix and a relative image path once saved.
edit("save_project", path="harden.blend")
image = bpy.data.images.new("Fixture", width=2, height=2)
image.filepath_raw = str(workspace / "color.png")
image.file_format = "PNG"
image.save()
bpy.data.images.remove(image)
edit("assign_material", names=["Rot"], material_name="Textured", base_color_texture="color.png",
     slot=0)
material = bpy.data.materials["Textured"]
mix = [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeMix"]
assert mix and mix[0].data_type == "RGBA" and mix[0].blend_type == "MULTIPLY"
assert not [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeMixRGB"]
textured = next(node.image for node in material.node_tree.nodes if node.type == "TEX_IMAGE")
assert textured.filepath.startswith("//"), textured.filepath
assert rot.material_slots[1].material == color

# FBX smoothing, tangents and optional empty hierarchy; GLB applies modifiers.
from io_scene_fbx import parse_fbx

parent = bpy.data.objects.new("Pivot", None)
bpy.context.scene.collection.objects.link(parent)
rot.parent = parent


def fbx_models(name):
    document, _ = parse_fbx.parse(str(workspace / name))
    objects = next(item for item in document.elems if item.id == b"Objects")
    models = {item.props[1].split(b"\0")[0].decode() for item in objects.elems
              if item.id == b"Model"}
    geometry = next(item for item in objects.elems if item.id == b"Geometry")
    layers = {child.id for child in geometry.elems}
    smoothing = next(child for child in geometry.elems if child.id == b"LayerElementSmoothing")
    mapping = next(child.props[0] for child in smoothing.elems
                   if child.id == b"MappingInformationType")
    return models, layers, mapping


edit("export_mesh", names=["Rot"], path="flat.fbx")
models, layers, mapping = fbx_models("flat.fbx")
assert models == {"Rot"}, models
assert mapping == b"ByPolygon", mapping
assert b"LayerElementTangent" in layers, layers
assert edit("export_mesh", names=["Rot"], path="tree.fbx", include_empties=True)["include_empties"]
assert fbx_models("tree.fbx")[0] == {"Rot", "Pivot"}
edit("create_primitive", name="Beveled", kind="cube")
edit("add_modifier", name="Beveled", kind="bevel", amount=0.1)
edit("export_mesh", names=["Beveled"], path="beveled.glb")
from cavi_blender_mcp.importing import inspect_glb

assert inspect_glb(workspace, "beveled.glb")["triangles"] > 12, "GLB skipped modifiers"

# Real HTTP bridge: maximal payload, structured error statuses.
coordinate = -123456.78901234567
vertices = [[coordinate + x, coordinate + y, 0.12345678901234567] for y in range(100)
            for x in range(100)]
faces = [[a, b, c] for a, b, c in triangles]
assert len(vertices) == 10000 and len(faces) == 19602
client = BridgeClient()
outcome = {}


def background(function, *args):
    def run():
        try:
            outcome["result"] = function(*args)
        except Exception as exc:  # noqa: BLE001
            outcome["error"] = exc

    worker = threading.Thread(target=run)
    worker.start()
    return worker


def pump_until(worker):
    while worker.is_alive():
        with bridge._jobs.not_empty:
            bridge._jobs.not_empty.wait_for(lambda: bool(bridge._jobs.queue), timeout=0.1)
        bridge.pump()


worker = background(client.call, "owned_edit", {"operation": "create_mesh", "params": {
    "name": "MaxPayload", "vertices": vertices, "faces": faces, "lease_id": lease}})
pump_until(worker)
assert "error" not in outcome, outcome
assert outcome["result"]["vertices"] == 10000
config = json.loads((root / "connection.json").read_text())


def raw(body, length=None, timeout=10):
    connection = http.client.HTTPConnection("127.0.0.1", config["port"], timeout=timeout)
    try:
        connection.putrequest("POST", "/rpc")
        connection.putheader("Authorization", f"Bearer {config['token']}")
        connection.putheader("Content-Length", str(length if length is not None else len(body)))
        connection.endheaders()
        if body:
            connection.send(body)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


status, payload = raw(b"", length=bridge.MAX_REQUEST_BYTES + 1)
assert status == 413 and "exceeds" in payload["error"], (status, payload)
status, payload = raw(b"{not json")
assert status == 400 and payload["error"].startswith("Bad request"), (status, payload)
status, payload = raw(json.dumps({"id": "t", "operation": "scene_info", "timeout": 0.3}).encode())
assert status == 504 and "not started" in payload["error"], (status, payload)
bridge.pump()
outcome.clear()
try:
    client.call("scene_info", timeout=0.3)
except ConnectionError as exc:
    assert "HTTP 504: Request was not started" in str(exc), exc
else:
    raise AssertionError("Unpumped request succeeded")
bridge.pump()
codes = []
request = json.dumps({"id": "q", "operation": "scene_info", "timeout": 2}).encode()
workers = [threading.Thread(target=lambda: codes.append(raw(request)[0])) for _ in range(9)]
for item in workers:
    item.start()
for item in workers:
    item.join()
while not bridge._jobs.empty():
    bridge.pump()
assert sorted(codes) == [503] + [504] * 8, codes
bridge.unregister()
assert not (root / "connection.json").exists()
folder.cleanup()
print(json.dumps({"native_harden": "passed"}))
