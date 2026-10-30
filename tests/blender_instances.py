"""FBX geometry sharing with resolved object material overrides and rollback."""

import json
import sys
import tempfile
from pathlib import Path

import bpy
from io_scene_fbx import parse_fbx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

first = bpy.data.objects["Cube"]
second = first.copy()
second.name = "Repeated"
second.location.x = 4
bpy.context.scene.collection.objects.link(second)
variant = first.copy()
variant.name = "DifferentFinish"
variant.location.y = 4
bpy.context.scene.collection.objects.link(variant)
one = bpy.data.materials.new("SharedFinish")
two = bpy.data.materials.new("OtherFinish")
detail = bpy.data.materials.new("DetailFinish")
first.data.materials.append(detail)
first.data.polygons[0].material_index = 1
for value, material in [(first, one), (second, one), (variant, two)]:
    value.material_slots[0].link = "OBJECT"
    value.material_slots[0].material = material
objects = [first, second, variant]
bpy.context.view_layer.update()


def state():
    return [
        (
            value.data,
            tuple(slot.link for slot in value.material_slots),
        tuple(slot.material for slot in value.material_slots),
        tuple(value.data.materials),
        tuple(face.material_index for face in value.data.polygons),
            value.matrix_world.copy(),
        )
        for value in objects
    ], set(bpy.data.meshes)


before = state()
owner = bridge.dispatch("session_control", {"action": "inspect"})
token = bridge.dispatch(
    "session_control",
    {"action": "claim", "owner": "instance-fixture", "expected_project": owner["project_id"]},
)["lease_id"]
with tempfile.TemporaryDirectory() as folder:
    bridge._workspace = Path(folder)
    bridge.dispatch(
        "export_instances",
        {
            "names": [value.name for value in objects],
            "path": "shared.fbx",
            "preserve_instances": True,
            "lease_id": token,
        },
    )
    root, _ = parse_fbx.parse(str(Path(folder) / "shared.fbx"))
    nodes = next(value for value in root.elems if value.id == b"Objects")
    geometry = {value.props[0] for value in nodes.elems if value.id == b"Geometry"}
    assert len(geometry) == 2, f"Expected two geometry definitions, got {len(geometry)}"
    models = {
        value.props[1].split(b"\0")[0].decode(): value.props[0]
        for value in nodes.elems
        if value.id == b"Model"
    }
    connections = next(value for value in root.elems if value.id == b"Connections")
    assigned = {
        value.props[2]: value.props[1]
        for value in connections.elems
        if value.props[0] == b"OO" and value.props[1] in geometry
    }
    assert assigned[models[first.name]] == assigned[models[second.name]]
    assert assigned[models[first.name]] != assigned[models[variant.name]]
    materials = {
        value.props[0]: value.props[1].split(b"\0")[0].decode()
        for value in nodes.elems
        if value.id == b"Material"
    }
    for value, expected in [(first, one), (second, one), (variant, two)]:
        slots = [
            materials[item.props[1]]
            for item in connections.elems
            if item.props[0] == b"OO"
            and item.props[1] in materials
            and item.props[2] == models[value.name]
        ]
        assert slots == [expected.name, detail.name], slots
    for value in nodes.elems:
        if value.id == b"Geometry":
            layer = next(child for child in value.elems if child.id == b"LayerElementMaterial")
            indices = next(child.props[0] for child in layer.elems if child.id == b"Materials")
            assert set(indices) == {0, 1}, list(indices)
assert state() == before, "Export changed source mesh data, slots, transforms or mesh datablocks"
from cavi_blender_mcp.export_instances import instance_meshes

try:
    with instance_meshes(objects):
        raise RuntimeError("Injected exporter failure")
except RuntimeError:
    pass
assert state() == before, "Failed export leaked temporary geometry or changed material bindings"
print(json.dumps({"instance_export": True, "material_variants": True, "restored": True}))
