"""Static mesh preparation: reduction, remeshing, LODs, UV layers, collision and cleanup."""

import math
import re

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

from .blender_bridge import editable_mesh, info, number, selected
from .naming import LOD, base_name
from .uvmath import density, overlap

MAX_TRIANGLES = 500000
MAX_UV_TRIANGLES = 200000
MAX_PARTS = 64
SEAM_WEIGHT = 10.0
AXES = {"X", "Y", "Z"}
CLEANUP_STEPS = {"merge", "delete_loose", "recalc_normals", "triangulate",
                 "clear_custom_normals"}


def triangle_count(mesh):
    totals = np.empty(len(mesh.polygons), np.int64)
    mesh.polygons.foreach_get("loop_total", totals)
    return int((totals - 2).sum())


def boolean(p, key, default):
    value = p.get(key, default)
    if type(value) is not bool:
        raise ValueError(f"{key} must be boolean")
    return value


def integer(p, key, default, low, high):
    value = p.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{key} must be an integer from {low} to {high}")
    return value


def layer_name(value, default=None):
    value = default if value is None else value
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > 63:
        raise ValueError("UV layer name must be nonempty and at most 63 UTF-8 bytes")
    return value


def source(name, cap=MAX_TRIANGLES):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before this operation")
    value = editable_mesh(name)
    if value.modifiers or value.data.shape_keys:
        raise ValueError("Requires a mesh without modifiers or shape keys; apply them first")
    if value.name not in bpy.context.view_layer.objects or value.hide_viewport:
        raise ValueError("Object must be visible in the active view layer")
    count = triangle_count(value.data)
    if not 0 < count <= cap:
        raise ValueError(f"Mesh must have 1 to {cap} triangles")
    return value, count


def swap(value, mesh):
    old = value.data
    label = old.name
    value.data = mesh
    bpy.data.meshes.remove(old)
    mesh.name = label


def bake(value, modifier):
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        mesh = bpy.data.meshes.new_from_object(
            value.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph)
    finally:
        value.modifiers.remove(modifier)
    swap(value, mesh)


def seam_vertices(mesh):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        layers = list(bm.loops.layers.uv.values())
        keep = set()
        for edge in bm.edges:
            loops = list(edge.link_loops)
            split = edge.seam or len(loops) != 2
            if not split:
                for layer in layers:
                    first = {loop.vert: loop[layer].uv for loop in (loops[0],
                                                                    loops[0].link_loop_next)}
                    for loop in (loops[1], loops[1].link_loop_next):
                        if (first[loop.vert] - loop[layer].uv).length > 1e-5:
                            split = True
                            break
                    if split:
                        break
            if split:
                keep.update((edge.verts[0].index, edge.verts[1].index))
        return sorted(keep)
    finally:
        bm.free()


def collapse(value, ratio, axis, seams):
    group = None
    if seams:
        keep = seam_vertices(value.data)
        if keep:
            group = value.vertex_groups.new(name="CAVI_Preserve")
            group.add(keep, 1.0, "REPLACE")
    label = group.name if group else None
    try:
        modifier = value.modifiers.new("CAVI Decimate", "DECIMATE")
        modifier.decimate_type = "COLLAPSE"
        modifier.ratio = ratio
        modifier.use_collapse_triangulate = True
        if axis:
            modifier.use_symmetry = True
            modifier.symmetry_axis = axis
        if label:
            # Inverted weights protect seam and boundary vertices from collapse.
            modifier.vertex_group = label
            modifier.invert_vertex_group = True
            modifier.vertex_group_factor = SEAM_WEIGHT
        bake(value, modifier)
    finally:
        if label and value.vertex_groups.get(label):
            value.vertex_groups.remove(value.vertex_groups[label])


def reduce(value, current, target, axis, seams):
    achieved = current
    for _ in range(3):
        if achieved <= target * 1.02:
            break
        collapse(value, min(1.0, max(1e-4, target / achieved)), axis, seams)
        reached = triangle_count(value.data)
        if reached >= achieved:
            break
        achieved = reached
    return achieved


def reduction_target(p, current):
    target, ratio = p.get("target_triangles"), p.get("amount")
    if (target is None) == (ratio is None):
        raise ValueError("Provide exactly one of target_triangles or amount (ratio)")
    if target is not None:
        if type(target) is not int or not 4 <= target <= MAX_TRIANGLES:
            raise ValueError(f"target_triangles must be an integer from 4 to {MAX_TRIANGLES}")
        return target
    return max(4, int(current * number(ratio, 1e-4, 1, "amount")))


