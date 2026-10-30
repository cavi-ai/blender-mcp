"""Bounded, read-only measurements of static Blender mesh sources."""

import math

import bpy

from .mapping import measure_triangle, summarize

MAX_TRIANGLES = 100000
MAX_VERTICES = 100000


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
        "not_checked": ["UV overlaps", "seam continuity", "shader appearance"],
    }
