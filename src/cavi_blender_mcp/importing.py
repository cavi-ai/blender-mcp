"""Preflight self-contained GLB files before Blender allocates their data."""

import base64
import hashlib
import json
import math
import re
import struct
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024
MAX_FBX_BYTES = 64 * 1024 * 1024
MAX_GEOMETRY = 500_000
MAX_SKINS = 16
MAX_JOINTS = 512
MAX_TOTAL_JOINTS = 1024
MAX_SKINNED_MESHES = 64
MAX_ANIMATIONS = 32
MAX_CHANNELS = 1024
MAX_KEYS_PER_CLIP = 100000
MAX_TOTAL_KEYS = 256000
MAX_MORPH_TARGETS = 64
MAX_TOTAL_MORPH_TARGETS = 256
TARGET_ATTRIBUTES = {"POSITION", "NORMAL", "TANGENT"}


def image_size(data):
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        offset = 2
        while offset + 4 <= len(data):
            if data[offset] != 0xFF:
                break
            while offset < len(data) and data[offset] == 0xFF:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            length = int.from_bytes(data[offset:offset + 2], "big")
            if length < 2 or offset + length > len(data):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF} and length >= 8:
                height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
                return width, height
            offset += length
    raise ValueError("Embedded image must be a bounded PNG or JPEG")


