"""Read-only multi-view contact sheet renders with temporary stand-ins."""

import math
import tempfile
from contextlib import contextmanager
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Vector

from .blender_bridge import RENDERLESS, number, obj, output_file
from .blender_geometry import triangle_count, unit_scale

VIEWS = {"front": (0, -1, 0), "back": (0, 1, 0), "left": (-1, 0, 0), "right": (1, 0, 0),
         "top": (0, 0, 1), "persp": (1.5, -2, 1.4)}
MODES = {"shaded", "wireframe", "uv_checker", "texel_heatmap", "matcap"}
MAX_TRIANGLES = 500000
MAX_COPY_TRIANGLES = 200000
MATCAP = "clay_studio.exr"


def heat(ratio):
    if ratio is None:
        return (1.0, 0.0, 1.0, 1.0)
    t = max(-1.0, min(1.0, math.log2(max(ratio, 1e-6))))
    if t < 0:
        return (0.0, 1.0 + t, -t, 1.0)
    return (t, 1.0 - t, 0.0, 1.0)


def face_density(value, layer, resolution, unit):
    from .blender_geometry import uv_triangles, world_triangles

    mesh = value.data
    points = world_triangles(value, unit)
    uvs = uv_triangles(mesh, layer)
    owners = np.empty(len(mesh.loop_triangles), np.int64)
    mesh.loop_triangles.foreach_get("polygon_index", owners)
    world = np.linalg.norm(np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]),
                           axis=1) / 2
    d1, d2 = uvs[:, 1] - uvs[:, 0], uvs[:, 2] - uvs[:, 0]
    uv = np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / 2
    count = len(mesh.polygons)
    world_sum = np.bincount(owners, world, count)
    uv_sum = np.bincount(owners, uv, count)
    valid = (world_sum > 1e-12) & (uv_sum > 1e-12)
    result = np.full(count, np.nan)
    result[valid] = np.sqrt(resolution * resolution * uv_sum[valid] / world_sum[valid])
    return result


def checker_material(stack):
    image = bpy.data.images.new("CAVI Checker", 1024, 1024)
    image.generated_type = "COLOR_GRID"
    stack["images"].append(image)
    material = bpy.data.materials.new("CAVI Checker")
    stack["materials"].append(material)
    material.use_nodes = True
    node = material.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    material.node_tree.nodes.active = node
    return material


def stand_in(source, mesh, stack):
    item = bpy.data.objects.new("CAVI Review", mesh)
    stack["objects"].append(item)
    bpy.context.scene.collection.objects.link(item)
    item.matrix_world = source.matrix_world.copy()
    return item


def copy_mesh(source, stack):
    mesh = source.data.copy()
    stack["meshes"].append(mesh)
    return mesh


def select_layer(mesh, requested):
    layers = mesh.uv_layers
    layer = layers.get(requested) if requested else next(
        (x for x in layers if x.active_render), layers.active)
    if layer is None:
        raise ValueError(f"{mesh.name}: UV layer does not exist")
    return layer.name