def symmetry(p):
    axis = p.get("symmetry_axis")
    if axis is not None and axis not in AXES:
        raise ValueError("symmetry_axis must be X, Y or Z")
    return axis


def decimate_to(p):
    value, before = source(p["name"])
    target = reduction_target(p, before)
    axis, seams = symmetry(p), boolean(p, "preserve_seams", True)
    after = reduce(value, before, target, axis, seams) if target < before else before
    return {**info(value), "triangles_before": before, "triangles_target": target,
            "triangles": after, "preserve_seams": seams, "symmetry_axis": axis}


def remesh_quad(p):
    value, before = source(p["name"], 200000)
    faces = integer(p, "target_faces", None, 16, 100000)
    sharp, boundary = boolean(p, "preserve_sharp", False), boolean(p, "preserve_boundary", True)
    with selected([value]), bpy.context.temp_override(
        object=value, active_object=value, selected_objects=[value],
        selected_editable_objects=[value],
    ):
        result = bpy.ops.object.quadriflow_remesh(
            mode="FACES", target_faces=faces, use_preserve_sharp=sharp,
            use_preserve_boundary=boundary, use_mesh_symmetry=False, smooth_normals=False,
            seed=0)
    if "FINISHED" not in result:
        raise RuntimeError("QuadriFlow did not finish; the mesh must be manifold")
    mesh = value.data
    quads = sum(len(face.vertices) == 4 for face in mesh.polygons)
    return {**info(value), "triangles_before": before, "faces_target": faces,
            "faces": len(mesh.polygons), "quad_ratio": quads / max(1, len(mesh.polygons)),
            "triangles": triangle_count(mesh), "uv_layers": len(mesh.uv_layers)}


def free_name(label):
    if len(label.encode()) > 63:
        raise ValueError(f"{label} exceeds 63 bytes")
    if label in bpy.data.objects:
        raise ValueError(f"{label} already exists")
    return label


def lod_chain(p):
    value, count = source(p["name"])
    ratios, targets = p.get("ratios"), p.get("triangle_targets")
    if ratios is not None and targets is not None:
        raise ValueError("Provide ratios or triangle_targets, not both")
    levels = targets if targets is not None else ratios or [0.5, 0.25, 0.125]
    if not isinstance(levels, list) or not 1 <= len(levels) <= 6:
        raise ValueError("Provide 1 to 6 LOD levels")
    if targets is not None:
        if any(type(t) is not int or t < 4 for t in targets):
            raise ValueError("triangle_targets must be integers of at least 4")
        goals = list(targets)
    else:
        goals = [max(4, int(count * number(r, 1e-4, 0.999, "ratios"))) for r in levels]
    if any(b >= a for a, b in zip([count, *goals], goals)):
        raise ValueError("LOD targets must strictly decrease below LOD0")
    rename = boolean(p, "rename_source", False)
    axis, seams = symmetry(p), boolean(p, "preserve_seams", True)
    if LOD.search(value.name):
        if not value.name.endswith("_LOD0"):
            raise ValueError("Source must be LOD0")
        base = base_name(value.name)
    else:
        base = value.name
    names = [free_name(f"{base}_LOD{i}") for i in range(1, len(goals) + 1)]
    lod0_name = f"{base}_LOD0"
    if value.name != lod0_name:
        free_name(lod0_name)
    collection_name = f"{base}_LODs"
    if collection_name in bpy.data.collections:
        raise ValueError(f"Collection {collection_name} already exists")
    parent = value.users_collection[0] if value.users_collection else bpy.context.scene.collection
    created, original = [], (value.name, value.data.name, list(value.users_collection))
    collection = bpy.data.collections.new(collection_name)
    try:
        parent.children.link(collection)
        if value.name == lod0_name or rename:
            lod0 = value
            value.name = lod0_name
            value.data.name = lod0_name
            for owner in list(value.users_collection):
                owner.objects.unlink(value)
        else:
            lod0 = value.copy()
            lod0.data = value.data.copy()
            lod0.name = lod0.data.name = lod0_name
            created.append(lod0)
        collection.objects.link(lod0)
        report = [{"name": lod0.name, "level": 0, "triangles": count}]
        for level, (label, goal) in enumerate(zip(names, goals), start=1):
            copy = lod0.copy()
            copy.data = lod0.data.copy()
            copy.name = copy.data.name = label
            created.append(copy)
            collection.objects.link(copy)
            reached = reduce(copy, count, goal, axis, seams)
            report.append({"name": copy.name, "level": level, "triangles_target": goal,
                           "triangles": reached})
    except Exception:
        for item in created:
            mesh = item.data
            bpy.data.objects.remove(item, do_unlink=True)
            bpy.data.meshes.remove(mesh)
        if value.name in collection.objects:
            collection.objects.unlink(value)
        value.name, value.data.name = original[0], original[1]
        for owner in original[2]:
            if value.name not in owner.objects:
                owner.objects.link(value)
        bpy.data.collections.remove(collection)
        raise
    return {"collection": collection.name, "base": base, "levels": report,
            "source_renamed": lod0 is value and original[0] != lod0.name}


