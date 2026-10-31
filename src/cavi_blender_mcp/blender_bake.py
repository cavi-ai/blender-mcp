"""Cycles-backed normal, AO, curvature and lightmap baking into workspace PNGs."""

import hashlib
from pathlib import Path

import bpy

from .blender_bridge import number, obj, output_file

MAX_LOW_TRIANGLES = 200000
MAX_HIGH_TRIANGLES = 1000000
MAX_HIGH_OBJECTS = 64
MAX_RESOLUTION = 4096
MAX_SAMPLES = 256


def triangles(value):
    return sum(len(face.vertices) - 2 for face in value.data.polygons)


def state(scene):
    bake = scene.render.bake
    return {
        "engine": scene.render.engine,
        "samples": scene.cycles.samples,
        "denoising": scene.cycles.use_denoising,
        "device": scene.cycles.device,
        "bake": {
            "use_selected_to_active": bake.use_selected_to_active,
            "use_clear": bake.use_clear,
            "margin": bake.margin,
            "margin_type": bake.margin_type,
            "cage_extrusion": bake.cage_extrusion,
            "max_ray_distance": bake.max_ray_distance,
            "use_cage": bake.use_cage,
            "target": bake.target,
            "normal_space": bake.normal_space,
            "use_pass_direct": bake.use_pass_direct,
            "use_pass_indirect": bake.use_pass_indirect,
            "use_pass_color": bake.use_pass_color,
        },
    }


def restore(scene, saved):
    scene.render.engine = saved["engine"]
    scene.cycles.samples = saved["samples"]
    scene.cycles.use_denoising = saved["denoising"]
    scene.cycles.device = saved["device"]
    bake = scene.render.bake
    for key, value in saved["bake"].items():
        setattr(bake, key, value)


def bake_layer(mesh, requested):
    layers = mesh.uv_layers
    layer = layers.get(requested) if requested else next(
        (item for item in layers if item.active_render), layers.active)
    if layer is None:
        raise ValueError("Bake target needs an existing UV layer")
    return layer


