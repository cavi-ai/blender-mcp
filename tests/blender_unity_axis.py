"""Native unity-axis export: identity FBX nodes, sockets kept, Blender re-import upright."""

import json
import math
import sys
import tempfile
from pathlib import Path

import bmesh
import bpy
from io_scene_fbx import parse_fbx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

folder = tempfile.TemporaryDirectory()
bridge._workspace = Path(folder.name).resolve()
state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "unity-axis", "expected_project": state["project_id"]})["lease_id"]


def edit(operation, **params):
    return bridge.dispatch("owned_edit", {"operation": operation,
                                          "params": {**params, "lease_id": lease}})


def box(name, location=(0, 0, 0)):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1)
    for v in bm.verts:
        v.co = (1 if v.co.x > 0 else 0, 0 if v.co.y > 0 else -2, 3 if v.co.z > 0 else 0)
    bm.to_mesh(mesh)
    bm.free()
    item = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(item)
    item.location = location
    return item


root = bpy.data.objects.new("SM_Test", None)
bpy.context.scene.collection.objects.link(root)
for item in (box("SM_Test_LOD0"), box("SM_Test_LOD1", (3, 0, 0)), box("UCX_SM_Test_00")):
    item.parent = root
edit("add_socket", name="SM_Test_LOD0", new_name="top", location=[0.5, -1, 3],
     rotation_degrees=[0, 0, 30])
exported = edit("export_asset", names=["SM_Test_LOD0"], path="unity.fbx", lods=True,
                collision=True, include_empties=True, axis="unity")
assert exported["collision"] == ["UCX_SM_Test_00"], exported


def props(element):
    found = {}
    for group in (e for e in element.elems if e.id == b"Properties70"):
        for row in group.elems:
            found[row.props[0].decode()] = list(row.props[4:])
    return found


document, _ = parse_fbx.parse(str(bridge._workspace / "unity.fbx"))
header = props(next(e for e in document.elems if e.id == b"GlobalSettings"))
assert header["UpAxis"] == [2] and header["UnitScaleFactor"] == [100.0], header
objects = next(e for e in document.elems if e.id == b"Objects")
nodes = {e.props[1].split(b"\0")[0].decode(): props(e) for e in objects.elems
         if e.id == b"Model"}
assert set(nodes) == {"SM_Test", "SM_Test_LOD0", "SM_Test_LOD1", "UCX_SM_Test_00",
                      "SOCKET_top"}, nodes
for name, values in nodes.items():
    rotation = values.get("Lcl Rotation", [0, 0, 0])
    expected = [0, 0, 30] if name == "SOCKET_top" else [0, 0, 0]
    assert all(abs(a - b) < 1e-4 for a, b in zip(rotation, expected)), (name, rotation)
    assert all(abs(v - 1) < 1e-6 for v in values.get("Lcl Scaling", [1, 1, 1])), name
    for key in ("PreRotation", "PostRotation", "GeometricRotation"):
        assert key not in values, (name, key)

for item in list(bpy.data.objects):
    bpy.data.objects.remove(item, do_unlink=True)
bpy.ops.import_scene.fbx(filepath=str(bridge._workspace / "unity.fbx"))
imported = {item.name: item for item in bpy.data.objects}
report = {}
for name, item in imported.items():
    angles = list(item.rotation_euler)
    expected = [0, 0, math.radians(30)] if name == "SOCKET_top" else [0, 0, 0]
    assert all(abs(a - b) < 1e-4 for a, b in zip(angles, expected)), (name, angles)
    assert all(abs(v - 1) < 1e-6 for v in item.scale), (name, item.scale)
    if item.type == "MESH":
        points = [v.co for v in item.data.vertices]
        low = [min(p[i] for p in points) for i in range(3)]
        high = [max(p[i] for p in points) for i in range(3)]
        assert all(abs(a - b) < 1e-4 for a, b in zip(low + high, [0, -2, 0, 1, 0, 3])), (
            name, low, high)
    report[name] = [round(v, 4) for v in [*item.location, *angles, *item.scale]]
socket = imported["SOCKET_top"]
assert socket.parent.name == "SM_Test_LOD0"
assert socket.location.to_tuple(4) == (0.5, -1.0, 3.0), socket.location
print(json.dumps(report))
