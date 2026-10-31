"""Typed PBR material assignment inside Blender; no caller-authored node code."""

import json
import math
import tempfile
from pathlib import Path

import bpy

from .textures import read_image

CONFIG_TAG = "cavi_material_config"
COLOR_TEXTURES = {"base_color_texture": "sRGB", "emission_texture": "sRGB"}
NON_COLOR_TEXTURES = {"normal_texture": "Non-Color", "roughness_texture": "Non-Color",
                      "metallic_texture": "Non-Color", "alpha_texture": "Non-Color"}
TEXTURES = {**COLOR_TEXTURES, **NON_COLOR_TEXTURES}
MAX_TOTAL_PIXELS = 32 * 1024 * 1024
DEFAULTS = {
    "base_color": [1.0, 1.0, 1.0, 1.0],
    "base_color_texture": None,
    "roughness": .5,
    "metallic": 0.0,
    "roughness_texture": None,
    "metallic_texture": None,
    "normal_texture": None,
    "normal_strength": 1.0,
    "emission_texture": None,
    "emission_strength": 0.0,
    "alpha_texture": None,
    "alpha_mode": "opaque",
    "uv_scale": [1.0, 1.0],
    "uv_offset": [0.0, 0.0],
    "uv_rotation_degrees": 0.0,
}


