"""Native AAA geometry checks: reduction, LODs, UVs, collision, transforms, exports, sheets."""

import itertools
import json
import math
import sys
import tempfile
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

folder = tempfile.TemporaryDirectory()
bridge._workspace = Path(folder.name).resolve()
state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "aaa-fixture", "expected_project": state["project_id"]})["lease_id"]
results = {}


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


def sphere(name, segments=48, rings=24, location=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=1,
                              calc_uvs=True)
    mesh = bpy.data.meshes.new(name)
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")
    bm.loops.layers.uv.verify()
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(bpy.data.materials.get("Rock") or bpy.data.materials.new("Rock"))
    value = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(value)
    value.location = location
    return value


def tris(value):
    return sum(len(p.vertices) - 2 for p in value.data.polygons)


def world(value):
    return sorted(tuple(round(c, 4) for c in value.matrix_world @ v.co)
                  for v in value.data.vertices)


try:
    bridge.dispatch("owned_edit", {"operation": "decimate_to", "params": {
        "name": "Cube", "target_triangles": 6}})
    raise AssertionError("Unowned decimate succeeded")
except RuntimeError as exc:
    assert "lease_id" in str(exc)

# decimate_to keeps UVs and materials, hits the target.
rock = sphere("SM_Rock")
before = tris(rock)
result = edit("decimate_to", name="SM_Rock", target_triangles=800, preserve_seams=True)
assert result["triangles"] <= 800 * 1.05 and result["triangles"] == tris(rock), result
assert result["triangles_before"] == before
assert rock.data.uv_layers and rock.data.materials[0].name == "Rock"
assert not rock.vertex_groups and not rock.modifiers
edit("decimate_to", name="SM_Rock", amount=0.5, symmetry_axis="X", preserve_seams=False)
refused("decimate_to", "exactly one", name="SM_Rock")
refused("decimate_to", "exactly one", name="SM_Rock", target_triangles=10, amount=0.5)
shared = bpy.data.objects.new("SharedRock", rock.data)
bpy.context.scene.collection.objects.link(shared)
refused("decimate_to", "shared", name="SM_Rock", target_triangles=100)
bpy.data.objects.remove(shared)
results["decimate_to"] = result["triangles"]

