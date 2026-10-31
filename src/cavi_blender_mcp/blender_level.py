"""Bounded terrain generation and scene assembly for level building."""

import math
import tempfile
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector
from mathutils.bvhtree import BVHTree

from .blender_bridge import new_name, number, obj, vector
from .blender_geometry import MAX_TRIANGLES, triangle_count
from .textures import read_image

MAX_TERRAIN_RESOLUTION = 501
MAX_PLACEMENTS = 256
MAX_SNAP_OBJECTS = 256
MAX_SCALE = 10000.0


def pair(value, low, high, label):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} requires two components")
    return [number(value[0], low, high, label), number(value[1], low, high, label)]


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer from {low} to {high}")
    return value


def smoothstep(value):
    return value * value * (3 - 2 * value)


def sample(grid, resolution):
    height, width = grid.shape
    x = np.linspace(0, width - 1, resolution)
    y = np.linspace(0, height - 1, resolution)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    tx = smoothstep(x - x0)
    ty = smoothstep(y - y0)
    top = grid[np.ix_(y0, x0)] * (1 - tx) + grid[np.ix_(y0, x1)] * tx
    bottom = grid[np.ix_(y1, x0)] * (1 - tx) + grid[np.ix_(y1, x1)] * tx
    return top * (1 - ty)[:, None] + bottom * ty[:, None]


def noise(resolution, seed, octaves, frequency):
    rng = np.random.default_rng(seed)
    total = np.zeros((resolution, resolution), np.float64)
    amplitude, weight = 1.0, 0.0
    for octave in range(octaves):
        cells = max(2, round(frequency * 2 ** octave))
        lattice = rng.random((cells + 1, cells + 1))
        total += amplitude * sample(lattice, resolution)
        weight += amplitude
        amplitude *= 0.5
    total /= weight
    low, high = float(total.min()), float(total.max())
    if high - low < 1e-9:
        return np.zeros_like(total)
    return (total - low) / (high - low)


def height_image(workspace, name, resolution):
    receipt, payload = read_image(workspace, name)
    with tempfile.TemporaryDirectory(prefix=".cavi-height-", dir=workspace) as folder:
        path = Path(folder) / f"height{Path(name).suffix.lower()}"
        path.write_bytes(payload)
        image = bpy.data.images.load(str(path), check_existing=False)
        try:
            image.colorspace_settings.name = "Non-Color"
            image.reload()
            width, height = image.size
            pixels = np.empty(width * height * 4, np.float32)
            image.pixels.foreach_get(pixels)
        finally:
            bpy.data.images.remove(image)
    grid = pixels.reshape(height, width, 4)
    luminance = (0.2126 * grid[:, :, 0] + 0.7152 * grid[:, :, 1] + 0.0722 * grid[:, :, 2])
    return sample(luminance, resolution), receipt


def mesh_data(resolution, size, height, values):
    count = resolution * resolution
    x = np.linspace(-size[0] / 2, size[0] / 2, resolution)
    y = np.linspace(-size[1] / 2, size[1] / 2, resolution)
    xx, yy = np.meshgrid(x, y)
    vertices = np.column_stack((
        xx.ravel(), yy.ravel(), (values * height).ravel(),
    )).astype(np.float64)
    corners = np.arange(count, dtype=np.int64).reshape(resolution, resolution)
    faces = np.stack((
        corners[:-1, :-1], corners[:-1, 1:], corners[1:, 1:], corners[1:, :-1],
    ), axis=-1).reshape(-1, 4)
    return vertices, faces