def bake(p):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before baking")
    low = obj(p["name"], mesh=True)
    if low.modifiers or low.data.shape_keys is not None:
        raise ValueError("Bake targets must not have modifiers or shape keys")
    low_triangles = triangles(low)
    if not 0 < low_triangles <= MAX_LOW_TRIANGLES:
        raise ValueError(f"Low-poly target needs 1 to {MAX_LOW_TRIANGLES} triangles")
    mode = p.get("map")
    if mode not in {"normal", "ao", "curvature", "lightmap"}:
        raise ValueError("map must be normal, ao, curvature or lightmap")
    high_names = p.get("high")
    if high_names is not None and mode not in {"normal", "ao"}:
        raise ValueError("high applies to normal and ao bakes")
    if high_names is not None:
        if (not isinstance(high_names, list) or not 1 <= len(high_names) <= MAX_HIGH_OBJECTS
                or len(set(high_names)) != len(high_names)):
            raise ValueError(f"high must list 1 to {MAX_HIGH_OBJECTS} unique meshes")
        if low.name in high_names:
            raise ValueError("high must not include the low-poly target")
    high = [obj(name, mesh=True) for name in (high_names or [])]
    for value in high:
        if value.modifiers or value.data.shape_keys is not None:
            raise ValueError("High-poly sources must not have modifiers or shape keys")
    high_triangles = sum(triangles(value) for value in high)
    if high_triangles > MAX_HIGH_TRIANGLES:
        raise ValueError(f"High-poly sources are limited to {MAX_HIGH_TRIANGLES} triangles")
    resolution = p.get("resolution", 1024)
    if type(resolution) is not int or not 64 <= resolution <= MAX_RESOLUTION:
        raise ValueError(f"resolution must be an integer from 64 to {MAX_RESOLUTION}")
    samples = p.get("samples", 16)
    if type(samples) is not int or not 1 <= samples <= MAX_SAMPLES:
        raise ValueError(f"samples must be an integer from 1 to {MAX_SAMPLES}")
    margin = p.get("margin", 4)
    if type(margin) is not int or not 0 <= margin <= 64:
        raise ValueError("margin must be an integer from 0 to 64")
    cage = number(p.get("cage_extrusion", 0.01), 0, 1, "cage_extrusion")
    distance = number(p.get("max_ray_distance", 0.1), 0, 10, "max_ray_distance")
    isolate = p.get("isolate", True)
    if type(isolate) is not bool:
        raise ValueError("isolate must be boolean")
    normal_space = p.get("normal_space")
    if mode == "normal":
        normal_space = normal_space or "tangent"
        if normal_space not in {"tangent", "object"}:
            raise ValueError("normal_space must be tangent or object")
    elif normal_space is not None:
        raise ValueError("normal_space applies to normal bakes only")
    selected = bool(high)
    layer = bake_layer(low.data, p.get("uv_layer"))

    scene = bpy.context.scene
    saved = state(scene)
    selection = list(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    visibility = [(value, value.hide_render, value.hide_viewport, value.hide_get())
                  for value in scene.objects]
    image = material = bake_low = None
    try:
        bake_low = low.copy()
        bake_low.data = low.data.copy()
        bake_low.parent = None
        scene.collection.objects.link(bake_low)
        bake_low.matrix_world = low.matrix_world.copy()
        bake_low.hide_render = False
        bake_low.hide_viewport = False
        bake_low.hide_set(False)
        layers = bake_low.data.uv_layers
        target_layer = layers.get(layer.name)
        if target_layer is None:
            raise RuntimeError("Could not copy the bake UV layer")
        layers.active = target_layer
        target_layer.active_render = True
        image = bpy.data.images.new("CAVI Bake", resolution, resolution, alpha=False)
        image.colorspace_settings.name = "sRGB" if mode == "lightmap" else "Non-Color"
        material = bpy.data.materials.new("CAVI Bake")
        material.use_nodes = True
        nodes, links = material.node_tree.nodes, material.node_tree.links
        for node in list(nodes):
            nodes.remove(node)
        output = nodes.new("ShaderNodeOutputMaterial")
        target = nodes.new("ShaderNodeTexImage")
        target.image = image
        if mode == "curvature":
            geometry = nodes.new("ShaderNodeNewGeometry")
            mapping = nodes.new("ShaderNodeMapRange")
            emission = nodes.new("ShaderNodeEmission")
            mapping.inputs["From Min"].default_value = 0.3
            mapping.inputs["From Max"].default_value = 0.7
            links.new(geometry.outputs["Pointiness"], mapping.inputs["Value"])
            links.new(mapping.outputs["Result"], emission.inputs["Color"])
            links.new(emission.outputs["Emission"], output.inputs["Surface"])
        else:
            shader = nodes.new("ShaderNodeBsdfPrincipled")
            links.new(shader.outputs["BSDF"], output.inputs["Surface"])
        nodes.active = target
        bake_low.data.materials.append(material)
        bake_low.active_material_index = len(bake_low.material_slots) - 1

        for value, hidden_render, hidden_viewport, _ in visibility:
            if value is bake_low or value in high:
                value.hide_render = False
            elif value.type in {"LIGHT", "LIGHT_PROBE", "LIGHTPROBE"}:
                value.hide_render = hidden_render
            elif value is low or isolate:
                value.hide_render = True
            else:
                value.hide_render = hidden_render
        for value in [bake_low, *high]:
            value.hide_viewport = False
            value.hide_set(False)
        for value in list(bpy.context.selected_objects):
            value.select_set(False)
        for value in [bake_low, *high]:
            value.select_set(True)
        bpy.context.view_layer.objects.active = bake_low
        bpy.context.view_layer.update()

        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = samples
        scene.cycles.use_denoising = False
        settings = scene.render.bake
        settings.use_selected_to_active = selected
        settings.use_clear = True
        settings.margin = margin
        settings.margin_type = "EXTEND"
        settings.cage_extrusion = cage
        settings.max_ray_distance = distance
        settings.use_cage = False
        settings.target = "IMAGE_TEXTURES"
        if mode == "normal":
            settings.normal_space = normal_space.upper()
        if mode == "lightmap":
            settings.use_pass_direct = True
            settings.use_pass_indirect = True
            settings.use_pass_color = False
        with output_file(p["path"], {".png"}) as path:
            if mode == "normal":
                result = bpy.ops.object.bake(type="NORMAL")
            elif mode == "ao":
                result = bpy.ops.object.bake(type="AO")
            elif mode == "curvature":
                result = bpy.ops.object.bake(type="EMIT")
            else:
                result = bpy.ops.object.bake(type="DIFFUSE",
                                             pass_filter={"DIRECT", "INDIRECT"})
            if "FINISHED" not in result:
                raise RuntimeError("Bake did not finish")
            image.filepath_raw = str(path)
            image.file_format = "PNG"
            image.save()
        data = Path(path).read_bytes()
        return {"path": str(path), "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(), "map": mode,
                "resolution": resolution, "samples": samples, "margin": margin,
                "cage_extrusion": cage, "max_ray_distance": distance,
                "normal_space": normal_space if mode == "normal" else None,
                "uv_layer": layer.name,
                "low": low.name, "high": [value.name for value in high],
                "selected_to_active": selected, "isolate": isolate}
    finally:
        restore(scene, saved)
        for value, hidden_render, hidden_viewport, hidden_get in visibility:
            value.hide_render = hidden_render
            value.hide_viewport = hidden_viewport
            value.hide_set(hidden_get)
        for value in list(bpy.context.selected_objects):
            value.select_set(False)
        for value in selection:
            try:
                value.select_set(True)
            except ReferenceError:
                continue
        if active is not None:
            bpy.context.view_layer.objects.active = active
        if bake_low is not None:
            data = bake_low.data
            if material is not None:
                for index, item in enumerate(data.materials):
                    if item is material:
                        data.materials.pop(index=index)
                        break
            bpy.data.objects.remove(bake_low, do_unlink=True)
            if data.users == 0:
                bpy.data.meshes.remove(data)
        if material is not None:
            bpy.data.materials.remove(material)
        if image is not None:
            bpy.data.images.remove(image)
