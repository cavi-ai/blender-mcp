"""Native normal/AO baking, output and scene-restoration checks."""

import json
import sys
import tempfile
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

folder = tempfile.TemporaryDirectory()
root = Path(folder.name)
bridge._workspace = root
state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "bake-fixture",
    "expected_project": state["project_id"]})["lease_id"]


def edit(operation, **params):
    return bridge.dispatch("owned_edit", {"operation": operation,
                                          "params": {**params, "lease_id": lease}})


def refused(operation, message, **params):
    try:
        edit(operation, **params)
    except (ValueError, RuntimeError, FileExistsError) as exc:
        assert message in str(exc), exc
    else:
        raise AssertionError(f"{operation} accepted {params}")


def variance(path):
    image = bpy.data.images.load(str(path))
    try:
        pixels = np.empty(len(image.pixels), np.float32)
        image.pixels.foreach_get(pixels)
        return float(pixels.reshape(-1, 4)[:, :3].std()), tuple(image.size)
    finally:
        bpy.data.images.remove(image)


try:
    bpy.ops.mesh.primitive_cube_add()
    low = bpy.context.object
    low.name = low.data.name = "BakeLow"
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.2)
    high = bpy.context.object
    high.name = high.data.name = "BakeHigh"
    scene = bpy.context.scene
    objects = set(bpy.data.objects)
    materials = set(bpy.data.materials)
    images = set(bpy.data.images)
    engine = scene.render.engine
    selection = {value.name for value in bpy.context.selected_objects}
    active = bpy.context.view_layer.objects.active
    visibility = {value.name: value.hide_render for value in scene.objects}

    normal = edit("bake_map", map="normal", name="BakeLow", path="normal.png",
                  high=["BakeHigh"], resolution=64, samples=1, margin=2,
                  cage_extrusion=.1, max_ray_distance=.5)
    assert normal["selected_to_active"] and normal["map"] == "normal", normal
    assert normal["bytes"] > 0 and normal["resolution"] == 64
    deviation, size = variance(root / "normal.png")
    assert size == (64, 64) and deviation > 0.01, (deviation, size)
    assert scene.render.engine == engine
    assert {value.name for value in bpy.context.selected_objects} == selection
    assert bpy.context.view_layer.objects.active == active
    assert set(bpy.data.objects) == objects
    assert set(bpy.data.materials) == materials
    assert set(bpy.data.images) == images
    assert {value.name: value.hide_render for value in scene.objects} == visibility
    assert not [value for value in bpy.data.objects if value.name.startswith("CAVI Bake")]
    assert not [value for value in bpy.data.materials if value.name.startswith("CAVI Bake")]

    bpy.ops.mesh.primitive_torus_add(major_radius=1, minor_radius=.35,
                                      major_segments=32, minor_segments=12)
    ao_target = bpy.context.object
    ao_target.name = ao_target.data.name = "BakeAO"
    ao = edit("bake_map", map="ao", name="BakeAO", path="ao.png",
              resolution=64, samples=1, margin=2, isolate=True)
    assert ao["map"] == "ao" and ao["selected_to_active"] is False, ao
    deviation, size = variance(root / "ao.png")
    assert size == (64, 64) and deviation > 0.001, (deviation, size)

    curvature = edit("bake_map", map="curvature", name="BakeAO", path="curvature.png",
                     resolution=64, samples=1, margin=2)
    assert curvature["map"] == "curvature"
    deviation, size = variance(root / "curvature.png")
    assert size == (64, 64) and deviation > 0.001, (deviation, size)

    bpy.ops.object.light_add(type="POINT", location=(3, -3, 4))
    light = bpy.context.object
    light.data.energy = 1000
    lightmap = edit("bake_map", map="lightmap", name="BakeLow", path="lightmap.png",
                    resolution=64, samples=4, margin=2, isolate=True)
    assert lightmap["map"] == "lightmap"
    deviation, size = variance(root / "lightmap.png")
    assert size == (64, 64) and deviation > 0.001, (deviation, size)

    bpy.ops.mesh.primitive_cube_add(location=(5, 0, 0))
    no_uv = bpy.context.object
    no_uv.name = "BakeNoUV"
    for layer in list(no_uv.data.uv_layers):
        no_uv.data.uv_layers.remove(layer)
    refused("bake_map", "UV layer", map="ao", name="BakeNoUV", path="bad-uv.png")
    refused("bake_map", "overwrite", map="ao", name="BakeAO", path="ao.png")
    low.modifiers.new("Bevel", "BEVEL")
    refused("bake_map", "modifiers", map="ao", name="BakeLow", path="bad-mod2.png")
    low.modifiers.clear()
    low.shape_key_add(name="Basis")
    refused("bake_map", "shape keys", map="ao", name="BakeLow", path="bad-shape.png")
    low.shape_key_clear()
    refused("bake_map", "does not exist", map="normal", name="BakeLow",
            path="bad-high.png", high=["Missing"])
    try:
        bridge.dispatch("bake_map", {"map": "ao", "name": "BakeAO", "path": "unowned.png",
                                     "resolution": 64})
        raise AssertionError("Unowned bake succeeded")
    except RuntimeError as exc:
        assert "lease_id" in str(exc)

    print(json.dumps({
        "normal": [normal["resolution"], round(deviation, 4)],
        "ao_bytes": ao["bytes"],
        "curvature_bytes": curvature["bytes"],
        "lightmap_bytes": lightmap["bytes"],
        "normal_sha": normal["sha256"][:12],
        "state_restored": True,
    }))
finally:
    folder.cleanup()