def build_mesh(name, resolution, size, height, values):
    vertices, faces = mesh_data(resolution, size, height, values)
    mesh = bpy.data.meshes.new(name)
    try:
        mesh.from_pydata(vertices.tolist(), [], faces.tolist())
        mesh.validate()
        triangles = triangle_count(mesh)
        if not 0 < triangles <= MAX_TRIANGLES:
            raise ValueError(f"Terrain must have 1 to {MAX_TRIANGLES} triangles")
        smooth = np.ones(len(mesh.polygons), dtype=bool)
        mesh.polygons.foreach_set("use_smooth", smooth)
        uv = mesh.uv_layers.new(name="UVMap")
        loops = np.empty(len(mesh.loops), np.int64)
        mesh.loops.foreach_get("vertex_index", loops)
        coordinates = np.empty((len(loops), 2), np.float64)
        coordinates[:, 0] = vertices[loops, 0] / size[0] + 0.5
        coordinates[:, 1] = vertices[loops, 1] / size[1] + 0.5
        uv.data.foreach_set("uv", coordinates.ravel())
        mesh.update()
    except Exception:
        bpy.data.meshes.remove(mesh)
        raise
    return mesh, triangles


def terrain(p, workspace):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before this operation")
    label = new_name(p.get("name"))
    size = pair(p.get("size", [100, 100]), 0.01, 10000, "size")
    height = number(p.get("height", 10), 0.01, 1000, "height")
    resolution = integer(p.get("resolution", 128), 2, MAX_TERRAIN_RESOLUTION, "resolution")
    location = vector(p.get("location") or [0, 0, 0])
    image_name = p.get("image")
    receipt = None
    if image_name is not None:
        if not isinstance(image_name, str) or not image_name.strip():
            raise ValueError("image must be a nonempty workspace path")
        values, receipt = height_image(workspace, image_name, resolution)
    else:
        seed = integer(p.get("seed", 0), 0, 1000000, "seed")
        octaves = integer(p.get("octaves", 4), 1, 8, "octaves")
        frequency = number(p.get("frequency", 4), 1, 64, "frequency")
        values = noise(resolution, seed, octaves, frequency)
    mesh, triangles = build_mesh(label, resolution, size, height, values)
    value = bpy.data.objects.new(label, mesh)
    try:
        bpy.context.collection.objects.link(value)
        value.location = location
    except Exception:
        bpy.data.objects.remove(value, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise
    result = {
        "name": value.name,
        "resolution": resolution,
        "size": size,
        "height": height,
        "minimum": float(values.min() * height),
        "maximum": float(values.max() * height),
        "vertices": len(mesh.vertices),
        "triangles": triangles,
        "source": "image" if receipt is not None else "noise",
    }
    if receipt is not None:
        result["image"] = receipt
    return result


def placement_specs(items):
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_PLACEMENTS:
        raise ValueError(f"placements must contain 1 to {MAX_PLACEMENTS} entries")
    seen = set()
    specs = []
    for item in items:
        source = item.get("source")
        label = item.get("name")
        source_object = obj(source, mesh=True)
        new_name(label)
        if label in seen:
            raise ValueError(f"{label} appears more than once")
        seen.add(label)
        location = vector(item.get("location") or [0, 0, 0])
        rotation = vector(item.get("rotation_degrees") or [0, 0, 0])
        scale = vector(item.get("scale") or [1, 1, 1])
        if any(not 0 < part <= MAX_SCALE for part in scale):
            raise ValueError(f"scale components must be from 0 to {MAX_SCALE}")
        linked = item.get("linked", False)
        if type(linked) is not bool:
            raise ValueError("linked must be boolean")
        specs.append({
            "source": source_object,
            "name": label,
            "location": location,
            "rotation": rotation,
            "scale": scale,
            "linked": linked,
        })
    return specs


def target_collection(name):
    if name is None:
        return None
    if not isinstance(name, str) or not name.strip() or len(name.encode()) > 63:
        raise ValueError("collection must name at most 63 UTF-8 bytes")
    collection = bpy.data.collections.get(name)
    created = collection is None
    if collection is None:
        collection = bpy.data.collections.new(name)
    if collection not in bpy.context.scene.collection.children_recursive:
        bpy.context.scene.collection.children.link(collection)
    return collection, created


def place(p):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before this operation")
    specs = placement_specs(p.get("placements"))
    target = target_collection(p.get("collection"))
    collection, created_collection = target if target else (None, False)
    created = []
    try:
        for spec in specs:
            source = spec["source"]
            copy = source.copy()
            if not spec["linked"] and copy.data is not None:
                copy.data = copy.data.copy()
            owner = collection or (source.users_collection or [bpy.context.scene.collection])[0]
            owner.objects.link(copy)
            copy.name = spec["name"]
            copy.matrix_world = Matrix.LocRotScale(
                Vector(spec["location"]),
                Euler([math.radians(v) for v in spec["rotation"]], "XYZ"),
                Vector(spec["scale"]),
            )
            created.append(copy)
    except Exception:
        for item in created:
            data = item.data
            bpy.data.objects.remove(item, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.meshes.remove(data)
        if created_collection and collection is not None and collection.users == 0:
            bpy.data.collections.remove(collection)
        raise
    return {
        "collection": collection.name if collection is not None else None,
        "count": len(created),
        "objects": [{"name": item.name, "source": spec["source"].name,
                     "linked": spec["linked"]} for item, spec in zip(created, specs)],
    }


def snap(p):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before this operation")
    names = p.get("names")
    if not isinstance(names, list) or not 1 <= len(names) <= MAX_SNAP_OBJECTS:
        raise ValueError(f"names must contain 1 to {MAX_SNAP_OBJECTS} objects")
    if len(set(names)) != len(names):
        raise ValueError("names must be unique")
    ground = obj(p.get("terrain"), mesh=True)
    offset = number(p.get("offset", 0), -1000, 1000, "offset")
    align = p.get("align_to_normal", False)
    if type(align) is not bool:
        raise ValueError("align_to_normal must be boolean")
    objects = []
    for name in names:
        value = obj(name)
        if value == ground:
            raise ValueError("Terrain cannot be snapped to itself")
        objects.append(value)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    try:
        tree = BVHTree.FromObject(ground, depsgraph)
    except Exception as exc:
        raise ValueError("Terrain has no evaluable surface") from exc
    corners = [ground.matrix_world @ Vector(corner) for corner in ground.bound_box]
    top = max(point.z for point in corners)
    inverse = ground.matrix_world.inverted()
    normal_matrix = ground.matrix_world.to_3x3().inverted().transposed()
    hits = []
    for value in objects:
        point = value.matrix_world.translation
        origin = inverse @ Vector((point.x, point.y, top + 1))
        direction = (inverse.to_3x3() @ Vector((0, 0, -1))).normalized()
        hit, normal, _, _ = tree.ray_cast(origin, direction, 1e6)
        if hit is None:
            raise ValueError(f"No terrain surface below {value.name}")
        world = ground.matrix_world @ hit
        normal = (normal_matrix @ normal).normalized()
        hits.append((value, world, normal))
    previous = [value.matrix_world.copy() for value, _, _ in hits]
    report = []
    try:
        for value, world, normal in hits:
            location = Vector((value.matrix_world.translation.x,
                               value.matrix_world.translation.y, world.z + offset))
            if align:
                up = normal
                forward = value.matrix_world.to_3x3() @ Vector((0, 1, 0))
                forward -= up * forward.dot(up)
                if forward.length < 1e-6:
                    forward = value.matrix_world.to_3x3() @ Vector((1, 0, 0))
                    forward -= up * forward.dot(up)
                if forward.length < 1e-6:
                    forward = up.orthogonal()
                forward.normalize()
                right = forward.cross(up).normalized()
                rotation = Matrix((right, forward, up)).transposed().to_quaternion()
                matrix = Matrix.LocRotScale(location, rotation, value.matrix_world.to_scale())
            else:
                matrix = value.matrix_world.copy()
                matrix.translation = location
            value.matrix_world = matrix
            report.append({"name": value.name, "surface": list(world),
                           "normal": list(normal)})
    except Exception:
        for (value, _, _), matrix in zip(hits, previous):
            value.matrix_world = matrix
        raise
    return {"terrain": ground.name, "offset": offset, "aligned": align, "objects": report}


HANDLERS = {
    "create_terrain": terrain,
    "place_objects": place,
    "snap_to_surface": snap,
}