# lod_chain copies by default and reports triangles per level.
tree = sphere("SM_Tree", location=(4, 0, 0))
lods = edit("lod_chain", name="SM_Tree")
levels = [entry["triangles"] for entry in lods["levels"]]
assert [e["name"] for e in lods["levels"]] == [f"SM_Tree_LOD{i}" for i in range(4)]
assert all(b < a for a, b in itertools.pairwise(levels)), levels
assert lods["collection"] == "SM_Tree_LODs" and not lods["source_renamed"]
assert bpy.data.objects["SM_Tree"].name == "SM_Tree"
collection = bpy.data.collections["SM_Tree_LODs"]
assert {o.name for o in collection.objects} == {f"SM_Tree_LOD{i}" for i in range(4)}
lod2 = bpy.data.objects["SM_Tree_LOD2"]
assert lod2.data.uv_layers and lod2.material_slots[0].material.name == "Rock"
refused("lod_chain", "already exists", name="SM_Tree")
bush = sphere("SM_Bush", location=(8, 0, 0))
count = tris(bush)
renamed = edit("lod_chain", name="SM_Bush", rename_source=True,
               triangle_targets=[count // 2, count // 8])
assert renamed["source_renamed"] and bush.name == "SM_Bush_LOD0" and bush.data.name == "SM_Bush_LOD0"
refused("lod_chain", "strictly decrease", name="SM_Rock", triangle_targets=[10, 50])
results["lod_chain"] = levels

# QuadriFlow runs in background on manifold meshes and refuses open ones.
blob = sphere("Blob", location=(0, 4, 0))
quad = edit("remesh_quad", name="Blob", target_faces=600, preserve_sharp=False,
            preserve_boundary=True)
assert quad["quad_ratio"] > 0.9 and 300 <= quad["faces"] <= 1200, quad
bpy.ops.mesh.primitive_grid_add(x_subdivisions=4, y_subdivisions=4, location=(0, 8, 0))
bpy.context.object.name = "OpenGrid"
try:
    edit("remesh_quad", name="OpenGrid", target_faces=100)
    results["remesh_quad_open"] = "accepted"
except (RuntimeError, ValueError) as exc:
    results["remesh_quad_open"] = str(exc)
results["remesh_quad"] = quad["faces"]

# Lightmap UV: separate layer, render-active preserved, no overlaps.
bpy.ops.mesh.primitive_cube_add(location=(0, -4, 0))
crate = bpy.context.object
crate.name = crate.data.name = "SM_Crate"
lightmap = edit("lightmap_uv", name="SM_Crate", lightmap_resolution=128, margin_px=4)
layers = crate.data.uv_layers
assert lightmap["created"] and "UVMap_Lightmap" in layers
assert next(x for x in layers if x.active_render).name == "UVMap"
assert layers.active.name == "UVMap"
assert lightmap["overlap_ratio"] == 0 and lightmap["coverage_ratio"] > 0.2, lightmap
again = edit("lightmap_uv", name="SM_Crate", lightmap_resolution=64)
assert not again["created"] and len(layers) == 2
refused("lightmap_uv", "too large", name="SM_Crate", lightmap_resolution=16, margin_px=8)
results["lightmap_overlap_ratio"] = lightmap["overlap_ratio"]

# Texel density: 2 m plane mapped 0-1 at 1024 px is 512 px/m.
mesh = bpy.data.meshes.new("SM_Floor")
mesh.from_pydata([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)], [], [(0, 1, 2, 3)])
uv = mesh.uv_layers.new(name="UVMap")
for loop, point in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)]):
    loop.uv = point
floor = bpy.data.objects.new("SM_Floor", mesh)
bpy.context.scene.collection.objects.link(floor)
density = edit("texel_density", name="SM_Floor", target_px_per_m=256, texture_resolution=1024)
assert abs(density["density_before"] - 512) < 1e-6
assert abs(density["density_after"] - 256) < 1e-6 and density["fits_unit_square"], density
inspected = bridge.dispatch("inspect_mesh_quality", {"names": ["SM_Floor"]})
assert abs(inspected["objects"][0]["mapping"]["density_area_weighted"] - 256) < 1e-6
packed = edit("texel_density", name="SM_Floor", target_px_per_m=128, texture_resolution=1024,
              pack=True)
assert abs(packed["density_after"] - 128) < 1e-3, packed
results["texel_density"] = [density["density_before"], density["density_after"]]

# Collision: convex hull per loose part, primitives, hull vertex cap.
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1)
bmesh.ops.create_cube(bm, size=1, matrix=Matrix.Translation((3, 0, 0)))
parts = bpy.data.meshes.new("SM_Fence")
bm.to_mesh(parts)
bm.free()
fence = bpy.data.objects.new("SM_Fence", parts)
bpy.context.scene.collection.objects.link(fence)
fence.location = (0, 0, 5)
hulls = edit("collision", name="SM_Fence", shape="convex", max_hull_vertices=32)
assert hulls["count"] == 2 and [o["name"] for o in hulls["objects"]] == [
    "UCX_SM_Fence_00", "UCX_SM_Fence_01"]
ucx = bpy.data.objects["UCX_SM_Fence_00"]
assert ucx.parent is None and ucx.matrix_world == fence.matrix_world
assert len(ucx.data.vertices) == 8
refused("collision", "already exists", name="SM_Fence", shape="box")
capped = edit("collision", name="SM_Rock", max_hull_vertices=16)
assert capped["objects"][0]["vertices"] <= 16, capped
boxes = edit("collision", name="SM_Crate", shape="box")
assert boxes["objects"][0]["name"] == "UBX_SM_Crate_00"
balls = edit("collision", name="Blob", shape="sphere")
assert balls["objects"][0]["name"] == "USP_Blob_00"
results["collision"] = {"convex": hulls["count"], "capped_vertices": capped["objects"][0][
    "vertices"]}

