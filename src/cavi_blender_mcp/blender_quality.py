"""Bounded, read-only measurements of static Blender mesh sources."""

import math

import bpy
import numpy as np

from .mapping import measure_triangle, summarize
from .naming import lint, rules

MAX_TRIANGLES = 100000
MAX_VERTICES = 100000
CHECKS = {"naming", "topology", "lightmap", "transforms", "origin"}


def topology(mesh):
    edge_faces = np.zeros(len(mesh.edges), np.int64)
    loop_edges = np.empty(len(mesh.loops), np.int64)
    mesh.loops.foreach_get("edge_index", loop_edges)
    np.add.at(edge_faces, loop_edges, 1)
    edge_verts = np.empty(len(mesh.edges) * 2, np.int64)
    mesh.edges.foreach_get("vertices", edge_verts)
    used = np.zeros(len(mesh.vertices), bool)
    used[edge_verts] = True
    totals = np.empty(len(mesh.polygons), np.int64)
    mesh.polygons.foreach_get("loop_total", totals)
    areas = np.empty(len(mesh.polygons), np.float64)
    mesh.polygons.foreach_get("area", areas)
    return {"non_manifold_edges": int(((edge_faces == 0) | (edge_faces > 2)).sum()),
            "boundary_edges": int((edge_faces == 1).sum()),
            "loose_vertices": int((~used).sum()),
            "zero_area_faces": int((areas <= 1e-12).sum()),
            "ngons": int((totals > 4).sum())}


def transforms(value):
    location, rotation, scale = value.matrix_basis.decompose()
    delta = (any(abs(c) > 1e-6 for c in value.delta_location)
             or any(abs(c - 1) > 1e-6 for c in value.delta_scale)
             or value.delta_rotation_quaternion.angle > 1e-6
             or any(abs(c) > 1e-6 for c in value.delta_rotation_euler))
    return {"scale_applied": all(abs(c - 1) <= 1e-5 for c in scale),
            "rotation_applied": rotation.angle <= 1e-5,
            "location_zero": location.length <= 1e-6, "delta_transforms": delta}


def origin(points):
    if not points:
        return None
    low = [min(p[axis] for p in points) for axis in range(3)]
    high = [max(p[axis] for p in points) for axis in range(3)]
    relative = [None if high[i] - low[i] <= 1e-9 else -low[i] / (high[i] - low[i])
                for i in range(3)]

    def near(axis, goal):
        value = relative[axis]
        return value is None and abs(low[axis]) <= 1e-6 or (
            value is not None and abs(value - goal) <= 1e-3)

    label = "other"
    if near(0, .5) and near(1, .5):
        label = "bounds_bottom_center" if near(2, 0) else (
            "bounds_center" if near(2, .5) else "other")
    return {"relative_to_bounds": relative, "classification": label,
            "local_bounds": {"min": low, "max": high}}


def run_checks(value, layer_name, requested, naming, lightmap_resolution):
    from .uvmath import overlap

    mesh = value.data
    report = {}
    if "naming" in requested:
        result = lint(value.name, naming)
        if result["role"] == "collision" and result["base"] and not any(
            name in bpy.context.scene.objects
            for name in (result["base"], result["base"] + "_LOD0")
        ):
            result["issues"].append("collision_without_mesh")
        report["naming"] = result
    if "topology" in requested:
        report["topology"] = topology(mesh)
    if "lightmap" in requested:
        layer = mesh.uv_layers.get(layer_name)
        entry = {"uv_layer": layer_name, "present": layer is not None}
        if layer is not None:
            loops = np.empty(len(mesh.loop_triangles) * 3, np.int64)
            mesh.loop_triangles.foreach_get("loops", loops)
            uv = np.empty(len(mesh.loops) * 2, np.float64)
            layer.data.foreach_get("uv", uv)
            triangles = uv.reshape(-1, 2)[loops].reshape(-1, 3, 2)
            entry.update(overlap(triangles, lightmap_resolution))
            entry["outside_unit_square"] = bool(len(uv) and (uv.min() < -1e-6
                                                             or uv.max() > 1 + 1e-6))
        report["lightmap"] = entry
    if "transforms" in requested:
        report["transforms"] = transforms(value)
    if "origin" in requested:
        report["origin"] = origin([vertex.co[:] for vertex in mesh.vertices])
    return report


