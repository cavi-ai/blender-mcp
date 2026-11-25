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


def topology_case(name, points, faces):
    data = bpy.data.meshes.new(name)
    data.from_pydata(points, [], faces)
    item = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(item)
    return item.name


square = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
cube = square + [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
defects = [
    topology_case("FlippedCube", cube, [(0, 3, 2, 1), (7, 6, 5, 4), (0, 1, 5, 4), (2, 3, 7, 6),
                                        (0, 4, 7, 3), (1, 2, 6, 5)]),
    topology_case("UnweldedPair", square[:3] + [(0, 0, 0), (1, 1, 0.005), (0, 1, 0)],
                  [(0, 1, 2), (3, 4, 5)]),
    topology_case("Needle", [(0, 0, 0), (1, 0, 0), (0.5, 0.005, 0)], [(0, 1, 2)]),
    topology_case("CrossingQuads", square + [(0.25, 0.5, -0.5), (0.75, 0.5, -0.5),
                                             (0.75, 0.5, 0.5), (0.25, 0.5, 0.5)],
                  [(0, 1, 2, 3), (4, 5, 6, 7)]),
]
DEFECTS = ("inconsistent_winding_edges", "coincident_vertex_pairs", "sliver_triangles",
           "self_intersecting_face_pairs")


def topology_defects():
    found = bridge.dispatch("inspect_mesh_quality", {"names": defects, "checks": ["topology"]})
    return found, [[item["checks"]["topology"][field] for field in DEFECTS]
                   for item in found["objects"]]


topology_report, defect_counts = topology_defects()
assert defect_counts == [[4, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], defect_counts
flipped, unwelded, needle, crossing = (item["checks"]["topology"]
                                       for item in topology_report["objects"])
assert len(flipped["inconsistent_winding_edge_examples"]) == 4, flipped
assert flipped["non_manifold_edges"] == flipped["boundary_edges"] == 0, flipped
assert unwelded["coincident_vertex_pair_examples"] == [[0, 3]], unwelded
assert needle["sliver_triangle_examples"] == [[0, 0]], needle
assert crossing["self_intersecting_face_pair_examples"] == [[0, 1]], crossing
assert "coplanar face overlaps" in topology_report["not_checked"], topology_report["not_checked"]
bpy.context.scene.unit_settings.scale_length = 0.01
assert topology_defects()[1][1] == [0, 2, 0, 0]
bpy.context.scene.unit_settings.scale_length = 1

left = [(0, -1, 0), (0, 1, 0), (2, 1, 0)]
right = [(0, 0, -1), (0, 0, 1), (2, 0, 1)]
# Equal numbers of distant triangles put the crossing faces on opposite sides of the BVH partition.
spaced = left + right + [(x + dx, dy, 0) for gap in range(10, 650, 10) for x in (-gap, gap)
                         for dx, dy in ((0, 0), (1, 0), (0, 1))]
split_crossing = topology_case("CrossChunkCrossing", spaced,
                               [(i, i + 1, i + 2) for i in range(0, len(spaced), 3)])
stack = left * 1100 + right * 1100
dense_crossings = topology_case("DenseCrossings", stack,
                                [(i, i + 1, i + 2) for i in range(0, len(stack), 3)])
dense_points = topology_case("DenseCoincidence", [(i * 1e-8, 0, 0) for i in range(1500)], [])
bounded = bridge.dispatch("inspect_mesh_quality", {
    "names": [dense_crossings, dense_points, split_crossing], "checks": ["topology", "transforms"]})
for item in bounded["objects"]:
    assert item["checks"]["transforms"]["scale_applied"], item
stacked, close, split = (item["checks"]["topology"] for item in bounded["objects"])
assert stacked["self_intersecting_face_pairs"] is None, stacked
assert not stacked["self_intersecting_face_pairs_complete"], stacked
assert stacked["self_intersecting_face_pair_examples"] == [], stacked
assert stacked["coincident_vertex_pairs"] == 6 * 1100 * 1099 // 2, stacked
assert close["coincident_vertex_pairs"] is None, close
assert not close["coincident_vertex_pairs_complete"], close
assert close["self_intersecting_face_pairs"] == 0, close
assert split["self_intersecting_face_pairs_complete"], split
assert split["self_intersecting_face_pairs"] == 1, split
assert split["self_intersecting_face_pair_examples"] == [[0, 1]], split
print(json.dumps({"read_only_inspection": True, "physical_density": True, "slot_binding": True,
                  "topology_defects": True, "bounded_topology": True}))