def unit(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Material values must be finite numbers from 0 to 1")
    return float(value)


def linear(value):
    value = unit(value)
    return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4


def bounded(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be a number from {low} to {high}")
    return float(value)


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


def path_name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ValueError("Texture paths must be nonempty workspace paths")
    return value


def pair(value, low, high, label):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} requires two components")
    return [bounded(value[0], low, high, label), bounded(value[1], low, high, label)]


def overlay(params):
    provided = {}
    if params.get("base_color") is not None:
        color = params["base_color"]
        if not isinstance(color, (list, tuple)) or len(color) != 4:
            raise ValueError("Base color requires four sRGB RGBA values")
        provided["base_color"] = [unit(value) for value in color]
    if params.get("base_color_texture") is not None:
        provided["base_color_texture"] = path_name(params["base_color_texture"])
    if params.get("roughness") is not None:
        provided["roughness"] = unit(params["roughness"])
    if params.get("metallic") is not None:
        provided["metallic"] = unit(params["metallic"])
    if params.get("roughness_texture") is not None:
        provided["roughness_texture"] = path_name(params["roughness_texture"])
    if params.get("metallic_texture") is not None:
        provided["metallic_texture"] = path_name(params["metallic_texture"])
    if params.get("normal_texture") is not None:
        provided["normal_texture"] = path_name(params["normal_texture"])
    if params.get("normal_strength") is not None:
        provided["normal_strength"] = bounded(params["normal_strength"], 0, 10,
                                              "normal_strength")
    if params.get("emission_texture") is not None:
        provided["emission_texture"] = path_name(params["emission_texture"])
    if params.get("emission_strength") is not None:
        provided["emission_strength"] = bounded(params["emission_strength"], 0, 1000,
                                                "emission_strength")
    if params.get("alpha_texture") is not None:
        provided["alpha_texture"] = path_name(params["alpha_texture"])
    if params.get("alpha_mode") is not None:
        if params["alpha_mode"] not in {"opaque", "clip", "blend"}:
            raise ValueError("alpha_mode must be opaque, clip or blend")
        provided["alpha_mode"] = params["alpha_mode"]
    if params.get("uv_scale") is not None:
        provided["uv_scale"] = pair(params["uv_scale"], 0.0001, 1000, "uv_scale")
    if params.get("uv_offset") is not None:
        provided["uv_offset"] = pair(params["uv_offset"], -1000, 1000, "uv_offset")
    if params.get("uv_rotation_degrees") is not None:
        provided["uv_rotation_degrees"] = bounded(params["uv_rotation_degrees"], -3600, 3600,
                                                  "uv_rotation_degrees")
    return provided


def resolve_config(params, existing):
    update = params.get("update_existing", False)
    if type(update) is not bool:
        raise ValueError("update_existing must be boolean")
    provided = overlay(params)
    if update:
        if existing is None:
            raise ValueError("Material does not exist; omit update_existing to create it")
        raw = existing.get(CONFIG_TAG)
        if not isinstance(raw, str):
            raise ValueError("Only materials created by assign_material can be updated")
        try:
            previous = json.loads(raw)
        except ValueError as exc:
            raise ValueError("Material configuration is not readable") from exc
        if not isinstance(previous, dict):
            raise ValueError("Material configuration is not readable")
        config = {**DEFAULTS, **previous, **provided}
    else:
        config = {**DEFAULTS, **provided}
    if config.get("alpha_texture") and config.get("alpha_mode") == "opaque":
        if "alpha_mode" in provided:
            raise ValueError("alpha_texture requires alpha_mode clip or blend")
        config["alpha_mode"] = "clip"
    if (config.get("emission_texture") and "emission_strength" not in provided
            and not config.get("emission_strength")):
        config["emission_strength"] = 1.0
    return config, update


def textures(workspace, config):
    found, total = {}, 0
    for key in TEXTURES:
        name = config.get(key)
        if name is None:
            continue
        receipt, payload = read_image(workspace, name)
        total += receipt["pixels"]
        if total > MAX_TOTAL_PIXELS:
            raise ValueError("Material textures exceed the combined pixel budget")
        found[key] = (receipt, payload)
    return found


def load_image(workspace, receipt, payload, color_space, folder, label):
    suffix = "." + receipt["format"]
    snapshot = Path(folder) / (label.replace(" ", "_") + suffix)
    snapshot.write_bytes(payload)
    image = bpy.data.images.load(str(snapshot), check_existing=False)
    if tuple(image.size) != (receipt["width"], receipt["height"]):
        bpy.data.images.remove(image)
        raise ValueError("Blender did not decode the expected texture dimensions")
    image.colorspace_settings.name = color_space
    image.pack()
    image.filepath = stored_path(receipt["path"])
    return image


def apply_alpha(material, mode):
    if mode not in {"opaque", "clip", "blend"}:
        raise ValueError("alpha_mode must be opaque, clip or blend")
    material.blend_method = {"opaque": "OPAQUE", "clip": "CLIP", "blend": "BLEND"}[mode]
    material.surface_render_method = "BLENDED" if mode == "blend" else "DITHERED"
    material.alpha_threshold = .5
    material.use_transparent_shadow = mode != "opaque"


def build(material, config, workspace, receipts, created_images, discard=None):
    tree = material.node_tree
    nodes, links = tree.nodes, tree.links
    nodes.clear()
    if discard:
        remove_unused(discard, set())
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (420, 0)
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.location = (120, 0)
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    color = config["base_color"]
    diffuse = (*[linear(value) for value in color[:3]], color[3])
    material.diffuse_color = diffuse
    shader.inputs["Base Color"].default_value = diffuse
    shader.inputs["Alpha"].default_value = color[3]
    shader.inputs["Roughness"].default_value = config["roughness"]
    shader.inputs["Metallic"].default_value = config["metallic"]
    mapping = None
    if receipts:
        uv = nodes.new("ShaderNodeUVMap")
        uv.uv_map = ""
        mapping = nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (*config["uv_scale"], 1)
        mapping.inputs["Location"].default_value = (*config["uv_offset"], 0)
        mapping.inputs["Rotation"].default_value = (
            0, 0, math.radians(config["uv_rotation_degrees"]))
        links.new(uv.outputs["UV"], mapping.inputs["Vector"])
    with tempfile.TemporaryDirectory(prefix=".cavi-texture-", dir=workspace) as folder:
        def image(key, label):
            receipt, payload = receipts[key]
            loaded = load_image(workspace, receipt, payload, TEXTURES[key], folder, label)
            loaded.name = f"{material.name}_{label.replace(' ', '_')}"
            created_images.append(loaded)
            node = nodes.new("ShaderNodeTexImage")
            node.label = label
            node.image = loaded
            links.new(mapping.outputs["Vector"], node.inputs["Vector"])
            return node

        if "base_color_texture" in receipts:
            node = image("base_color_texture", "Base Color")
            factor, color_in, tint, result = multiply_node(tree)
            factor.default_value = 1
            tint.default_value = diffuse
            links.new(node.outputs["Color"], color_in)
            links.new(result, shader.inputs["Base Color"])
        if "normal_texture" in receipts:
            node = image("normal_texture", "Normal")
            normal = nodes.new("ShaderNodeNormalMap")
            normal.inputs["Strength"].default_value = config["normal_strength"]
            links.new(node.outputs["Color"], normal.inputs["Color"])
            links.new(normal.outputs["Normal"], shader.inputs["Normal"])
        if "roughness_texture" in receipts:
            links.new(image("roughness_texture", "Roughness").outputs["Color"],
                      shader.inputs["Roughness"])
        if "metallic_texture" in receipts:
            links.new(image("metallic_texture", "Metallic").outputs["Color"],
                      shader.inputs["Metallic"])
        if "emission_texture" in receipts:
            links.new(image("emission_texture", "Emission").outputs["Color"],
                      shader.inputs["Emission Color"])
            shader.inputs["Emission Strength"].default_value = config["emission_strength"]
        elif config["emission_strength"]:
            shader.inputs["Emission Color"].default_value = (1, 1, 1, 1)
            shader.inputs["Emission Strength"].default_value = config["emission_strength"]
        if "alpha_texture" in receipts:
            alpha = image("alpha_texture", "Alpha").outputs["Color"]
            if config["alpha_mode"] == "clip":
                cut = nodes.new("ShaderNodeMath")
                cut.operation = "ROUND"
                links.new(alpha, cut.inputs[0])
                alpha = cut.outputs[0]
            links.new(alpha, shader.inputs["Alpha"])
    apply_alpha(material, config["alpha_mode"])


def remove_unused(images, keep):
    for image in images:
        if image not in keep and image.users == 0:
            bpy.data.images.remove(image)


def assign(params, workspace, find_object):
    names = params["names"]
    name = params["material_name"]
    slot = params.get("slot", 0)
    if not isinstance(names, list) or not 1 <= len(names) <= 32 or len(set(names)) != len(names):
        raise ValueError("Choose 1 to 32 unique mesh names")
    if not isinstance(name, str) or not name.strip() or len(name.encode()) > 63:
        raise ValueError("Material name must be nonempty and at most 63 UTF-8 bytes")
    if type(slot) is not int or not 0 <= slot <= 31:
        raise ValueError("Material slot must be 0 to 31")
    values = [find_object(value, mesh=True) for value in names]
    existing = bpy.data.materials.get(name)
    config, update = resolve_config(params, existing)
    if existing is not None and not update:
        raise ValueError("Material name already exists; pass update_existing=true to change it")
    for value in values:
        if value.data.users != 1:
            raise ValueError("Material assignment requires single-user mesh data")
        if slot >= len(value.material_slots):
            if not (slot == 0 and not value.material_slots):
                raise ValueError("Requested material slot does not exist")
        elif update and value.material_slots[slot].material is not existing:
            raise ValueError("update_existing requires the material to be bound to this slot")
    if any(config.get(key) is not None for key in TEXTURES) and any(
            not value.data.uv_layers for value in values):
        raise ValueError("Textured meshes require an existing UV layer")
    receipts = textures(workspace, config)
    old_images = set()
    if update:
        if existing.node_tree is not None:
            old_images = {node.image for node in existing.node_tree.nodes
                          if node.type == "TEX_IMAGE" and node.image is not None}
        old_config = json.loads(existing[CONFIG_TAG])
    else:
        old_config = None
    material = existing
    created = material is None
    new_images = []
    try:
        if created:
            material = bpy.data.materials.new(name)
        material.use_nodes = True
        build(material, config, workspace, receipts, new_images,
              old_images if update else None)
        for value in values:
            if not value.material_slots:
                value.data.materials.append(material)
            value.material_slots[slot].link = "OBJECT"
            value.material_slots[slot].material = material
        material[CONFIG_TAG] = json.dumps(config, sort_keys=True)
    except Exception:
        if created:
            if material is not None:
                bpy.data.materials.remove(material)
            remove_unused(new_images, set())
        elif old_config is not None:
            remove_unused(new_images, set())
            restored, failed = [], False
            try:
                previous = {**DEFAULTS, **old_config}
                build(material, previous, workspace, textures(workspace, previous), restored)
            except (ValueError, RuntimeError, OSError, TypeError, KeyError):
                failed = True
            remove_unused(new_images, set())
            if failed:
                remove_unused(restored, set())
        raise
    packed = all(image.packed_file is not None for image in new_images)
    return {
        "material": material.name,
        "objects": names,
        "slot": slot,
        "updated": update,
        "material_users": material.users,
        "base_color_srgb": config["base_color"],
        "roughness": config["roughness"],
        "metallic": config["metallic"],
        "base_color_texture": receipts.get("base_color_texture", (None, None))[0],
        "textures": {key: value[0] for key, value in receipts.items()},
        "config": config,
        "texture_packed": packed,
    }