def prepare(meshes, mode, params, stack, radius):
    shading = bpy.context.scene.display.shading
    shading.light, shading.color_type = "STUDIO", "MATERIAL"
    stats = None
    if mode == "matcap":
        shading.light = "MATCAP"
        names = [x.name for x in bpy.context.preferences.studio_lights if x.type == "MATCAP"]
        shading.studio_light = MATCAP if MATCAP in names else names[0]
        return meshes, stats
    if mode == "shaded":
        return meshes, stats
    if mode == "wireframe":
        shading.color_type = "OBJECT"
        for source in meshes:
            wire = stand_in(source, source.data, stack)
            modifier = wire.modifiers.new("Wire", "WIREFRAME")
            scale = max(max(source.matrix_world.to_scale()), 1e-6)
            modifier.thickness = radius * 0.005 / scale
            modifier.offset = 1
            modifier.use_even_offset = True
            modifier.use_replace = True
            wire.color = (0.02, 0.02, 0.02, 1)
        return meshes + [x for x in stack["objects"]], stats
    if sum(triangle_count(v.data) for v in meshes) > MAX_COPY_TRIANGLES:
        raise ValueError(f"{mode} is bounded to {MAX_COPY_TRIANGLES} triangles")
    requested = params.get("uv_layer")
    shown = []
    if mode == "uv_checker":
        shading.color_type = "TEXTURE"
        material = checker_material(stack)
        for source in meshes:
            label = select_layer(source.data, requested)
            mesh = copy_mesh(source, stack)
            mesh.uv_layers.active = mesh.uv_layers[label]
            mesh.uv_layers[label].active_render = True
            mesh.materials.clear()
            mesh.materials.append(material)
            shown.append(stand_in(source, mesh, stack))
        return shown, stats
    target = params.get("target_px_per_m")
    target = number(512 if target is None else target, 0.01, 100000, "target_px_per_m")
    size = params.get("texture_resolution")
    size = 1024 if size is None else size
    if type(size) is not int or not 1 <= size <= 4096:
        raise ValueError("texture_resolution must be an integer from 1 to 4096")
    shading.color_type = "VERTEX"
    unit = unit_scale()
    low = high = on = 0
    for source in meshes:
        label = select_layer(source.data, requested)
        values = face_density(source, source.data.uv_layers[label], size, unit)
        mesh = copy_mesh(source, stack)
        totals = np.empty(len(mesh.polygons), np.int64)
        mesh.polygons.foreach_get("loop_total", totals)
        colors = np.array([heat(None if np.isnan(d) else d / target) for d in values],
                          np.float32).reshape(-1, 4)
        attribute = mesh.color_attributes.new("CAVI Heat", "FLOAT_COLOR", "CORNER")
        attribute.data.foreach_set("color", np.repeat(colors, totals, axis=0).ravel())
        mesh.color_attributes.active_color = attribute
        mesh.color_attributes.render_color_index = mesh.color_attributes.find("CAVI Heat")
        ratio = values[~np.isnan(values)] / target
        low += int((ratio < 0.8).sum())
        high += int((ratio > 1.25).sum())
        on += int(((ratio >= 0.8) & (ratio <= 1.25)).sum())
        shown.append(stand_in(source, mesh, stack))
    stats = {"faces_below": low, "faces_on_target": on, "faces_above": high}
    return shown, stats


def place_camera(camera, view, center, radius):
    data = camera.data
    if view == "persp":
        data.type = "PERSP"
        distance = max(radius * 3.5, 2)
    else:
        data.type = "ORTHO"
        data.ortho_scale = radius * 2.2
        distance = radius * 3 + 1
    data.clip_start = max(1e-4, min(0.1, (distance - radius) * 0.5))
    data.clip_end = distance + radius * 2
    direction = Vector(VIEWS[view]).normalized()
    camera.location = center + direction * distance
    if view == "top":
        camera.rotation_euler = Euler((0, 0, 0))
    else:
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()


@contextmanager
def render_state(scene):
    render, shading = scene.render, scene.display.shading
    keys = [(render, "engine"), (render, "filepath"), (render, "resolution_x"),
            (render, "resolution_y"), (render, "resolution_percentage"),
            (render, "film_transparent"), (shading, "studio_light"), (shading, "light"),
            (shading, "color_type"), (scene, "camera")]
    image = (render.image_settings.file_format, render.image_settings.color_mode)
    saved = [(owner, key, getattr(owner, key)) for owner, key in keys]
    visibility = [(v, v.hide_render) for v in scene.objects if v.type not in RENDERLESS]
    stack = {"objects": [], "meshes": [], "materials": [], "images": [], "cameras": []}
    try:
        yield stack, visibility
    finally:
        for value, hidden in visibility:
            value.hide_render = hidden
        for owner, key, value in reversed(saved):
            try:
                setattr(owner, key, value)
            except TypeError:
                pass
        render.image_settings.file_format, render.image_settings.color_mode = image
        for item in stack["objects"]:
            bpy.data.objects.remove(item, do_unlink=True)
        for kind in ("meshes", "materials", "images", "cameras"):
            pool = getattr(bpy.data, kind)
            for item in stack[kind]:
                pool.remove(item)


def tile_pixels(path, tile):
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        if tuple(image.size) != (tile, tile):
            raise RuntimeError("Rendered tile has unexpected dimensions")
        pixels = np.empty(tile * tile * 4, np.float32)
        image.pixels.foreach_get(pixels)
        return pixels.reshape(tile, tile, 4)
    finally:
        bpy.data.images.remove(image)


