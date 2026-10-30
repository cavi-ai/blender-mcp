"""Typed material assignment inside Blender; no caller-authored node code."""

import math
import tempfile
from pathlib import Path

import bpy

from .textures import read_png


def unit(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Material values must be finite numbers from 0 to 1")
    return float(value)


def linear(value):
    value = unit(value)
    return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4


def stored_path(path):
    if not bpy.data.filepath:
        return path
    try:
        return bpy.path.relpath(path)
    except ValueError:
        return path


def multiply_node(tree):
    try:
        node = tree.nodes.new("ShaderNodeMix")
    except RuntimeError:
        node = tree.nodes.new("ShaderNodeMixRGB")
        node.blend_type = "MULTIPLY"
        return node.inputs[0], node.inputs[1], node.inputs[2], node.outputs[0]
    node.data_type = "RGBA"
    node.blend_type = "MULTIPLY"
    inputs = {socket.identifier: socket for socket in node.inputs}
    outputs = {socket.identifier: socket for socket in node.outputs}
    return inputs["Factor_Float"], inputs["A_Color"], inputs["B_Color"], outputs["Result_Color"]


def assign(params, workspace, find_object):
    names = params["names"]
    name = params["material_name"]
    slot = params.get("slot", 0)
    if not isinstance(names, list) or not 1 <= len(names) <= 32 or len(set(names)) != len(names):
        raise ValueError("Choose 1 to 32 unique mesh names")
    if not isinstance(name, str) or not name.strip() or len(name.encode()) > 63:
        raise ValueError("Material name must be nonempty and at most 63 UTF-8 bytes")
    if name in bpy.data.materials:
        raise ValueError("Material name already exists; inspect before assigning")
    if type(slot) is not int or not 0 <= slot <= 31:
        raise ValueError("Material slot must be 0 to 31")
    values = [find_object(value, mesh=True) for value in names]
    for value in values:
        if value.data.users != 1:
            raise ValueError("Material assignment requires single-user mesh data")
        if slot >= len(value.material_slots) and not (slot == 0 and not value.material_slots):
            raise ValueError("Requested material slot does not exist")
    color = params.get("base_color", [1, 1, 1, 1])
    if not isinstance(color, (list, tuple)) or len(color) != 4:
        raise ValueError("Base color requires four sRGB RGBA values")
    color = [unit(value) for value in color]
    roughness, metallic = unit(params.get("roughness", .5)), unit(params.get("metallic", 0))
    texture = params.get("base_color_texture")
    receipt, payload = read_png(workspace, texture) if texture is not None else (None, None)
    if texture is not None and any(not value.data.uv_layers for value in values):
        raise ValueError("Textured meshes require an existing UV layer")
    material, image = None, None
    previous = [(value, len(value.material_slots),
                 value.material_slots[slot].link if value.material_slots else None,
                 value.material_slots[slot].material if value.material_slots else None)
                for value in values]
    try:
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        material.diffuse_color = (*[linear(value) for value in color[:3]], color[3])
        shader = material.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = material.diffuse_color
        shader.inputs["Alpha"].default_value = color[3]
        shader.inputs["Roughness"].default_value = roughness
        shader.inputs["Metallic"].default_value = metallic
        if receipt:
            with tempfile.TemporaryDirectory(prefix=".cavi-texture-", dir=workspace) as folder:
                snapshot = Path(folder) / "color.png"
                snapshot.write_bytes(payload)
                image = bpy.data.images.load(str(snapshot), check_existing=False)
                if tuple(image.size) != (receipt["width"], receipt["height"]):
                    raise ValueError("Blender did not decode the expected PNG dimensions")
                image.colorspace_settings.name = "sRGB"
                image.pack()
                image.filepath = stored_path(receipt["path"])
            node = material.node_tree.nodes.new("ShaderNodeTexImage")
            node.image = image
            factor, color_in, tint, result = multiply_node(material.node_tree)
            factor.default_value = 1
            tint.default_value = material.diffuse_color
            material.node_tree.links.new(node.outputs["Color"], color_in)
            material.node_tree.links.new(result, shader.inputs["Base Color"])
        for value in values:
            if not value.material_slots:
                value.data.materials.append(material)
            value.material_slots[slot].link = "OBJECT"
            value.material_slots[slot].material = material
        return {"material": material.name, "objects": names, "slot": slot,
                "base_color_srgb": color, "roughness": roughness, "metallic": metallic,
                "base_color_texture": receipt, "texture_packed": bool(image and image.packed_file)}
    except Exception:
        for value, count, link, old_material in previous:
            if not count and value.material_slots:
                value.data.materials.pop(index=0)
            elif count:
                value.material_slots[slot].link = link
                value.material_slots[slot].material = old_material
        if material is not None:
            bpy.data.materials.remove(material)
        if image is not None:
            bpy.data.images.remove(image)
        raise