def uv_triangles(mesh, layer):
    mesh.calc_loop_triangles()
    loops = np.empty(len(mesh.loop_triangles) * 3, np.int64)
    mesh.loop_triangles.foreach_get("loops", loops)
    uv = np.empty(len(mesh.loops) * 2, np.float64)
    layer.data.foreach_get("uv", uv)
    return uv.reshape(-1, 2)[loops].reshape(-1, 3, 2)


def world_triangles(value, unit):
    mesh = value.data
    mesh.calc_loop_triangles()
    verts = np.empty(len(mesh.loop_triangles) * 3, np.int64)
    mesh.loop_triangles.foreach_get("vertices", verts)
    co = np.empty(len(mesh.vertices) * 3, np.float64)
    mesh.vertices.foreach_get("co", co)
    matrix = np.array(value.matrix_world, np.float64)
    co = co.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
    return (co * unit)[verts].reshape(-1, 3, 3)


def unit_scale():
    units = bpy.context.scene.unit_settings
    scale = 1.0 if units.system == "NONE" else units.scale_length
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Scene unit scale must be positive and finite")
    return scale


def uv_overlap(mesh, layer, resolution):
    return overlap(uv_triangles(mesh, layer), resolution)


def edit_uvs(value, layer, steps):
    layers = value.data.uv_layers
    previous = layers.active.name if layers.active else None
    render = next((x.name for x in layers if x.active_render), None)
    try:
        layers.active = layers[layer]
        with selected([value]):
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            for step in steps:
                if "FINISHED" not in step():
                    raise RuntimeError("UV operation did not finish")
    finally:
        # Edit Mode reallocates layers; look them up by name.
        layers = value.data.uv_layers
        if previous in layers:
            layers.active = layers[previous]
        if render in layers:
            layers[render].active_render = True


def lightmap_uv(p):
    value, _ = source(p["name"], MAX_UV_TRIANGLES)
    label = layer_name(p.get("uv_layer"), "UVMap_Lightmap")
    resolution = integer(p, "lightmap_resolution", 64, 16, 4096)
    margin_px = number(p.get("margin_px", 4), 0, 64, "margin_px")
    angle = number(p.get("angle_limit_degrees", 66), 1, 89, "angle_limit_degrees")
    margin = margin_px / resolution
    if margin >= 0.25:
        raise ValueError("margin_px is too large for lightmap_resolution")
    layers = value.data.uv_layers
    created = layers.get(label) is None
    if created and len(layers) >= 8:
        raise ValueError("Mesh already has the maximum of 8 UV layers")
    render = next((x.name for x in layers if x.active_render), None)
    if created:
        layers.new(name=label)
    if render is not None:
        layers[render].active_render = True
    try:
        edit_uvs(value, label, [
            lambda: bpy.ops.uv.smart_project(angle_limit=math.radians(angle), island_margin=margin,
                                             margin_method="FRACTION", rotate_method="AXIS_ALIGNED"),
            lambda: bpy.ops.uv.select_all(action="SELECT"),
            lambda: bpy.ops.uv.pack_islands(margin=margin, margin_method="FRACTION", rotate=True,
                                            scale=True, shape_method="CONCAVE"),
        ])
    except Exception:
        layers = value.data.uv_layers
        if created and label in layers:
            layers.remove(layers[label])
        raise
    check = uv_overlap(value.data, value.data.uv_layers[label], resolution)
    return {**info(value), "uv_layer": label, "created": created,
            "lightmap_resolution": resolution, "margin_uv": margin, **check}