def inspect_glb(workspace, name):
    root = Path(workspace).expanduser().resolve(strict=True)
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root):
        raise ValueError("Input must stay inside the workspace")
    if path.suffix.lower() != ".glb" or not path.is_file():
        raise ValueError("Input must be a GLB file")
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if not 20 <= len(data) <= MAX_BYTES:
        raise ValueError("GLB must be at most 64 MiB")
    magic, version, size = struct.unpack("<4sII", data[:12])
    if magic != b"glTF" or version != 2 or size != len(data):
        raise ValueError("Invalid GLB header or length")
    offset, chunks = 12, []
    while offset + 8 <= len(data):
        length, kind = struct.unpack("<II", data[offset:offset + 8])
        offset += 8
        if length % 4 or offset + length > len(data):
            raise ValueError("Invalid GLB chunk length")
        chunks.append((kind, memoryview(data)[offset:offset + length]))
        offset += length
    if offset != len(data) or len(chunks) != 2 or [c[0] for c in chunks] != [0x4E4F534A, 0x004E4942]:
        raise ValueError("GLB must contain JSON followed by one embedded binary buffer")
    try:
        document = json.loads(bytes(chunks[0][1]))
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise ValueError("GLB JSON chunk is invalid") from exc
    binary = chunks[1][1]
    if not isinstance(document, dict):
        raise ValueError("Expected glTF 2.0 in the GLB")  # noqa: TRY004
    asset = document.get("asset")
    if not isinstance(asset, dict) or asset.get("version") != "2.0":
        raise ValueError("Expected glTF 2.0 in the GLB")
    for key in (
        "accessors", "animations", "bufferViews", "images", "meshes",
        "materials", "nodes", "scenes", "skins",
    ):
        if not isinstance(document.get(key, []), list):
            raise ValueError(f"GLB {key} must be a list")  # noqa: TRY004
    if document.get("cameras"):
        raise ValueError("Cameras are not supported by the import preflight")
    if len(document.get("scenes", [])) != 1 or not 0 < len(document.get("nodes", [])) <= 1000:
        raise ValueError("GLB imports require one scene and at most 1000 nodes")
    compressed = {"KHR_draco_mesh_compression", "EXT_meshopt_compression"}
    extensions = document.get("extensionsUsed", [])
    if not isinstance(extensions, list) or not all(
            isinstance(extension, str) for extension in extensions):
        raise ValueError("GLB extensionsUsed must be a string list")
    if compressed.intersection(extensions):
        raise ValueError("Compressed geometry is not supported by the import preflight")
    if "KHR_lights_punctual" in extensions:
        raise ValueError("Light extensions are not supported by the import preflight")

    def check_references(value, depth=0):
        if depth > 64:
            raise ValueError("GLB JSON nesting exceeds the import budget")
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "extensions":
                    if not isinstance(child, dict):
                        raise ValueError("GLB extensions must be an object")
                    if compressed.intersection(child):
                        raise ValueError(
                            "Compressed geometry is not supported by the import preflight")
                if key == "uri" and (not isinstance(child, str) or not child.startswith("data:")):
                    raise ValueError("GLB external dependencies are refused")
                check_references(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                check_references(child, depth + 1)

    check_references(document)
    nodes = document["nodes"]
    state = [0] * len(nodes)
    parents = [0] * len(nodes)
    for node in nodes:
        for child in node.get("children", []):
            if type(child) is not int or not 0 <= child < len(nodes):
                raise ValueError("Invalid GLB node hierarchy")
            parents[child] += 1
            if parents[child] > 1:
                raise ValueError("GLB node hierarchy must not have multiple parents")

    def visit(index, depth=0):
        if state[index] == 1 or depth > 128:
            raise ValueError("GLB node hierarchy is cyclic or too deep")
        if state[index] == 2:
            return
        state[index] = 1
        for child in nodes[index].get("children", []):
            visit(child, depth + 1)
        state[index] = 2

    for index in range(len(nodes)):
        visit(index)
    buffers = document.get("buffers", [])
    if (len(buffers) != 1 or "uri" in buffers[0]
            or type(buffers[0].get("byteLength")) is not int
            or not 0 < buffers[0]["byteLength"] <= len(binary)
            or len(binary) - buffers[0]["byteLength"] > 3):
        raise ValueError("GLB must use one embedded binary buffer")
    accessors = document.get("accessors", [])
    components = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
    byte_sizes = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
    allocated = 0
    for accessor in accessors:
        count = accessor.get("count")
        if type(count) is not int or not 0 < count <= 3 * MAX_GEOMETRY:
            raise ValueError("Declared geometry exceeds the import budget")
        kind, component = accessor.get("type"), accessor.get("componentType")
        if kind not in components or component not in byte_sizes:
            raise ValueError("Invalid geometry accessor metadata")
        allocated += count * components[kind] * byte_sizes[component]
    if allocated > MAX_BYTES:
        raise ValueError("Declared geometry exceeds the import budget")

    def accessor_at(index):
        if type(index) is not int or not 0 <= index < len(accessors):
            raise ValueError("Invalid geometry accessor")
        return accessors[index]

    def count_at(index):
        return accessor_at(index)["count"]

    mesh_sizes = []
    mesh_targets = []
    total_morph = 0
    for mesh in document.get("meshes", []):
        vertices = triangles = 0
        target_count = None
        for primitive in mesh.get("primitives", []):
            if primitive.get("mode", 4) != 4:
                raise ValueError("Only triangle geometry is supported")
            attributes = primitive.get("attributes", {})
            if "POSITION" not in attributes:
                raise ValueError("Triangle primitives need a POSITION accessor")
            count = count_at(attributes["POSITION"])
            indices = count_at(primitive["indices"]) if "indices" in primitive else count
            if indices % 3:
                raise ValueError("Triangle geometry has an invalid index count")
            targets = primitive.get("targets")
            if targets is None:
                count_targets = 0
            else:
                if not isinstance(targets, list) or len(targets) > MAX_MORPH_TARGETS:
                    raise ValueError(
                        f"Morph targets are limited to {MAX_MORPH_TARGETS} per primitive")
                count_targets = len(targets)
                for target in targets:
                    if not isinstance(target, dict) or not set(target) <= TARGET_ATTRIBUTES:
                        raise ValueError(
                            "Morph targets support POSITION, NORMAL and TANGENT")
                    for accessor_index in target.values():
                        accessor = accessor_at(accessor_index)
                        if (accessor.get("type") != "VEC3"
                                or accessor.get("componentType") != 5126):
                            raise ValueError(
                                "Morph target deltas must be FLOAT VEC3 accessors")
                        if accessor.get("count") != count:
                            raise ValueError(
                                "Morph target counts must match the position count")
            if target_count is None:
                target_count = count_targets
            elif target_count != count_targets:
                raise ValueError(
                    "All primitives in a mesh need the same morph target count")
            vertices += count
            triangles += indices // 3
        mesh_sizes.append((vertices, triangles))
        mesh_targets.append(target_count or 0)
        total_morph += target_count or 0
    if total_morph > MAX_TOTAL_MORPH_TARGETS:
        raise ValueError(f"Imports are limited to {MAX_TOTAL_MORPH_TARGETS} morph targets")
    for index, mesh in enumerate(document.get("meshes", [])):
        target_count = mesh_targets[index]
        weights = mesh.get("weights")
        if weights is not None and (
                not isinstance(weights, list) or len(weights) != target_count
                or any(type(weight) not in (int, float) or not math.isfinite(weight)
                       or not 0 <= weight <= 1 for weight in weights)):
            raise ValueError("Mesh morph weights must match the target count and range")
        extras = mesh.get("extras")
        names = extras.get("targetNames") if isinstance(extras, dict) else None
        if names is not None and (
                not isinstance(names, list) or len(names) != target_count
                or any(not isinstance(name, str) or not name
                       or len(name.encode()) > 63 for name in names)):
            raise ValueError("Morph target names must match the target count")
    for node in nodes:
        if "weights" in node:
            if "mesh" not in node:
                raise ValueError("Node morph weights need a mesh")
            index = node["mesh"]
            if type(index) is not int or not 0 <= index < len(mesh_targets):
                raise ValueError("Invalid mesh reference")
            weights = node["weights"]
            if (not isinstance(weights, list) or len(weights) != mesh_targets[index]
                    or any(type(weight) not in (int, float) or not math.isfinite(weight)
                           or not 0 <= weight <= 1 for weight in weights)):
                raise ValueError("Node morph weights must match the target count and range")
    skins = document.get("skins", [])
    if not isinstance(skins, list) or len(skins) > MAX_SKINS:
        raise ValueError(f"Imports are limited to {MAX_SKINS} skins")
    total_joints = 0
    for skin in skins:
        if not isinstance(skin, dict):
            raise ValueError("Invalid skin definition")  # noqa: TRY004
        joints = skin.get("joints")
        if not isinstance(joints, list) or not 1 <= len(joints) <= MAX_JOINTS:
            raise ValueError(f"Skins need 1 to {MAX_JOINTS} joints")
        if any(type(joint) is not int or not 0 <= joint < len(nodes) for joint in joints):
            raise ValueError("Skin joint references an invalid node")
        if len(set(joints)) != len(joints):
            raise ValueError("Skins need unique joints")
        total_joints += len(joints)
        if total_joints > MAX_TOTAL_JOINTS:
            raise ValueError(f"Imports are limited to {MAX_TOTAL_JOINTS} joints")
        if "inverseBindMatrices" in skin:
            matrices = accessor_at(skin["inverseBindMatrices"])
            if matrices.get("type") != "MAT4" or matrices.get("componentType") != 5126:
                raise ValueError("Inverse bind matrices must be FLOAT MAT4 accessors")
            if matrices.get("count") != len(joints):
                raise ValueError("Inverse bind matrix count must match the joints")
        if "skeleton" in skin:
            node = skin["skeleton"]
            if type(node) is not int or not 0 <= node < len(nodes):
                raise ValueError("Skin skeleton references an invalid node")
    skinned_meshes = set()
    for node in nodes:
        if "skin" in node:
            index = node["skin"]
            if type(index) is not int or not 0 <= index < len(skins):
                raise ValueError("Invalid skin reference")
            if "mesh" not in node:
                raise ValueError("A skinned node must reference a mesh")
            mesh_index = node["mesh"]
            if type(mesh_index) is not int or not 0 <= mesh_index < len(mesh_sizes):
                raise ValueError("Invalid skinned mesh reference")
            skinned_meshes.add(mesh_index)
    if len(skinned_meshes) > MAX_SKINNED_MESHES:
        raise ValueError(f"Imports are limited to {MAX_SKINNED_MESHES} skinned meshes")
    skinned_vertices = 0
    for index in skinned_meshes:
        if type(index) is not int or not 0 <= index < len(mesh_sizes):
            raise ValueError("Invalid skinned mesh reference")
        for primitive in document["meshes"][index].get("primitives", []):
            attributes = primitive.get("attributes", {})
            if "JOINTS_1" in attributes or "WEIGHTS_1" in attributes:
                raise ValueError("Only four skin influences per vertex are supported")
            if "JOINTS_0" not in attributes or "WEIGHTS_0" not in attributes:
                raise ValueError("Skinned primitives need JOINTS_0 and WEIGHTS_0")
            position = attributes.get("POSITION")
            if type(position) is not int or not 0 <= position < len(accessors):
                raise ValueError("Skinned primitives need a valid POSITION accessor")
            count = accessors[position]["count"]
            joint_accessor = accessor_at(attributes["JOINTS_0"])
            weight_accessor = accessor_at(attributes["WEIGHTS_0"])
            if (joint_accessor.get("type") != "VEC4"
                    or joint_accessor.get("componentType") not in {5121, 5123}):
                raise ValueError("JOINTS_0 must be an unsigned VEC4 accessor")
            if (weight_accessor.get("type") != "VEC4"
                    or weight_accessor.get("componentType") not in {5121, 5123, 5126}):
                raise ValueError("WEIGHTS_0 must be a VEC4 accessor")
            if (weight_accessor.get("componentType") in {5121, 5123}
                    and weight_accessor.get("normalized") is not True):
                raise ValueError("Integer WEIGHTS_0 accessors must be normalized")
            if joint_accessor.get("count") != count or weight_accessor.get("count") != count:
                raise ValueError("Skin attributes must match the position count")
            skinned_vertices += count
    if skinned_vertices > MAX_GEOMETRY:
        raise ValueError("Skinned geometry exceeds the import budget")
    animations = document.get("animations", [])
    if not isinstance(animations, list) or len(animations) > MAX_ANIMATIONS:
        raise ValueError(f"Imports are limited to {MAX_ANIMATIONS} animations")
    total_channels = total_samplers = total_keys = 0
    for animation in animations:
        if not isinstance(animation, dict):
            raise ValueError("Invalid animation definition")  # noqa: TRY004
        channels, samplers = animation.get("channels"), animation.get("samplers")
        if not isinstance(channels, list) or not channels:
            raise ValueError("Animations need at least one channel")
        if not isinstance(samplers, list) or not samplers:
            raise ValueError("Animations need at least one sampler")
        total_channels += len(channels)
        total_samplers += len(samplers)
        if total_channels > MAX_CHANNELS or total_samplers > MAX_CHANNELS:
            raise ValueError(f"Imports are limited to {MAX_CHANNELS} animation channels")
        paths = {}
        for channel in channels:
            if not isinstance(channel, dict):
                raise ValueError("Invalid animation channel")  # noqa: TRY004
            sampler = channel.get("sampler")
            if type(sampler) is not int or not 0 <= sampler < len(samplers):
                raise ValueError("Invalid animation sampler reference")
            target = channel.get("target")
            if not isinstance(target, dict):
                raise ValueError("Invalid animation target")  # noqa: TRY004
            node = target.get("node")
            if type(node) is not int or not 0 <= node < len(nodes):
                raise ValueError("Animation target references an invalid node")
            target_path = target.get("path")
            if target_path not in {"translation", "rotation", "scale", "weights"}:
                raise ValueError(
                    "Animation targets must be translation, rotation, scale or weights")
            target_count = 1
            if target_path == "weights":
                if "mesh" not in nodes[node]:
                    raise ValueError("Weight animation targets need a mesh")
                mesh_index = nodes[node]["mesh"]
                if type(mesh_index) is not int or not 0 <= mesh_index < len(mesh_targets):
                    raise ValueError("Weight animation target references an invalid mesh")
                target_count = mesh_targets[mesh_index]
                if target_count <= 0:
                    raise ValueError("Weight animation targets need morph targets")
            paths.setdefault(sampler, set()).add((target_path, target_count))
        clip_keys = 0
        for index, sampler in enumerate(samplers):
            if not isinstance(sampler, dict):
                raise ValueError("Invalid animation sampler")  # noqa: TRY004
            input_accessor = accessor_at(sampler.get("input"))
            output_accessor = accessor_at(sampler.get("output"))
            if (input_accessor.get("type") != "SCALAR"
                    or input_accessor.get("componentType") != 5126):
                raise ValueError("Animation inputs must be FLOAT SCALAR accessors")
            if output_accessor.get("componentType") != 5126:
                raise ValueError("Animation outputs must be FLOAT accessors")
            count = input_accessor.get("count")
            if type(count) is not int or not 1 <= count <= MAX_KEYS_PER_CLIP:
                raise ValueError(f"Animation clips are limited to {MAX_KEYS_PER_CLIP} keys")
            interpolation = sampler.get("interpolation", "LINEAR")
            if interpolation not in {"LINEAR", "STEP", "CUBICSPLINE"}:
                raise ValueError("Unsupported animation interpolation")
            path_info = None
            if index in paths:
                if len(paths[index]) != 1:
                    raise ValueError("Animation samplers cannot mix target paths")
                path_info = next(iter(paths[index]))
            target_count = path_info[1] if path_info else 1
            expected = count * target_count
            if interpolation == "CUBICSPLINE":
                expected *= 3
            if output_accessor.get("count") != expected:
                raise ValueError("Animation output count does not match its input")
            if path_info is not None:
                target_path = path_info[0]
                expected_type = ("VEC4" if target_path == "rotation"
                                 else "SCALAR" if target_path == "weights" else "VEC3")
                if output_accessor.get("type") != expected_type:
                    raise ValueError("Animation output type does not match its target")
            clip_keys += count
        total_keys += clip_keys
        if total_keys > MAX_TOTAL_KEYS:
            raise ValueError(f"Imports are limited to {MAX_TOTAL_KEYS} animation keys")
    vertices = triangles = 0
    for node in document["nodes"]:
        if "mesh" in node:
            index = node["mesh"]
            if type(index) is not int or not 0 <= index < len(mesh_sizes):
                raise ValueError("Invalid mesh reference")
            vertices += mesh_sizes[index][0]
            triangles += mesh_sizes[index][1]
    if not 0 < vertices <= MAX_GEOMETRY or not 0 < triangles <= MAX_GEOMETRY:
        raise ValueError("Instanced geometry exceeds the import budget")
    if sum(v for v, _ in mesh_sizes) > MAX_GEOMETRY:
        raise ValueError("Declared geometry exceeds the import budget")
    pixels = 0
    images = document.get("images", [])
    buffer_views = document.get("bufferViews", [])
    if not isinstance(images, list) or not isinstance(buffer_views, list):
        raise ValueError("GLB images and bufferViews must be lists")  # noqa: TRY004
    for image in images:
        if not isinstance(image, dict):
            raise ValueError("Invalid GLB image definition")  # noqa: TRY004
        if "uri" in image:
            uri = image["uri"]
            if not isinstance(uri, str) or "," not in uri:
                raise ValueError("Embedded image must be PNG or JPEG")
            header, encoded = uri.split(",", 1)
            if header not in {"data:image/png;base64", "data:image/jpeg;base64"}:
                raise ValueError("Embedded image must be PNG or JPEG")
            try:
                image_data = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise ValueError("Embedded image is not valid base64") from exc
        else:
            index = image.get("bufferView")
            if type(index) is not int or not 0 <= index < len(buffer_views):
                raise ValueError("Invalid embedded image buffer view")
            view = buffer_views[index]
            if not isinstance(view, dict):
                raise ValueError("Invalid embedded image buffer view")
            start = view.get("byteOffset", 0)
            length = view.get("byteLength")
            if (view.get("buffer") != 0
                    or type(start) is not int or type(length) is not int
                    or start < 0 or length <= 0 or start + length > len(binary)):
                raise ValueError("Invalid embedded image range")
            image_data = binary[start:start + length]
        width, height = image_size(image_data)
        pixels += width * height
        if not 0 < width <= 4096 or not 0 < height <= 4096 or pixels > 4096 * 4096:
            raise ValueError("Embedded image dimensions exceed the import budget")
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "vertices": vertices, "triangles": triangles, "skins": len(skins),
            "joints": total_joints, "skinned_meshes": len(skinned_meshes),
            "morph_targets": total_morph,
            "shape_key_meshes": sum(1 for count in mesh_targets if count),
            "animations": len(animations), "animation_channels": total_channels,
            "animation_keys": total_keys}


