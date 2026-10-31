"""Multi-mesh composition: booleans, joins, splits, mirrors, arrays and shells."""

import bmesh
import bpy

from .blender_bridge import info, number, selected, vector
from .blender_geometry import MAX_TRIANGLES, bake, free_name, loose_parts, source, triangle_count

MAX_JOIN_OBJECTS = 64
MAX_PARTS = 64
MAX_ARRAY_COUNT = 1000


def flag(p, key, default):
    value = p.get(key, default)
    if type(value) is not bool:
        raise ValueError(f"{key} must be boolean")
    return value


def checked(value, cap, label):
    count = triangle_count(value.data)
    if not 0 < count <= cap:
        raise ValueError(f"{label} must have 1 to {cap} triangles")
    return count


def restore(value, snapshot, changed):
    if changed:
        current = value.data
        value.data = snapshot
        bpy.data.meshes.remove(current)
    else:
        bpy.data.meshes.remove(snapshot)


def boolean_mesh(p):
    target, target_count = source(p.get("name"))
    operand, operand_count = source(p.get("operand"))
    if operand == target:
        raise ValueError("Boolean operand must be another object")
    if target_count + operand_count > MAX_TRIANGLES:
        raise ValueError(f"Boolean inputs exceed {MAX_TRIANGLES} triangles")
    operation = p.get("operation")
    if operation not in {"union", "difference", "intersect"}:
        raise ValueError("operation must be union, difference or intersect")
    solver = p.get("solver", "exact")
    if solver not in {"exact", "fast"}:
        raise ValueError("solver must be exact or fast")
    self_intersection = flag(p, "self_intersection", False)
    if self_intersection and solver != "exact":
        raise ValueError("self_intersection requires the exact solver")
    keep = flag(p, "keep_operand", False)
    snapshot = target.data.copy()
    changed = False
    try:
        modifier = target.modifiers.new("CAVI Boolean", "BOOLEAN")
        modifier.operation = operation.upper()
        modifier.object = operand
        modifier.solver = "EXACT" if solver == "exact" else "FLOAT"
        modifier.use_self = self_intersection
        modifier.use_hole_tolerant = solver == "exact"
        if hasattr(modifier, "material_mode"):
            modifier.material_mode = "TRANSFER"
        bake(target, modifier)
        changed = True
        if not target.data.polygons:
            raise RuntimeError("Boolean produced no faces")
        after = checked(target, MAX_TRIANGLES, "Boolean result")
    except Exception:
        restore(target, snapshot, changed)
        raise
    bpy.data.meshes.remove(snapshot)
    operand_name = operand.name
    if not keep:
        mesh = operand.data
        bpy.data.objects.remove(operand, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    return {**info(target), "operation": operation, "solver": solver,
            "operand": operand_name, "operand_kept": keep,
            "triangles_before": target_count + operand_count, "triangles": after}


def join_meshes(p):
    target, target_count = source(p.get("name"))
    names = p.get("names")
    if (not isinstance(names, list) or not 1 <= len(names) <= MAX_JOIN_OBJECTS
            or len(set(names)) != len(names)):
        raise ValueError(f"names must list 1 to {MAX_JOIN_OBJECTS} unique objects")
    if target.name in names:
        raise ValueError("join names must not include the target")
    sources = [source(name) for name in names]
    total = target_count + sum(count for _, count in sources)
    if total > MAX_TRIANGLES:
        raise ValueError(f"Joined mesh would exceed {MAX_TRIANGLES} triangles")
    holder = (target.users_collection or [bpy.context.scene.collection])[0]
    copies = []
    try:
        target_copy = target.copy()
        target_copy.data = target.data.copy()
        holder.objects.link(target_copy)
        copies.append(target_copy)
        for value, _ in sources:
            copy = value.copy()
            copy.data = value.data.copy()
            (value.users_collection or [bpy.context.scene.collection])[0].objects.link(copy)
            copies.append(copy)
        with selected(copies):
            result = bpy.ops.object.join()
        if "FINISHED" not in result:
            raise RuntimeError("Blender did not finish joining the meshes")
        joined = target_copy.data
        checked(target_copy, MAX_TRIANGLES, "Joined mesh")
        old = target.data
        target.data = joined
        bpy.data.objects.remove(target_copy, do_unlink=True)
        bpy.data.meshes.remove(old)
        joined.name = target.name
    except Exception:
        for item in copies:
            try:
                name = item.name
            except ReferenceError:
                continue
            mesh = item.data
            bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        raise
    removed = []
    for value, _ in sources:
        mesh = value.data
        removed.append(value.name)
        bpy.data.objects.remove(value, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    return {**info(target), "joined": removed, "triangles_before": total,
            "triangles": triangle_count(target.data)}


def subset(mesh, keep, by_vertex):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        if by_vertex:
            drop = [v for v in bm.verts if v.index not in keep]
            bmesh.ops.delete(bm, geom=drop, context="VERTS")
        else:
            drop = [f for f in bm.faces if f.index not in keep]
            bmesh.ops.delete(bm, geom=drop, context="FACES")
            loose = [v for v in bm.verts if not v.link_faces]
            if loose:
                bmesh.ops.delete(bm, geom=loose, context="VERTS")
        result = bpy.data.meshes.new("CAVI Part")
        bm.to_mesh(result)
        for material in mesh.materials:
            result.materials.append(material)
        result.update()
        return result
    finally:
        bm.free()


def separate_mesh(p):
    value, before = source(p.get("name"))
    by = p.get("by", "loose_parts")
    if by not in {"loose_parts", "materials"}:
        raise ValueError("by must be loose_parts or materials")
    if by == "loose_parts":
        groups = loose_parts(value.data)
        keyed = [(None, group) for group in groups]
    else:
        grouped = {}
        for face in value.data.polygons:
            grouped.setdefault(face.material_index, []).append(face.index)
        keyed = sorted(grouped.items())
    if not 1 <= len(keyed) <= MAX_PARTS:
        raise ValueError(f"separate supports 1 to {MAX_PARTS} parts")
    snapshot = value.data.copy()
    created, parts, changed = [], [], False
    base = value.name
    try:
        for index, (material, group) in enumerate(keyed):
            mesh = subset(snapshot, set(group), by == "loose_parts")
            if index == 0:
                old = value.data
                label = old.name
                value.data = mesh
                bpy.data.meshes.remove(old)
                mesh.name = label
                changed = True
                parts.append({**info(value), "part": 0, "material_index": material})
            else:
                label = free_name(f"{base}_part_{index:02d}")
                mesh.name = label
                item = bpy.data.objects.new(label, mesh)
                (value.users_collection or [bpy.context.scene.collection])[0].objects.link(item)
                item.matrix_world = value.matrix_world.copy()
                created.append(item)
                parts.append({**info(item), "part": index, "material_index": material})
    except Exception:
        for item in created:
            mesh = item.data
            bpy.data.objects.remove(item, do_unlink=True)
            bpy.data.meshes.remove(mesh)
        restore(value, snapshot, changed)
        raise
    bpy.data.meshes.remove(snapshot)
    return {"source": value.name, "by": by, "count": len(parts), "parts": parts,
            "triangles_before": before}


def mirror_mesh(p):
    value, before = source(p.get("name"))
    axis = p.get("symmetry_axis", "X")
    if axis not in {"X", "Y", "Z"}:
        raise ValueError("symmetry_axis must be X, Y or Z")
    threshold = number(p.get("merge_distance", 0.001), 0, 1, "merge_distance")
    clipping = flag(p, "clipping", False)
    snapshot = value.data.copy()
    changed = False
    try:
        modifier = value.modifiers.new("CAVI Mirror", "MIRROR")
        modifier.use_axis = tuple(name == axis for name in "XYZ")
        modifier.use_mirror_merge = threshold > 0
        modifier.merge_threshold = max(threshold, 1e-6)
        modifier.use_clip = clipping
        bake(value, modifier)
        changed = True
        after = checked(value, MAX_TRIANGLES, "Mirrored mesh")
    except Exception:
        restore(value, snapshot, changed)
        raise
    bpy.data.meshes.remove(snapshot)
    return {**info(value), "axis": axis, "merge_distance": threshold, "clipping": clipping,
            "triangles_before": before, "triangles": after}


def array_mesh(p):
    value, before = source(p.get("name"))
    count = p.get("count")
    if type(count) is not int or not 2 <= count <= MAX_ARRAY_COUNT:
        raise ValueError(f"count must be an integer from 2 to {MAX_ARRAY_COUNT}")
    offset = vector(p.get("offset"))
    if all(abs(component) < 1e-9 for component in offset):
        raise ValueError("offset must not be zero")
    if before * count > MAX_TRIANGLES:
        raise ValueError(f"Array would exceed {MAX_TRIANGLES} triangles")
    snapshot = value.data.copy()
    changed = False
    try:
        modifier = value.modifiers.new("CAVI Array", "ARRAY")
        modifier.count = count
        modifier.use_relative_offset = False
        modifier.use_constant_offset = True
        modifier.constant_offset_displace = offset
        bake(value, modifier)
        changed = True
        after = checked(value, MAX_TRIANGLES, "Array result")
    except Exception:
        restore(value, snapshot, changed)
        raise
    bpy.data.meshes.remove(snapshot)
    return {**info(value), "count": count, "offset": list(offset),
            "triangles_before": before, "triangles": after}


def solidify_mesh(p):
    value, before = source(p.get("name"))
    thickness = number(p.get("thickness"), 1e-4, 100, "thickness")
    offset = number(p.get("offset", -1), -1, 1, "offset")
    if before * 3 > MAX_TRIANGLES:
        raise ValueError(f"Solidify would exceed {MAX_TRIANGLES} triangles")
    snapshot = value.data.copy()
    changed = False
    try:
        modifier = value.modifiers.new("CAVI Solidify", "SOLIDIFY")
        modifier.thickness = thickness
        modifier.offset = offset
        modifier.use_even_offset = True
        bake(value, modifier)
        changed = True
        after = checked(value, MAX_TRIANGLES, "Solidified mesh")
    except Exception:
        restore(value, snapshot, changed)
        raise
    bpy.data.meshes.remove(snapshot)
    return {**info(value), "thickness": thickness, "offset": offset,
            "triangles_before": before, "triangles": after}


HANDLERS = {"boolean_mesh": boolean_mesh, "join_meshes": join_meshes,
            "separate_mesh": separate_mesh, "mirror_mesh": mirror_mesh,
            "array_mesh": array_mesh, "solidify_mesh": solidify_mesh}
