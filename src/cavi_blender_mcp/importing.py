"""Preflight self-contained static GLB files before Blender allocates their data."""

import base64
import hashlib
import json
import struct
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024
MAX_GEOMETRY = 500_000


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
    document = json.loads(bytes(chunks[0][1]))
    binary = chunks[1][1]
    if not isinstance(document, dict) or document.get("asset", {}).get("version") != "2.0":
        raise ValueError("Expected glTF 2.0 in the GLB")
    if any(document.get(key) for key in ["animations", "skins", "cameras"]):
        raise ValueError("Only static mesh GLB imports are supported")
    if len(document.get("scenes", [])) != 1 or not 0 < len(document.get("nodes", [])) <= 1000:
        raise ValueError("Static GLB requires one scene and at most 1000 nodes")
    compressed = {"KHR_draco_mesh_compression", "EXT_meshopt_compression"}
    if compressed.intersection(document.get("extensionsUsed", [])):
        raise ValueError("Compressed geometry is not supported by the import preflight")

    def check_references(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "extensions" and compressed.intersection(child):
                    raise ValueError("Compressed geometry is not supported by the import preflight")
                if key == "uri" and (not isinstance(child, str) or not child.startswith("data:")):
                    raise ValueError("GLB external dependencies are refused")
                check_references(child)
        elif isinstance(value, list):
            for child in value:
                check_references(child)

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
        allocated += count * components[accessor["type"]] * byte_sizes[accessor["componentType"]]
    if allocated > MAX_BYTES:
        raise ValueError("Declared geometry exceeds the import budget")

    def count_at(index):
        if type(index) is not int or not 0 <= index < len(accessors):
            raise ValueError("Invalid geometry accessor")
        return accessors[index]["count"]

    mesh_sizes = []
    for mesh in document.get("meshes", []):
        vertices = triangles = 0
        for primitive in mesh.get("primitives", []):
            if primitive.get("mode", 4) != 4 or primitive.get("targets"):
                raise ValueError("Only static triangle geometry is supported")
            count = count_at(primitive["attributes"]["POSITION"])
            indices = count_at(primitive["indices"]) if "indices" in primitive else count
            if indices % 3:
                raise ValueError("Triangle geometry has an invalid index count")
            vertices += count
            triangles += indices // 3
        mesh_sizes.append((vertices, triangles))
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
    for image in document.get("images", []):
        if "uri" in image:
            header, encoded = image["uri"].split(",", 1)
            if header not in {"data:image/png;base64", "data:image/jpeg;base64"}:
                raise ValueError("Embedded image must be PNG or JPEG")
            image_data = base64.b64decode(encoded, validate=True)
        else:
            view = document["bufferViews"][image["bufferView"]]
            start, length = view.get("byteOffset", 0), view["byteLength"]
            if view.get("buffer") != 0 or start < 0 or length <= 0 or start + length > len(binary):
                raise ValueError("Invalid embedded image range")
            image_data = binary[start:start + length]
        width, height = image_size(image_data)
        pixels += width * height
        if not 0 < width <= 4096 or not 0 < height <= 4096 or pixels > 4096 * 4096:
            raise ValueError("Embedded image dimensions exceed the import budget")
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "vertices": vertices, "triangles": triangles}