# Cleanup: merges, loose geometry, flipped face, triangulation, custom normals.
dirty = bpy.data.meshes.new("Dirty")
dirty.from_pydata(
    [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
     (1, 1, 1.00001), (5, 5, 5)],
    [],
    [(3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 8, 5), (2, 3, 7, 6), (0, 4, 7, 3)])
dirty.normals_split_custom_set_from_vertices([(0, 0, 1)] * 10)
dirty_obj = bpy.data.objects.new("Dirty", dirty)
bpy.context.scene.collection.objects.link(dirty_obj)
dirty_obj.data.polygons[1].flip()
clean = edit("cleanup_mesh", name="Dirty", merge_distance=0.001,
             steps=["merge", "delete_loose", "recalc_normals", "triangulate",
                    "clear_custom_normals"])
assert clean["merged_vertices"] == 1 and clean["loose_removed"] == 1, clean
assert clean["flipped_faces"] >= 1 and clean["after"]["faces"] == 12, clean
assert clean["custom_normals_cleared"] and not dirty.has_custom_normals
refused("cleanup_mesh", "steps", name="Dirty", steps=["explode"])
results["cleanup"] = clean["delta"]

# apply_transforms preserves world geometry and children.
bpy.ops.mesh.primitive_cube_add(location=(2, 3, 4), rotation=(0, 0, math.radians(30)))
box = bpy.context.object
box.scale = (2, 1, -1)
box.name = box.data.name = "SM_Box"
child = bpy.data.objects.new("Child", None)
bpy.context.scene.collection.objects.link(child)
child.parent = box
child.location = (1, 0, 0)
bpy.context.view_layer.update()
child_world = child.matrix_world.copy()
geometry = world(box)
applied = edit("apply_transforms", name="SM_Box", components=["rotation", "scale"])
bpy.context.view_layer.update()
assert world(box) == geometry and tuple(box.scale) == (1, 1, 1)
assert all(abs(a - b) < 1e-5 for a, b in zip(box.location, (2, 3, 4)))
assert all(abs(child.matrix_world[i][j] - child_world[i][j]) < 1e-5
           for i in range(4) for j in range(4))
box.data.calc_loop_triangles()
center = sum((v.co for v in box.data.vertices), Vector()) / len(box.data.vertices)
assert all(p.normal.dot(p.center - center) > 0 for p in box.data.polygons), "inward normals"
assert applied["applied"] == ["rotation", "scale"]
twin = bpy.data.objects.new("Twin", box.data)
bpy.context.scene.collection.objects.link(twin)
twin.scale = (3, 3, 3)
refused("apply_transforms", "make_single_user", name="Twin", components=["scale"])
edit("apply_transforms", name="Twin", components=["scale"], make_single_user=True)
assert twin.data != box.data and tuple(twin.scale) == (1, 1, 1)

# Origins, grid snapping, rename and sockets.
geometry = world(box)
edit("set_origin", name="SM_Box", origin="bounds_bottom_center")
bpy.context.view_layer.update()
assert world(box) == geometry
low = min(v.co.z for v in box.data.vertices)
assert abs(low) < 1e-6
edit("set_origin", name="SM_Box", origin="point", location=[0, 0, 0])
bpy.context.view_layer.update()
assert world(box) == geometry and box.matrix_world.translation.length < 1e-6
refused("set_origin", "location", name="SM_Box", origin="bounds_center", location=[1, 1, 1])
box.location = (0.26, -0.74, 1.01)
edit("snap_to_grid", name="SM_Box", grid=0.5)
assert all(abs(a - b) < 1e-6 for a, b in zip(box.location, (0.5, -0.5, 1.0)))
edit("rename_object", name="SM_Box", new_name="SM_Crate_B")
assert "SM_Crate_B" in bpy.data.objects and bpy.data.objects["SM_Crate_B"].data.name == "SM_Crate_B"
refused("rename_object", "unique", name="SM_Crate_B", new_name="SM_Rock")
socket = edit("add_socket", name="SM_Crate_B", new_name="Handle", location=[0, 0, 1])
assert socket["name"] == "SOCKET_Handle" and bpy.data.objects["SOCKET_Handle"].parent.name == (
    "SM_Crate_B")
