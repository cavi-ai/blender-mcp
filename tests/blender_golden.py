"""Golden-asset regressions: hulls with interior points, lightmap speed, LOD honesty, sheet size."""

import json
import random
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import bmesh
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp import blender_geometry

folder = tempfile.TemporaryDirectory()
bridge._workspace = Path(folder.name).resolve()
state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "golden-fixture", "expected_project": state["project_id"]})["lease_id"]
results = {}


def edit(operation, **params):
    return bridge.dispatch("owned_edit", {"operation": operation,
                                          "params": {**params, "lease_id": lease}})


def make(name, build, uv=False):
    bm = bmesh.new()
    build(bm)
    mesh = bpy.data.meshes.new(name)
    if uv:
        mesh.uv_layers.new(name="UVMap")
    bm.to_mesh(mesh)
    bm.free()
    value = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(value)
    return value


def subdivided_sphere(bm):
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=2, use_grid_fill=True)


def rock(bm):
    rng = random.Random(7)
    bmesh.ops.create_icosphere(bm, subdivisions=4, radius=1)
    for vert in bm.verts:
        vert.co *= 1 + 0.3 * rng.random()


def assert_convex_hull(value, limit):
    mesh = value.data
    assert 4 <= len(mesh.vertices) <= limit, len(mesh.vertices)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    try:
        assert all(edge.is_manifold for edge in bm.edges)
        assert not any(vert for vert in bm.verts if not vert.link_faces)
        bm.normal_update()
        co = np.array([vert.co[:] for vert in bm.verts])
        center = co.mean(axis=0)
        for face in bm.faces:
            normal, point = np.array(face.normal[:]), np.array(face.verts[0].co[:])
            if normal @ (center - point) > 0:
                normal = -normal
            assert ((co - point) @ normal).max() <= 1e-5, "hull is not convex"
    finally:
        bm.free()


# Convex hulls of meshes with interior points.
for name, build in (("SM_SubSphere", subdivided_sphere), ("SM_Rock", rock)):
    make(name, build, uv=True)
for name, extra in (("SM_SubSphere", {}), ("SM_Rock", {"target_triangles": 300})):
    if extra:
        edit("decimate_to", name=name, **extra)
    hulls = edit("collision", name=name, shape="convex", max_hull_vertices=24)
    entry = hulls["objects"][0]
    assert hulls["count"] == 1 and not entry["box_fallback"], hulls
    assert_convex_hull(bpy.data.objects[entry["name"]], 24)
    results[f"hull_{name}"] = entry["vertices"]


# Lightmap packing stays fast, non-overlapping and inside the margin.
def wall(bm):
    bmesh.ops.create_cube(bm, size=1)
    bmesh.ops.scale(bm, vec=(4, 0.2, 3), verts=bm.verts)


def dense(bm):
    bmesh.ops.create_uvsphere(bm, u_segments=100, v_segments=100, radius=1)


timings = {}
for name, build, budget in (("SM_Wall", wall, 2), ("SM_Dense", dense, 10)):
    value = make(name, build)
    start = time.perf_counter()
    result = edit("lightmap_uv", name=name, lightmap_resolution=64, margin_px=4)
    timings[name] = round(time.perf_counter() - start, 3)
    assert timings[name] < budget, timings
    assert result["overlap_ratio"] == 0 and result["coverage_ratio"] > 0.2, result
    uv = np.empty(len(value.data.loops) * 2)
    value.data.uv_layers["UVMap_Lightmap"].data.foreach_get("uv", uv)
    assert uv.min() >= result["margin_uv"] - 1e-6 and uv.max() <= 1 - result["margin_uv"] + 1e-6
results["lightmap_seconds"] = timings


# LOD and decimation relax preservation instead of silently missing targets.
def seamed_cone(bm):
    bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=1, radius2=0, depth=2,
                          calc_uvs=True)
    for edge in bm.edges:
        edge.seam = True


make("SM_Cone", seamed_cone, uv=True)
lods = edit("lod_chain", name="SM_Cone", triangle_targets=[30, 15], preserve_seams=True)
for level in lods["levels"][1:]:
    assert level["achieved"] <= level["target"] * 1.1, lods
    assert level["relaxed"] and level["preservation"] != "seams", level
    mesh = bpy.data.objects[level["name"]].data
    assert level["achieved"] == sum(len(p.vertices) - 2 for p in mesh.polygons), level
assert lods["warnings"] == [], lods
make("SM_Cone2", seamed_cone, uv=True)
reduced = edit("decimate_to", name="SM_Cone2", target_triangles=30)
assert reduced["achieved"] <= 33 and reduced["relaxed"] and reduced["warnings"] == [], reduced
make("SM_Kept", seamed_cone, uv=True)
with patch.object(blender_geometry, "collapse", lambda *args: None):
    stuck = edit("decimate_to", name="SM_Kept", target_triangles=30)
    assert stuck["achieved"] == 62 and stuck["preservation"] == "plain", stuck
    assert len(stuck["warnings"]) == 1 and "SM_Kept" in stuck["warnings"][0], stuck
    stuck_lods = edit("lod_chain", name="SM_Kept", triangle_targets=[30])
    assert len(stuck_lods["warnings"]) == 1, stuck_lods
results["lod_levels"] = [(x["target"], x["achieved"], x["preservation"])
                         for x in lods["levels"][1:]]

# Review sheet width matches the requested resolution.
for views, resolution in ((None, 1024), (["front", "back"], 1023), (["persp"], 300)):
    params = {"path": f"sheet-{resolution}.png", "resolution": resolution,
              "names": ["SM_Wall"], **({"views": views} if views else {})}
    sheet = bridge.dispatch("review_sheet", params)
    image = bpy.data.images.load(sheet["path"])
    size = list(image.size)
    bpy.data.images.remove(image)
    assert sheet["size"] == size and size[0] == resolution, (sheet, size)
    results[f"sheet_{resolution}"] = size

print(json.dumps(results))
