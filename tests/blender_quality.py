"""Native physical mapping, object material slots, and read-only state checks."""

import json
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

bpy.context.scene.unit_settings.system = "METRIC"
bpy.context.scene.unit_settings.scale_length = 1
mesh = bpy.data.meshes.new("QualityPlane")
mesh.from_pydata([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)], [], [(0, 1, 2, 3)])
uv = mesh.uv_layers.new(name="Surface")
for loop, point in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)]):
    loop.uv = point
plane = bpy.data.objects.new("QualityPlane", mesh)
bpy.context.scene.collection.objects.link(plane)
mesh.materials.append(bpy.data.materials.new("Data Material"))
material = bpy.data.materials.new("Object Material")
material.use_nodes = True
plane.material_slots[0].link = "OBJECT"
plane.material_slots[0].material = material
image = bpy.data.images.new("QualityBitmap", width=16, height=8)
with tempfile.TemporaryDirectory() as folder:
    image.filepath_raw = str(Path(folder) / "fixture.png")
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    image = bpy.data.images.load(str(Path(folder) / "fixture.png"))
    assert tuple(image.size) == (16, 8)
    image.pack()
material.node_tree.nodes.new("ShaderNodeTexImage").image = image
large = bpy.data.objects.new("ScaledPlane", mesh)
bpy.context.scene.collection.objects.link(large)
large.scale = (2, 2, 2)
large.material_slots[0].link = "OBJECT"
large.material_slots[0].material = material
bpy.context.view_layer.update()
state = bridge.dispatch("session_control", {"action": "inspect"})
bridge.dispatch(
    "session_control",
    {"action": "claim", "owner": "another-editor", "expected_project": state["project_id"]},
)
before = bridge.dispatch("scene_info", {})
selected = list(bpy.context.selected_objects)
active = bpy.context.view_layer.objects.active
counts = (
    len(bpy.data.objects),
    len(bpy.data.meshes),
    len(bpy.data.materials),
    len(bpy.data.images),
)
result = bridge.dispatch(
    "inspect_mesh_quality", {"names": [plane.name, large.name], "texture_resolution": [1024, 1024]}
)
first, second = result["objects"]
assert first["mapping"]["density_area_weighted"] == 512
assert second["mapping"]["density_area_weighted"] == 256
assert first["mapping"]["anisotropy_max"] == 1
assert first["surfaces"][0]["material"] == "Object Material"
assert result["unique_materials"] == 1
assert result["unique_meshes"] == 1
assert first["mesh"] == second["mesh"]
assert result["project_id"] == state["project_id"]
assert result["images"][0]["size"] == [16, 8]
assert result["images"][0]["packed"]
assert result["not_checked"] == ["UV overlaps", "seam continuity", "shader appearance"]
assert bridge.dispatch("scene_info", {}) == before
assert (
    selected == list(bpy.context.selected_objects)
    and active == bpy.context.view_layer.objects.active
)
assert counts == (
    len(bpy.data.objects),
    len(bpy.data.meshes),
    len(bpy.data.materials),
    len(bpy.data.images),
)
bpy.context.scene.unit_settings.scale_length = 0.01
centimeters = bridge.dispatch("inspect_mesh_quality", {"names": [plane.name]})
assert abs(centimeters["objects"][0]["mapping"]["density_area_weighted"] - 51200) < 0.1
bpy.context.scene.unit_settings.system = "NONE"
unitless = bridge.dispatch("inspect_mesh_quality", {"names": [plane.name]})
assert unitless["scene_unit_meters"] == 1
assert unitless["objects"][0]["mapping"]["density_area_weighted"] == 512
bpy.context.scene.unit_settings.system = "METRIC"
bpy.context.scene.unit_settings.scale_length = 1
for params, error in [
    ({"names": [plane.name], "uv_layer": "Missing"}, "UV layer"),
    ({"names": [plane.name] * 2}, "unique"),
]:
    try:
        bridge.dispatch("inspect_mesh_quality", params)
        raise AssertionError("Invalid inspection succeeded")
    except ValueError as exc:
        assert error in str(exc)
invalid_mesh = mesh.copy()
invalid_mesh.materials.clear()
invalid_mesh.polygons[0].material_index = 17
invalid = bpy.data.objects.new("InvalidSlot", invalid_mesh)
bpy.context.scene.collection.objects.link(invalid)
try:
    bridge.dispatch("inspect_mesh_quality", {"names": [invalid.name]})
    raise AssertionError("Missing material slots created unbounded surface groups")
except ValueError as exc:
    assert "material slot" in str(exc)
plane.modifiers.new("Unbaked", "SUBSURF")
try:
    bridge.dispatch("inspect_mesh_quality", {"names": [plane.name]})
    raise AssertionError("Unbaked modifier was evaluated")
except ValueError as exc:
    assert "modifier" in str(exc)
print(json.dumps({"read_only_inspection": True, "physical_density": True, "slot_binding": True}))