assert tuple(bpy.data.objects["SOCKET_Handle"].location) == (0, 0, 1)

# Inspect checks.
crate.scale = (2, 2, 2)
checks = bridge.dispatch("inspect_mesh_quality", {
    "names": ["SM_Crate", "SM_Tree_LOD1", "UCX_SM_Fence_00", "Dirty"],
    "checks": ["naming", "topology", "lightmap", "transforms", "origin"],
    "naming": {"mesh_prefix": "SM_", "lod_suffix": "_LOD{n}",
               "collision_prefixes": ["UCX_", "UBX_", "USP_"]}})
by = {o["name"]: o["checks"] for o in checks["objects"]}
assert by["SM_Crate"]["lightmap"]["present"] and by["SM_Crate"]["lightmap"]["overlap_ratio"] == 0
assert not by["SM_Crate"]["transforms"]["scale_applied"]
assert by["SM_Crate"]["origin"]["classification"] == "bounds_center"
assert by["SM_Crate"]["topology"]["non_manifold_edges"] == 0
assert by["SM_Tree_LOD1"]["naming"]["role"] == "lod" and by["SM_Tree_LOD1"]["naming"]["lod"] == 1
assert by["UCX_SM_Fence_00"]["naming"] == {"role": "collision", "base": "SM_Fence",
                                           "issues": []}
assert "missing_mesh_prefix" in by["Dirty"]["naming"]["issues"]
assert not by["SM_Tree_LOD1"]["lightmap"]["present"]
crate.scale = (1, 1, 1)
results["inspect_checks"] = by["SM_Crate"]

# Exports: LOD group, collision, USD, axis presets and bake pairs.
exported = edit("export_asset", names=["SM_Tree_LOD0"], path="tree.fbx", lods=True,
                axis="unity")
assert exported["lods"] == [f"SM_Tree_LOD{i}" for i in range(4)], exported
fenced = edit("export_asset", names=["SM_Fence"], path="fence.fbx", collision=True,
              axis="unreal")
assert fenced["collision"] == ["UCX_SM_Fence_00", "UCX_SM_Fence_01"]
refused("export_asset", "collision objects", names=["SM_Floor"], path="floor.fbx",
        collision=True)
refused("export_asset", "LOD0", names=["SM_Floor"], path="floor.fbx", lods=True)
layout = edit("export_asset", names=["SM_Crate", "SM_Fence"], path="layout.usdc", axis="godot")
assert layout["bytes"] > 0
refused("export_asset", "glTF", names=["SM_Crate"], path="crate.glb", axis="unreal")
high = sphere("SM_Crate_high", segments=64, rings=32, location=(0, -4, 0))
pair = edit("export_asset", path="crate.fbx", bake_pair={"high": ["SM_Crate_high"],
                                                          "low": ["SM_Crate"]})
assert pair["low"]["objects"] == ["SM_Crate_low"] and pair["high"]["objects"] == [
    "SM_Crate_high"]
assert crate.name == "SM_Crate" and high.name == "SM_Crate_high" and crate.data.name == "SM_Crate"
refused("export_asset", "same base", path="bad.fbx",
        bake_pair={"high": ["Blob"], "low": ["SM_Crate"]})
refused("export_asset", "overwrite", path="crate.fbx",
        bake_pair={"high": ["SM_Crate_high"], "low": ["SM_Crate"]})
before_import = set(bpy.data.objects)
bpy.ops.import_scene.fbx(filepath=str(bridge._workspace / "crate_low.fbx"))
imported = set(bpy.data.objects) - before_import
assert {o.name for o in imported} == {"SM_Crate_low"}, imported
for item in imported:
    bpy.data.objects.remove(item, do_unlink=True)