def texel_density(p):
    value, _ = source(p["name"], MAX_UV_TRIANGLES)
    target = number(p.get("target_px_per_m"), 0.01, 100000, "target_px_per_m")
    size = integer(p, "texture_resolution", 1024, 1, 4096)
    pack = boolean(p, "pack", False)
    layers = value.data.uv_layers
    requested = p.get("uv_layer")
    layer = (layers.get(layer_name(requested)) if requested is not None
             else next((x for x in layers if x.active_render), layers.active))
    if layer is None:
        raise ValueError("UV layer does not exist; unwrap first")
    unit = unit_scale()
    points = world_triangles(value, unit)
    before = density(points, uv_triangles(value.data, layer), (size, size))
    if before is None:
        raise ValueError("Mesh has no mapped area in this UV layer")
    factor = target / before
    uv = np.empty(len(value.data.loops) * 2, np.float64)
    layer.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    center = (uv.min(axis=0) + uv.max(axis=0)) / 2
    uv = center + (uv - center) * factor
    if np.abs(uv).max() > 1e5:
        raise ValueError("Scaled UVs exceed a bounded range")
    layer.data.foreach_set("uv", uv.ravel())
    value.data.update()
    label = layer.name
    if pack:
        edit_uvs(value, label, [
            lambda: bpy.ops.uv.select_all(action="SELECT"),
            lambda: bpy.ops.uv.pack_islands(margin=0.002, margin_method="FRACTION", rotate=True,
                                            scale=False, shape_method="CONCAVE"),
        ])
        layer = value.data.uv_layers[label]
    after = density(points, uv_triangles(value.data, layer), (size, size))
    layer.data.foreach_get("uv", uv.ravel())
    low, high = uv.min(axis=0), uv.max(axis=0)
    return {**info(value), "uv_layer": layer.name, "texture_resolution": size,
            "target_px_per_m": target, "density_before": before, "density_after": after,
            "scale_factor": factor, "packed": pack,
            "uv_bounds": {"min": low.tolist(), "max": high.tolist()},
            "fits_unit_square": bool(low.min() >= -1e-6 and high.max() <= 1 + 1e-6)}


def loose_parts(mesh):
    count = len(mesh.vertices)
    edges = np.empty(len(mesh.edges) * 2, np.int64)
    mesh.edges.foreach_get("vertices", edges)
    parent = list(range(count))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in edges.reshape(-1, 2).tolist():
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[ra] = rb
    used = np.zeros(count, bool)
    used[edges] = True
    groups = {}
    for index in np.nonzero(used)[0].tolist():
        groups.setdefault(root(index), []).append(index)
    return list(groups.values())


def farthest(points, limit):
    chosen = [0]
    distance = np.linalg.norm(points - points[0], axis=1)
    while len(chosen) < limit:
        index = int(distance.argmax())
        if distance[index] <= 0:
            break
        chosen.append(index)
        distance = np.minimum(distance, np.linalg.norm(points - points[index], axis=1))
    return points[chosen]


def hull(points, limit):
    for _ in range(2):
        bm = bmesh.new()
        try:
            verts = [bm.verts.new(point) for point in points.tolist()]
            result = bmesh.ops.convex_hull(bm, input=verts)
            extra = [v for v in result["geom_interior"] + result["geom_unused"]
                     if isinstance(v, bmesh.types.BMVert)]
            bmesh.ops.delete(bm, geom=extra, context="VERTS")
            if len(bm.faces) < 4:
                return None
            kept = np.array([v.co[:] for v in bm.verts])
            if len(kept) <= limit:
                mesh = bpy.data.meshes.new("CAVI Hull")
                bm.to_mesh(mesh)
                return mesh
            points = farthest(kept, limit)
        finally:
            bm.free()
    return None


def box(low, high):
    low = np.minimum(low, high - 1e-4)
    corners = [(x, y, z) for z in (low[2], high[2]) for y in (low[1], high[1])
               for x in (low[0], high[0])]
    mesh = bpy.data.meshes.new("CAVI Box")
    mesh.from_pydata(corners, [], [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3),
                                   (0, 4, 6, 2), (1, 3, 7, 5)])
    return mesh


def sphere(center, radius):
    bm = bmesh.new()
    try:
        bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=max(radius, 1e-4),
                                  matrix=Matrix.Translation(Vector(center)))
        mesh = bpy.data.meshes.new("CAVI Sphere")
        bm.to_mesh(mesh)
        return mesh
    finally:
        bm.free()