def inspect(params, find_object):
    names = params.get("names")
    if not isinstance(names, list) or not 1 <= len(names) <= 32 or len(set(names)) != len(names):
        raise ValueError("Choose 1 to 32 unique mesh names")
    resolution = params.get("texture_resolution", [1024, 1024])
    if len(resolution) != 2 or any(
        type(value) is not int or not 1 <= value <= 4096 for value in resolution
    ):
        raise ValueError("Texture dimensions must be integers from 1 to 4096")
    if bpy.context.mode != "OBJECT":
        raise ValueError("Inspect a working copy in Object Mode")
    selected_checks = params.get("checks") or []
    if not isinstance(selected_checks, list) or any(c not in CHECKS for c in selected_checks):
        raise ValueError(f"checks must be a list from {sorted(CHECKS)}")
    naming = rules(params.get("naming"))
    lightmap_layer = params.get("lightmap_uv", "UVMap_Lightmap")
    if not isinstance(lightmap_layer, str) or not lightmap_layer or len(lightmap_layer) > 63:
        raise ValueError("lightmap_uv must be a UV layer name")
    lightmap_resolution = params.get("lightmap_resolution", 64)
    if type(lightmap_resolution) is not int or not 16 <= lightmap_resolution <= 4096:
        raise ValueError("lightmap_resolution must be an integer from 16 to 4096")
    objects = [find_object(name, mesh=True) for name in names]
    if sum(len(value.material_slots) for value in objects) > 64:
        raise ValueError("Inspect at most 64 material slots per call")
    if sum(len(value.data.vertices) for value in objects) > MAX_VERTICES:
        raise ValueError(f"Inspection is bounded to {MAX_VERTICES} total vertices")
    triangle_budget = 0
    for value in objects:
        if value.modifiers or value.data.shape_keys or value.find_armature():
            raise ValueError(
                "Inspect static sources without modifiers, shape keys or an armature; use a baked working copy"
            )
        triangle_budget += sum(max(0, len(face.vertices) - 2) for face in value.data.polygons)
        if triangle_budget > MAX_TRIANGLES:
            raise ValueError(f"Inspection is bounded to {MAX_TRIANGLES} total triangles")
    units = bpy.context.scene.unit_settings
    # Match Blender's FBX exporter: unitless scenes export one unit as one metre.
    unit_scale = 1.0 if units.system == "NONE" else units.scale_length
    if not math.isfinite(unit_scale) or unit_scale <= 0:
        raise ValueError("Scene unit scale must be positive and finite")
    bpy.context.view_layer.update()
    result, materials, images = [], set(), {}
    for value in objects:
        mesh = value.data
        mesh.calc_loop_triangles()
        requested = params.get("uv_layer")
        layer = (
            mesh.uv_layers.get(requested)
            if requested
            else next(
                (item for item in mesh.uv_layers if item.active_render), mesh.uv_layers.active
            )
        )
        if requested and layer is None:
            raise ValueError(f"{value.name}: requested UV layer does not exist")
        points = [
            tuple(component * unit_scale for component in value.matrix_world @ vertex.co)
            for vertex in mesh.vertices
        ]
        samples, surfaces, uv_points = [], {}, []
        for triangle in mesh.loop_triangles:
            uv = [tuple(layer.data[index].uv) for index in triangle.loops] if layer else None
            sample = measure_triangle(
                [points[index] for index in triangle.vertices], uv, resolution
            )
            slot = triangle.material_index
            if slot >= max(1, len(value.material_slots)):
                raise ValueError(f"{value.name}: a face references a missing material slot")
            surfaces.setdefault(slot, []).append(sample)
            samples.append(sample)
            if uv:
                uv_points.extend(uv)
        bound_surfaces = []
        for slot, entries in sorted(surfaces.items()):
            material = value.material_slots[slot].material if value.material_slots else None
            if material:
                materials.add(material.as_pointer())
                nodes = material.node_tree.nodes if material.use_nodes else []
                if len(nodes) > 512:
                    raise ValueError("Inspect materials with at most 512 nodes")
                for node in nodes:
                    if node.type == "TEX_IMAGE" and node.image:
                        image = node.image
                        images[image.as_pointer()] = {
                            "name": image.name,
                            "size": list(image.size) if image.has_data else None,
                            "loaded": image.has_data,
                            "color_space": image.colorspace_settings.name,
                            "packed": image.packed_file is not None,
                        }
                        if len(images) > 64:
                            raise ValueError("Inspect at most 64 image resources per call")
            bound_surfaces.append(
                {
                    "slot": slot,
                    "material": material.name if material else None,
                    "mapping": summarize(entries),
                }
            )
        bounds = (
            None
            if not points
            else {
                "min": [min(point[axis] for point in points) for axis in range(3)],
                "max": [max(point[axis] for point in points) for axis in range(3)],
            }
        )
        result.append(
            {
                "name": value.name,
                "mesh": mesh.name,
                "vertices": len(points),
                "bounds_meters": bounds,
                "uv_layer": layer.name if layer else None,
                "uv_bounds": None
                if not uv_points
                else {
                    "min": [min(point[axis] for point in uv_points) for axis in range(2)],
                    "max": [max(point[axis] for point in uv_points) for axis in range(2)],
                },
                "mapping": summarize(samples),
                "surfaces": bound_surfaces,
                **({"checks": run_checks(value, lightmap_layer, selected_checks, naming,
                                         lightmap_resolution)} if selected_checks else {}),
            }
        )
    return {
        "scope": "static_source_current_frame",
        "frame": bpy.context.scene.frame_current,
        "file": bpy.data.filepath,
        "dirty": bpy.data.is_dirty,
        "unit_system": units.system,
        "texture_resolution": list(resolution),
        "density_unit": "pixels_per_meter",
        "scene_unit_meters": unit_scale,
        "objects": result,
        "unique_meshes": len({value.data.as_pointer() for value in objects}),
        "unique_materials": len(materials),
        "images": list(images.values()),
        "not_checked": ["UV overlaps" if "lightmap" not in selected_checks else "texture UV overlaps",
                        "seam continuity", "shader appearance"],
    }