def inspect_fbx(workspace, name):
    root = Path(workspace).expanduser().resolve(strict=True)
    try:
        path = (root / name).resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("FBX does not exist inside the workspace") from exc
    if Path(name).is_absolute() or not path.is_relative_to(root):
        raise ValueError("Input must stay inside the workspace")
    if path.suffix.lower() != ".fbx" or not path.is_file():
        raise ValueError("Input must be an FBX file")
    with path.open("rb") as stream:
        data = stream.read(MAX_FBX_BYTES + 1)
    if not 27 <= len(data) <= MAX_FBX_BYTES:
        raise ValueError("FBX must be at most 64 MiB")
    binary = data.startswith(b"Kaydara FBX Binary")
    ascii_file = data.lstrip().startswith(b";") and b"FBX" in data[:1024]
    if not (binary or ascii_file):
        raise ValueError("Expected an ASCII or binary FBX file")
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "format": "fbx", "binary": binary}


def inspect_obj(workspace, name):
    root = Path(workspace).expanduser().resolve(strict=True)
    try:
        path = (root / name).resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("OBJ does not exist inside the workspace") from exc
    if Path(name).is_absolute() or not path.is_relative_to(root):
        raise ValueError("Input must stay inside the workspace")
    if path.suffix.lower() != ".obj" or not path.is_file():
        raise ValueError("Input must be an OBJ file")
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError("OBJ must be at most 64 MiB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("OBJ must be UTF-8 text") from exc
    vertices = faces = objects = 0
    mtllibs = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        key = parts[0]
        if key == "v":
            vertices += 1
        elif key == "f":
            faces += 1
        elif key == "o":
            objects += 1
        elif key == "mtllib":
            mtllibs.update(part for part in parts[1:] if part)
    if not 0 < vertices <= MAX_GEOMETRY or not 0 < faces <= MAX_GEOMETRY:
        raise ValueError("OBJ geometry exceeds the import budget")
    if len(mtllibs) > 16:
        raise ValueError("OBJ material libraries are limited to 16 files")
    textures = 0
    for item in mtllibs:
        target = (path.parent / item).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError("OBJ material libraries must stay inside the workspace")
        if target.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("OBJ material libraries must be at most 4 MiB")
        try:
            material_text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError("OBJ material libraries must be UTF-8 text") from exc
        for raw in material_text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            key = parts[0].lower()
            if not (key.startswith("map_") or key in {"bump", "disp", "decal", "refl", "norm"}):
                continue
            if len(parts) < 2:
                continue
            texture = (target.parent / parts[-1].strip('"')).resolve()
            if not texture.is_relative_to(root) or not texture.is_file():
                raise ValueError("OBJ textures must stay inside the workspace")
            textures += 1
            if textures > 64:
                raise ValueError("OBJ textures are limited to 64 files")
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "format": "obj", "vertices": vertices, "faces": faces, "objects": objects,
            "mtllibs": sorted(mtllibs), "textures": textures}