def collision(p):
    value, _ = source(p["name"], 200000)
    shape = p.get("shape", "convex")
    if shape not in {"convex", "box", "sphere"}:
        raise ValueError("shape must be convex, box or sphere")
    limit = integer(p, "max_hull_vertices", 32, 4, 255)
    prefix = {"convex": "UCX_", "box": "UBX_", "sphere": "USP_"}[shape]
    base = base_name(value.name)
    pattern = re.compile(r"^(UCX|UBX|USP)_" + re.escape(base) + r"_\d+$")
    if any(pattern.match(item.name) for item in bpy.data.objects):
        raise ValueError(f"Collision for {base} already exists; remove it first")
    parts = loose_parts(value.data)
    if not 1 <= len(parts) <= MAX_PARTS:
        raise ValueError(f"Collision supports 1 to {MAX_PARTS} loose parts")
    co = np.empty(len(value.data.vertices) * 3, np.float64)
    value.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    owners = value.users_collection or [bpy.context.scene.collection]
    created, report = [], []
    try:
        for index, part in enumerate(parts):
            points = co[part]
            low, high = points.min(axis=0), points.max(axis=0)
            fallback = False
            if shape == "convex":
                mesh = hull(points, limit)
                if mesh is None:
                    mesh, fallback = box(low, high), True
            elif shape == "box":
                mesh = box(low, high)
            else:
                center = (low + high) / 2
                mesh = sphere(center, float(np.linalg.norm(points - center, axis=1).max()))
            label = free_name(f"{prefix}{base}_{index:02}")
            mesh.name = label
            item = bpy.data.objects.new(label, mesh)
            created.append(item)
            owners[0].objects.link(item)
            item.matrix_world = value.matrix_world.copy()
            item.display_type = "WIRE"
            item.hide_render = True
            report.append({"name": label, "vertices": len(mesh.vertices),
                           "faces": len(mesh.polygons), "box_fallback": fallback})
    except Exception:
        for item in created:
            mesh = item.data
            bpy.data.objects.remove(item, do_unlink=True)
            bpy.data.meshes.remove(mesh)
        raise
    scale = value.matrix_world.to_scale()
    return {"source": value.name, "shape": shape, "count": len(report), "objects": report,
            "uniform_scale": bool(max(scale) - min(scale) <= 1e-5 * max(scale))}


def counts(bm):
    return {"vertices": len(bm.verts), "edges": len(bm.edges), "faces": len(bm.faces),
            "triangles": sum(len(f.verts) - 2 for f in bm.faces)}


def cleanup(p):
    value, _ = source(p["name"])
    distance = number(p.get("merge_distance", 0.0001), 0, 1, "merge_distance")
    steps = p.get("steps", ["merge", "delete_loose", "recalc_normals"])
    if (not isinstance(steps, list) or len(set(steps)) != len(steps)
            or not set(steps) <= CLEANUP_STEPS):
        raise ValueError(f"steps must be unique entries from {sorted(CLEANUP_STEPS)}")
    loose, normals = "delete_loose" in steps, "recalc_normals" in steps
    triangulate, clear = "triangulate" in steps, "clear_custom_normals" in steps
    if "merge" not in steps:
        distance = 0
    mesh = value.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        before = counts(bm)
        merged = 0
        if distance > 0:
            count = len(bm.verts)
            bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=distance)
            merged = count - len(bm.verts)
        removed = 0
        if loose:
            count = len(bm.verts) + len(bm.edges)
            bmesh.ops.delete(bm, geom=[e for e in bm.edges if not e.link_faces], context="EDGES")
            bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_edges], context="VERTS")
            removed = count - len(bm.verts) - len(bm.edges)
        flipped = 0
        if normals:
            bm.normal_update()
            previous = [f.normal.copy() for f in bm.faces]
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            bm.normal_update()
            flipped = sum(f.normal.dot(n) < 0 for f, n in zip(bm.faces, previous))
        if triangulate:
            bmesh.ops.triangulate(bm, faces=list(bm.faces), quad_method="BEAUTY",
                                  ngon_method="BEAUTY")
        after = counts(bm)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    custom = mesh.attributes.get("custom_normal")
    cleared = bool(clear and custom is not None)
    if cleared:
        mesh.attributes.remove(custom)
    mesh.update()
    return {**info(value), "before": before, "after": after,
            "delta": {k: after[k] - before[k] for k in after}, "merged_vertices": merged,
            "loose_removed": removed, "flipped_faces": flipped, "steps": steps,
            "custom_normals_cleared": cleared}


HANDLERS = {"decimate_to": decimate_to, "remesh_quad": remesh_quad, "lod_chain": lod_chain,
            "lightmap_uv": lightmap_uv, "texel_density": texel_density,
            "collision": collision, "cleanup_mesh": cleanup}
