"""Native terrain, placement and surface-snap checks."""

import json
import resource
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

folder = tempfile.TemporaryDirectory()
root = Path(folder.name)
bridge._workspace = root
state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "level-fixture",
    "expected_project": state["project_id"]})["lease_id"]


def refused(operation, message, **params):
    try:
        bridge.dispatch(operation, {**params, "lease_id": lease})
    except (ValueError, RuntimeError, FileExistsError) as exc:
        assert message in str(exc), exc
    else:
        raise AssertionError(f"{operation} accepted {params}")


def peak_mb():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


try:
    # The densest noise request must not allocate a lattice finer than the mesh.
    baseline = peak_mb()
    dense = bridge.dispatch("create_terrain", {
        "name": "DenseTerrain", "resolution": 501, "octaves": 8, "frequency": 64,
        "lease_id": lease})
    assert dense["vertices"] == 501 * 501, dense
    assert peak_mb() - baseline < 400, f"peak grew {peak_mb() - baseline:.0f} MB"
    dense_mesh = bpy.data.objects["DenseTerrain"].data
    bpy.data.objects.remove(bpy.data.objects["DenseTerrain"], do_unlink=True)
    bpy.data.meshes.remove(dense_mesh)

    terrain = bridge.dispatch("create_terrain", {
        "name": "LevelTerrain", "size": [20, 10], "height": 4, "resolution": 9,
        "seed": 3, "octaves": 3, "frequency": 3, "lease_id": lease})
    assert terrain["triangles"] == 128 and terrain["vertices"] == 81, terrain
    assert terrain["source"] == "noise"
    assert terrain["minimum"] == 0 and terrain["maximum"] == 4, terrain
    mesh = bpy.data.objects["LevelTerrain"].data
    assert len(mesh.uv_layers) == 1
    assert all(polygon.use_smooth for polygon in mesh.polygons)

    image = bpy.data.images.new("Heightmap", 4, 4)
    pixels = []
    for index in range(16):
        shade = index / 15
        pixels.extend((shade, shade, shade, 1.0))
    image.pixels = pixels
    image.filepath_raw = str(root / "height.png")
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    mapped = bridge.dispatch("create_terrain", {
        "name": "ImageTerrain", "image": "height.png", "size": [4, 4], "height": 2,
        "resolution": 4, "location": [10, 0, 0], "lease_id": lease})
    assert mapped["source"] == "image" and mapped["triangles"] == 18, mapped
    assert mapped["image"]["width"] == 4 and mapped["image"]["height"] == 4

    bpy.ops.mesh.primitive_cube_add(location=(0, 0, 100))
    prop = bpy.context.object
    prop.name = prop.data.name = "LevelProp"
    placed = bridge.dispatch("place_objects", {
        "collection": "LevelProps", "lease_id": lease, "placements": [
            {"source": "LevelProp", "name": "LevelPropA", "location": [-2, 0, 10],
             "linked": False},
            {"source": "LevelProp", "name": "LevelPropB", "location": [2, 0, 10],
             "rotation_degrees": [0, 0, 45], "linked": True},
        ]})
    assert placed["count"] == 2 and placed["collection"] == "LevelProps", placed
    first, second = bpy.data.objects["LevelPropA"], bpy.data.objects["LevelPropB"]
    assert first.data != prop.data and second.data == prop.data
    assert first.matrix_world.translation == Vector((-2, 0, 10))
    assert "LevelPropA" in bpy.data.collections["LevelProps"].objects

    snapped = bridge.dispatch("snap_to_surface", {
        "names": ["LevelPropA", "LevelPropB"], "terrain": "LevelTerrain",
        "offset": 0.25, "align_to_normal": True, "lease_id": lease})
    assert snapped["terrain"] == "LevelTerrain" and len(snapped["objects"]) == 2
    for item in snapped["objects"]:
        value = bpy.data.objects[item["name"]]
        assert 0 <= item["surface"][2] <= 4, item
        assert abs(value.matrix_world.translation.z - item["surface"][2] - 0.25) < 1e-5
        up = value.matrix_world.to_3x3() @ Vector((0, 0, 1))
        assert up.normalized().dot(Vector(item["normal"])) > 0.99, item

    tilted = bpy.data.objects["LevelTerrain"]
    tilted.rotation_euler = (0.35, 0, 0.2)
    tilted.scale = (1.5, 1.2, 1.0)
    tilted.location = (0, 0, 5)
    bpy.context.view_layer.update()
    anchors = {"LevelPropA": (-2.0, 0.0), "LevelPropB": (2.0, 0.5)}
    for name, (x, y) in anchors.items():
        value = bpy.data.objects[name]
        value.matrix_world.translation = Vector((x, y, 200))
    tilted_snap = bridge.dispatch("snap_to_surface", {
        "names": ["LevelPropA", "LevelPropB"], "terrain": "LevelTerrain",
        "offset": 0.25, "align_to_normal": True, "lease_id": lease})
    for item in tilted_snap["objects"]:
        value = bpy.data.objects[item["name"]]
        assert abs(value.matrix_world.translation.z - item["surface"][2] - 0.25) < 1e-4
        assert (value.matrix_world.translation.x,
                value.matrix_world.translation.y) == anchors[item["name"]]
        up = (value.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
        assert up.dot(Vector(item["normal"]).normalized()) > 0.99, item
        assert abs(Vector(item["normal"]).normalized().z) < 0.999, item
    before = bpy.data.objects["LevelPropA"].rotation_euler.copy()
    flat = bridge.dispatch("snap_to_surface", {
        "names": ["LevelPropA"], "terrain": "LevelTerrain", "offset": 0.5,
        "align_to_normal": False, "lease_id": lease})
    value = bpy.data.objects["LevelPropA"]
    assert value.rotation_euler == before
    assert abs(value.matrix_world.translation.z - flat["objects"][0]["surface"][2] - 0.5) < 1e-4

    refused("create_terrain", "unique", name="LevelProp")
    refused("create_terrain", "501", name="TooFine", resolution=502)
    refused("create_terrain", "workspace", name="Outside", image="../outside.png")
    refused("place_objects", "more than once", placements=[
        {"source": "LevelProp", "name": "Twice"},
        {"source": "LevelProp", "name": "Twice"}])
    refused("place_objects", "scale components", placements=[
        {"source": "LevelProp", "name": "ZeroScale", "scale": [0, 1, 1]}])
    refused("place_objects", "does not exist", placements=[
        {"source": "MissingProp", "name": "Missing"}])

    # A placement that fails part-way leaves no objects and no new collection.
    from cavi_blender_mcp import blender_level

    class FailingMatrix:
        @staticmethod
        def LocRotScale(*args):
            raise RuntimeError("placement failed")

    original_matrix = blender_level.Matrix
    blender_level.Matrix = FailingMatrix
    try:
        refused("place_objects", "placement failed", collection="RolledBackProps",
                placements=[{"source": "LevelProp", "name": "NeverPlaced"}])
    finally:
        blender_level.Matrix = original_matrix
    assert "NeverPlaced" not in bpy.data.objects
    assert "RolledBackProps" not in bpy.data.collections
    refused("snap_to_surface", "No terrain surface", names=["LevelProp"],
            terrain="ImageTerrain")
    refused("snap_to_surface", "itself", names=["LevelTerrain"],
            terrain="LevelTerrain")
    try:
        bridge.dispatch("create_terrain", {"name": "Unowned"})
        raise AssertionError("Unowned terrain succeeded")
    except RuntimeError as exc:
        assert "lease_id" in str(exc)

    print(json.dumps({
        "terrain": [terrain["vertices"], terrain["triangles"]],
        "image_terrain": [mapped["vertices"], mapped["triangles"]],
        "placed": [placed["count"], placed["collection"]],
        "snapped": [item["name"] for item in snapped["objects"]],
    }))
finally:
    folder.cleanup()