before_import = set(bpy.data.objects)
bpy.ops.import_scene.fbx(filepath=str(bridge._workspace / "tree.fbx"))
imported = set(bpy.data.objects) - before_import
assert {o.name.split(".")[0] for o in imported} == {f"SM_Tree_LOD{i}" for i in range(4)}
for item in imported:
    bpy.data.objects.remove(item, do_unlink=True)
results["exports"] = sorted(p.name for p in bridge._workspace.iterdir())

# Review sheets: every mode, no leaked datablocks, scene restored.
pools = ("objects", "meshes", "materials", "images", "cameras")
counts = {k: len(getattr(bpy.data, k)) for k in pools}
hidden = {o.name: o.hide_render for o in bpy.context.scene.objects}
for mode in ("shaded", "wireframe", "uv_checker", "texel_heatmap", "matcap"):
    extra = {"target_px_per_m": 128, "texture_resolution": 1024} if mode == "texel_heatmap" else {}
    sheet = bridge.dispatch("review_sheet", {"path": f"sheet-{mode}.png", "mode": mode,
                                             "names": ["SM_Floor", "SM_Crate"],
                                             "resolution": 384, **extra})
    assert sheet["size"] == [384, 256], sheet
    image = bpy.data.images.load(sheet["path"])
    assert tuple(image.size) == (384, 256)
    pixels = np.empty(384 * 256 * 4, np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(256, 384, 4)
    bpy.data.images.remove(image)
    assert pixels[..., :3].std() > 0.01, mode
    if mode == "texel_heatmap":
        assert sheet["density"]["faces_on_target"] >= 1, sheet
        assert ((pixels[..., 1] > 0.5) & (pixels[..., 0] < 0.3) & (pixels[..., 2] < 0.3)).any()
    results[f"review_{mode}"] = sheet["size"]
assert counts == {k: len(getattr(bpy.data, k)) for k in pools}
assert hidden == {o.name: o.hide_render for o in bpy.context.scene.objects}
single = bridge.dispatch("review_sheet", {"path": "single.png", "views": ["persp"],
                                          "resolution": 256})
assert single["size"] == [256, 256]
try:
    bridge.dispatch("review_sheet", {"path": "bad.png", "mode": "shaded",
                                     "target_px_per_m": 10})
    raise AssertionError("Unrelated review parameter accepted")
except ValueError as exc:
    assert "texel_heatmap" in str(exc)

# Scatter: fixed node group, seeded, bounded, collection recursion refused.
props = bpy.data.collections.new("Props")
bpy.context.scene.collection.children.link(props)
pebble = sphere("Pebble", segments=8, rings=4, location=(50, 0, 0))
for owner in list(pebble.users_collection):
    owner.objects.unlink(pebble)
props.objects.link(pebble)
floor.scale = (5, 5, 1)
bpy.context.view_layer.update()
spread = edit("scatter", name="SM_Floor", collection="Props", density=2, seed=7,
              min_distance=0.2, scale_range=[0.5, 1.5], rotation_jitter_degrees=360)
assert spread["estimated_instances"] == 200 and 50 < spread["instances"] <= 200, spread
assert floor.modifiers[-1].type == "NODES"
again = edit("scatter", name="SM_Floor", collection="Props", density=2, seed=7,
             min_distance=0.2, scale_range=[0.5, 1.5])
flat = edit("scatter", name="SM_Crate", collection="Props", density=1, realize=True)
assert flat["evaluated_triangles"] > tris(crate), flat
refused("scatter", "budget", name="SM_Floor", collection="Props", density=10000)
refused("scatter", "inside", name="Pebble", collection="Props", density=1)
refused("scatter", "does not exist", name="SM_Floor", collection="Missing", density=1)
results["scatter"] = [spread["instances"], again["instances"], flat["evaluated_triangles"]]
print(json.dumps(results, default=str))