def inspect_usd(workspace, name):
    root = Path(workspace).expanduser().resolve(strict=True)
    try:
        path = (root / name).resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("USD does not exist inside the workspace") from exc
    if Path(name).is_absolute() or not path.is_relative_to(root):
        raise ValueError("Input must stay inside the workspace")
    suffix = path.suffix.lower()
    if suffix not in {".usd", ".usda", ".usdc"} or not path.is_file():
        raise ValueError("Input must be a USD file")
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError("USD must be at most 64 MiB")
    binary = data.startswith(b"PXR-USDC")
    text_data = None
    if suffix == ".usdc":
        if not binary:
            raise ValueError("Expected a binary USD container")
    elif suffix == ".usda":
        try:
            text_data = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Expected an ASCII USD file") from exc
        if not text_data.lstrip().startswith("#usda"):
            raise ValueError("Expected an ASCII USD file")
    elif not binary:
        try:
            text_data = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Expected an ASCII or binary USD file") from exc
        if not text_data.lstrip().startswith("#usda"):
            raise ValueError("Expected an ASCII or binary USD file")
    references = 0
    if text_data is not None:
        for match in re.findall(r"@([^@\n]+)@", text_data):
            item = match.strip()
            if not item or item.startswith("anon:"):
                continue
            target = (path.parent / item).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                raise ValueError("USD assets must stay inside the workspace")
            references += 1
            if references > 128:
                raise ValueError("USD assets are limited to 128 references")
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "format": "usd", "binary": binary, "asset_references": references}