def review(p):
    scene = bpy.context.scene
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before rendering")
    views = p.get("views") or list(VIEWS)
    if (not isinstance(views, list) or not 1 <= len(views) <= 6
            or len(set(views)) != len(views) or any(v not in VIEWS for v in views)):
        raise ValueError(f"views must be 1 to 6 unique entries from {list(VIEWS)}")
    mode = p.get("mode", "shaded")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {sorted(MODES)}")
    resolution = p.get("resolution", 1024)
    if type(resolution) is not int or not 256 <= resolution <= 2048:
        raise ValueError("Sheet resolution must be between 256 and 2048")
    for key, allowed in (("target_px_per_m", {"texel_heatmap"}),
                         ("texture_resolution", {"texel_heatmap"}),
                         ("uv_layer", {"texel_heatmap", "uv_checker"})):
        if p.get(key) is not None and mode not in allowed:
            raise ValueError(f"{key} applies to {' or '.join(sorted(allowed))}")
    names = p.get("names")
    if names is not None:
        if not isinstance(names, list) or not 1 <= len(names) <= 1000:
            raise ValueError("Provide between 1 and 1000 mesh names")
        meshes = [obj(name, mesh=True) for name in names]
    else:
        meshes = [v for v in scene.objects if v.type == "MESH" and not v.hide_render]
    if not meshes:
        raise ValueError("Scene has no visible meshes")
    if sum(triangle_count(v.data) for v in meshes) > MAX_TRIANGLES:
        raise ValueError(f"Review sheets are bounded to {MAX_TRIANGLES} source triangles")
    bpy.context.view_layer.update()
    points = [v.matrix_world @ Vector(c) for v in meshes for c in v.bound_box]
    center = Vector([(min(q[i] for q in points) + max(q[i] for q in points)) / 2
                     for i in range(3)])
    radius = max(max((q - center).length for q in points), 1e-4)
    columns = min(3, len(views))
    rows = math.ceil(len(views) / columns)
    tile = resolution // columns
    width, height = resolution, tile * rows
    pad = (width - tile * columns) // 2
    with render_state(scene) as (stack, visibility), output_file(p["path"], {".png"}) as path, tempfile.TemporaryDirectory(prefix="cavi-review-") as folder:
        shown, stats = prepare(meshes, mode, p, stack, radius)
        for value, _ in visibility:
            value.hide_render = value not in shown
        for item in stack["objects"]:
            item.hide_render = item not in shown
        data = bpy.data.cameras.new("CAVI Review")
        stack["cameras"].append(data)
        camera = bpy.data.objects.new("CAVI Review Camera", data)
        stack["objects"].append(camera)
        scene.collection.objects.link(camera)
        scene.camera = camera
        render = scene.render
        render.engine = "BLENDER_WORKBENCH"
        render.resolution_x = render.resolution_y = tile
        render.resolution_percentage = 100
        render.film_transparent = False
        render.image_settings.file_format = "PNG"
        render.image_settings.color_mode = "RGBA"
        sheet = np.full((height, width, 4), 0.12, np.float32)
        sheet[..., 3] = 1
        for index, view in enumerate(views):
            place_camera(camera, view, center, radius)
            render.filepath = str(Path(folder) / f"{index}.png")
            if "FINISHED" not in bpy.ops.render.render(write_still=True):
                raise RuntimeError("Review tile render did not finish")
            row, column = divmod(index, columns)
            # Blender pixel rows run bottom to top.
            top = height - (row + 1) * tile
            left = pad + column * tile
            sheet[top:top + tile, left:left + tile] = tile_pixels(
                render.filepath, tile)
        image = bpy.data.images.new("CAVI Review Sheet", width, height, alpha=True)
        stack["images"].append(image)
        image.pixels.foreach_set(sheet.ravel())
        image.filepath_raw = str(path)
        image.file_format = "PNG"
        image.save()
    return {"path": str(path), "views": views, "mode": mode, "size": [width, height],
            "tile": tile, "objects": [v.name for v in meshes], "density": stats}
