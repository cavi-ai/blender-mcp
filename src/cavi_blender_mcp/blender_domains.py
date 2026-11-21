"""Geometry graphs, compositor nodes, rigid bodies, particles, hair and volumes."""

import math
import os
import tempfile
from pathlib import Path

import bpy
from mathutils import Vector

from .blender_lookup import MAX_MODIFIERS, info, new_name, obj, selected
from .importing import workspace_bytes

MAX_GRAPH_NODES = 64
MAX_GRAPH_LINKS = 128
MAX_HAIR_CURVES = 32
MAX_HAIR_POINTS = 8
MAX_PARTICLES = 256
MAX_PHYSICS_FRAMES = 50
MAX_VOXELS = 2_000_000
VDB_LIMIT = 32 * 1024 * 1024
# OpenVDB File.h writes this little-endian magic before any grid.
VDB_MAGIC = 0x56444220
SHAPES = {"BOX", "SPHERE", "CONVEX_HULL"}


def _object_mode():
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before this operation")


def _label(name, existing, what):
    if (not isinstance(name, str) or not name.strip() or len(name.encode("utf-8")) > 63
            or name in existing):
        raise ValueError(f"{what} must be unique, nonempty and at most 63 UTF-8 bytes")
    return name


def _node_type(kind, tree):
    cls = getattr(bpy.types, kind, None) if isinstance(kind, str) else None
    if (not isinstance(cls, type) or not issubclass(cls, bpy.types.Node)
            or not cls.is_registered_node_type() or not cls.poll(tree)):
        raise ValueError("Node type is not available in this node tree: " + str(kind))
    return cls


def _finite_point(point):
    if (not isinstance(point, (list, tuple)) or len(point) != 3
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) for value in point)):
        raise ValueError("Positions must be finite XYZ values")
    return (float(point[0]), float(point[1]), float(point[2]))


def _geometry(name, modifier_name):
    target = obj(name, mesh=True)
    modifier = target.modifiers.get(modifier_name) if isinstance(modifier_name, str) else None
    if modifier is None or modifier.type != "NODES" or modifier.node_group is None:
        raise ValueError("Geometry Nodes modifier is required")
    return target, modifier, modifier.node_group


def _graph(target, tree, modifier):
    return {**info(target), "definition": tree.name, "domain": {
        "kind": "geometry_nodes", "node_group": tree.name, "modifier": modifier.name,
        "nodes": [node.name for node in tree.nodes], "links": len(tree.links)}}


def create_geometry_group(p):
    _object_mode()
    target = obj(p["name"], mesh=True)
    group_name = _label(p.get("new_name"), bpy.data.node_groups, "Node group")
    modifier_name = _label(p.get("modifier") or group_name, target.modifiers, "Modifier")
    if len(target.modifiers) >= MAX_MODIFIERS:
        raise ValueError("Modifier limit reached")
    tree = bpy.data.node_groups.new(group_name, "GeometryNodeTree")
    modifier = None
    try:
        tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        group_in = tree.nodes.new("NodeGroupInput")
        group_out = tree.nodes.new("NodeGroupOutput")
        group_in.name = "Group Input"
        group_out.name = "Group Output"
        tree.links.new(group_in.outputs["Geometry"], group_out.inputs["Geometry"])
        if group_in.name != "Group Input" or group_out.name != "Group Output":
            raise RuntimeError("Geometry group sockets were not named")
        modifier = target.modifiers.new(modifier_name, "NODES")
        if modifier is None:
            raise RuntimeError("Geometry Nodes modifier was not created")
        modifier.node_group = tree
        if modifier.node_group != tree:
            raise RuntimeError("Geometry Nodes group was not attached")
    except Exception:
        if modifier is not None:
            target.modifiers.remove(modifier)
        bpy.data.node_groups.remove(tree)
        raise
    return _graph(target, tree, modifier)


def add_geometry_node(p):
    _object_mode()
    target, modifier, tree = _geometry(p["name"], p.get("modifier"))
    if len(tree.nodes) >= MAX_GRAPH_NODES:
        raise ValueError("Geometry node graphs are limited to 64 nodes")
    name = _label(p.get("new_name"), tree.nodes, "Node")
    cls = _node_type(p.get("node_type"), tree)
    node = tree.nodes.new(cls.bl_rna.identifier)
    try:
        node.name = name
        if node.name != name:
            raise RuntimeError("Geometry node was not named")
    except Exception:
        tree.nodes.remove(node)
        raise
    return _graph(target, tree, modifier)


def link_geometry_node(p):
    _object_mode()
    target, modifier, tree = _geometry(p["name"], p.get("modifier"))
    if len(tree.links) >= MAX_GRAPH_LINKS:
        raise ValueError("Geometry node graphs are limited to 128 links")
    source = tree.nodes.get(p.get("from_node"))
    dest = tree.nodes.get(p.get("to_node"))
    if source is None or dest is None:
        raise ValueError("Link nodes must exist in the geometry group")
    output_name, input_name = p.get("from_socket"), p.get("to_socket")
    if not isinstance(output_name, str) or output_name not in source.outputs:
        raise ValueError("Output socket is not on the source node")
    if not isinstance(input_name, str) or input_name not in dest.inputs:
        raise ValueError("Input socket is not on the destination node")
    link = tree.links.new(source.outputs[output_name], dest.inputs[input_name])
    if (link is None or link.from_node != source or link.to_node != dest
            or link.from_socket.name != output_name or link.to_socket.name != input_name):
        raise RuntimeError("Geometry sockets were not linked")
    return _graph(target, tree, modifier)


def _tree(scene):
    if not hasattr(scene, "compositing_node_group"):
        raise ValueError("This Blender has no scene compositor node group")
    tree = scene.compositing_node_group
    if tree is not None and tree.bl_idname != "CompositorNodeTree":
        raise ValueError("Scene compositor is not a compositor node tree")
    return tree


def _compositor_result(tree):
    return {"name": tree.name, "type": "COMPOSITOR", "node_count": len(tree.nodes),
            "link_count": len(tree.links)}


def compositor(spec):
    _object_mode()
    step = spec.get("step")
    scene = bpy.context.scene
    tree = _tree(scene)
    if step == "add_node":
        if tree is None:
            tree = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
            scene.compositing_node_group = tree
        if len(tree.nodes) >= MAX_GRAPH_NODES:
            raise ValueError("Compositor graphs are limited to 64 nodes")
        name = _label(spec.get("node"), tree.nodes, "Node")
        cls = _node_type(spec.get("node_type"), tree)
        node = tree.nodes.new(cls.bl_rna.identifier)
        try:
            node.name = name
            if node.name != name:
                raise RuntimeError("Compositor node was not named")
        except Exception:
            tree.nodes.remove(node)
            raise
    elif step == "link":
        if tree is None:
            raise ValueError("Scene has no compositor node tree")
        if len(tree.links) >= MAX_GRAPH_LINKS:
            raise ValueError("Compositor graphs are limited to 128 links")
        source = tree.nodes.get(spec.get("from_node"))
        dest = tree.nodes.get(spec.get("to_node"))
        if source is None or dest is None:
            raise ValueError("Link nodes must exist in the compositor")
        output_name, input_name = spec.get("from_socket"), spec.get("to_socket")
        if not isinstance(output_name, str) or output_name not in source.outputs:
            raise ValueError("Output socket is not on the source node")
        if not isinstance(input_name, str) or input_name not in dest.inputs:
            raise ValueError("Input socket is not on the destination node")
        link = tree.links.new(source.outputs[output_name], dest.inputs[input_name])
        if (link is None or link.from_node != source or link.to_node != dest
                or link.from_socket.name != output_name or link.to_socket.name != input_name):
            raise RuntimeError("Compositor sockets were not linked")
    else:
        raise ValueError("Compositor step must be add_node or link")
    return _compositor_result(tree)


def sculpt_stroke(p):
    mesh = obj(p["name"], mesh=True)
    if mesh.data.users > 1:
        raise ValueError("Mesh data is shared; use object_edit make_single_user before editing")
    points = p.get("vertices")
    strength = p.get("amount", 1)
    if not isinstance(points, list) or not 3 <= len(points) <= 32:
        raise ValueError("Sculpt stroke needs 3 to 32 positions")
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not 0 < strength <= 1:
        raise ValueError("Sculpt strength must be in (0, 1]")
    coords = [_finite_point(point) for point in points]
    if bpy.app.background:
        raise ValueError("Sculpt stroke is unavailable in background mode")
    window = bpy.context.window
    area = next((item for item in window.screen.areas if item.type == "VIEW_3D"), None) if window else None
    if area is None:
        raise ValueError("Sculpt needs a 3D viewport")
    region = next(item for item in area.regions if item.type == "WINDOW")
    before = [Vector(vertex.co) for vertex in mesh.data.vertices]
    brush = None
    previous_strength = None
    try:
        with selected([mesh]):
            with bpy.context.temp_override(window=window, area=area, region=region):
                if "FINISHED" not in bpy.ops.object.mode_set(mode="SCULPT"):
                    raise RuntimeError("Could not enter Sculpt mode")
                brush = bpy.context.tool_settings.sculpt.brush
                if brush is None or brush.name != "Draw":
                    raise ValueError("Draw brush is not available")
                previous_strength = brush.strength
                brush.strength = float(strength)
                stroke = []
                for index, location in enumerate(coords):
                    mouse = (region.width * (index + 1) / (len(coords) + 1), region.height / 2)
                    stroke.append({
                        "name": "Draw", "location": location, "mouse": mouse, "mouse_event": mouse,
                        "pressure": 1.0, "size": 50.0, "x_tilt": 0.0, "y_tilt": 0.0,
                        "time": index / max(len(coords) - 1, 1), "is_start": index == 0,
                    })
                if "FINISHED" not in bpy.ops.sculpt.brush_stroke(stroke=stroke, mode="NORMAL"):
                    raise RuntimeError("Sculpt stroke did not finish")
            mesh.data.update()
            moved = max((vertex.co - prior).length
                        for vertex, prior in zip(mesh.data.vertices, before, strict=True))
            if moved < 1e-8:
                raise ValueError("Sculpt stroke did not move the mesh")
    finally:
        if brush is not None and previous_strength is not None:
            brush.strength = previous_strength
    return {**info(mesh), "domain": {"kind": "sculpt", "moved_m": moved}}


def rigid_body(p):
    _object_mode()
    target = obj(p["name"], mesh=True)
    body = p.get("body", "ACTIVE")
    shape = p.get("collision_shape")
    mass = p.get("mass", 1)
    frames = p.get("frames", 0)
    if body not in {"ACTIVE", "PASSIVE"}:
        raise ValueError("Rigid body type must be ACTIVE or PASSIVE")
    if shape not in SHAPES:
        raise ValueError("Collision shape must be BOX, SPHERE or CONVEX_HULL")
    if isinstance(mass, bool) or not isinstance(mass, (int, float)) or not 0.001 <= float(mass) <= 1000:
        raise ValueError("Mass must be from 0.001 to 1000")
    if type(frames) is not int or not 0 <= frames <= MAX_PHYSICS_FRAMES:
        raise ValueError("Physics bake is 0 to 50 frames")
    scene = bpy.context.scene
    if scene.rigidbody_world is None and "FINISHED" not in bpy.ops.rigidbody.world_add():
        raise RuntimeError("Rigid body world was not created")
    with selected([target]):
        if target.rigid_body is None and "FINISHED" not in bpy.ops.rigidbody.object_add():
            raise RuntimeError("Rigid body was not created")
    target.rigid_body.type = body
    target.rigid_body.mass = float(mass)
    target.rigid_body.collision_shape = shape
    location = [float(value) for value in target.matrix_world.translation]
    if frames:
        world = scene.rigidbody_world
        cache = world.point_cache
        previous = (scene.frame_start, scene.frame_end, cache.frame_start, cache.frame_end,
                    scene.frame_current)
        try:
            scene.frame_start = cache.frame_start = 1
            scene.frame_end = cache.frame_end = frames
            if "FINISHED" not in bpy.ops.ptcache.bake_all(bake=True):
                raise RuntimeError("Physics bake did not finish")
            scene.frame_set(frames)
            location = [float(value) for value in target.matrix_world.translation]
        finally:
            scene.frame_start, scene.frame_end, cache.frame_start, cache.frame_end, current = previous
            scene.frame_set(current)
    if target.rigid_body.type != body or target.rigid_body.collision_shape != shape:
        raise RuntimeError("Rigid body settings did not apply")
    return {**info(target), "domain": {
        "kind": "rigid_body", "body": body, "collision_shape": shape, "mass": float(mass),
        "frames": frames, "evaluated_location": location}}


def particle_system(p):
    _object_mode()
    target = obj(p["name"], mesh=True)
    count = p.get("count", 1)
    seed = p.get("seed", 0)
    label = p.get("new_name") or "Particles"
    if type(count) is not int or not 1 <= count <= MAX_PARTICLES:
        raise ValueError("Particle count must be 1 to 256")
    if type(seed) is not int or not 0 <= seed <= 1_000_000:
        raise ValueError("Particle seed must be 0 to 1000000")
    label = _label(label, target.modifiers, "Particle system")
    modifier = target.modifiers.new(label, "PARTICLE_SYSTEM")
    if modifier is None or modifier.type != "PARTICLE_SYSTEM":
        raise RuntimeError("Particle system was not created")
    try:
        system = target.particle_systems[-1]
        system.seed = seed
        settings = system.settings
        settings.count = count
        settings.type = "EMITTER"
        settings.child_type = "NONE"
        settings.emit_from = "FACE"
        settings.frame_start = 1
        settings.frame_end = 1
        settings.lifetime = 1
        if (settings.count != count or system.seed != seed or settings.type != "EMITTER"
                or settings.child_type != "NONE"):
            raise RuntimeError("Particle settings did not apply")
    except Exception:
        target.modifiers.remove(modifier)
        raise
    return {**info(target), "domain": {
        "kind": "particles", "name": system.name, "count": settings.count, "seed": system.seed}}


def hair_curves(p):
    _object_mode()
    parent = obj(p["name"], mesh=True)
    label = new_name(p.get("new_name"))
    if label in bpy.data.hair_curves:
        raise ValueError("Hair data name already exists")
    strands = p.get("curves")
    if not isinstance(strands, list) or not 1 <= len(strands) <= MAX_HAIR_CURVES:
        raise ValueError("Hair needs 1 to 32 curves")
    sizes, points = [], []
    for strand in strands:
        if not isinstance(strand, (list, tuple)) or not 2 <= len(strand) <= MAX_HAIR_POINTS:
            raise ValueError("Each hair curve needs 2 to 8 points")
        sizes.append(len(strand))
        points.extend(_finite_point(point) for point in strand)
    data = bpy.data.hair_curves.new(label)
    curves = bpy.data.objects.new(label, data)
    try:
        if data.name != label or curves.name != label:
            raise RuntimeError("Hair object was not named")
        bpy.context.scene.collection.objects.link(curves)
        data.add_curves(sizes)
        if len(data.curves) != len(sizes) or len(data.points) != len(points):
            raise RuntimeError("Hair curves were not created")
        for point, co in zip(data.points, points, strict=True):
            point.position = co
        curves.parent = parent
        if curves.parent != parent:
            raise RuntimeError("Hair was not parented")
    except Exception:
        bpy.data.objects.remove(curves, do_unlink=True)
        bpy.data.hair_curves.remove(data)
        raise
    return {**info(curves), "domain": {
        "kind": "hair", "curves": len(data.curves), "points": len(data.points), "parent": parent.name}}


def volume_to_mesh(p):
    _object_mode()
    target = obj(p["name"], mesh=True)
    source = obj(p.get("source"))
    resolution = p.get("resolution")
    if source.type != "VOLUME":
        raise ValueError("source must be a volume")
    if type(resolution) is not int or not 8 <= resolution <= 125 or resolution ** 3 > MAX_VOXELS:
        raise ValueError("Volume resolution must be 8 to 125")
    if len(target.modifiers) >= MAX_MODIFIERS or "VolumeMesh" in target.modifiers:
        raise ValueError("VolumeMesh modifier cannot be added")
    modifier = target.modifiers.new("VolumeMesh", "VOLUME_TO_MESH")
    if modifier is None:
        raise RuntimeError("Volume to mesh modifier was not created")
    try:
        modifier.object = source
        modifier.resolution_mode = "VOXEL_AMOUNT"
        modifier.voxel_amount = resolution
        if (modifier.object != source or modifier.resolution_mode != "VOXEL_AMOUNT"
                or modifier.voxel_amount != resolution):
            raise RuntimeError("Volume resolution did not apply")
    except Exception:
        target.modifiers.remove(modifier)
        raise
    return {**info(target), "domain": {
        "kind": "volume_to_mesh", "source": source.name, "resolution": modifier.voxel_amount}}


def _import_name(name):
    if not isinstance(name, str) or not name.strip() or len(name.encode("utf-8")) > 58:
        raise ValueError("Import name must be nonempty and at most 58 UTF-8 bytes")
    if name in bpy.data.collections or any(
            item.name == name or item.name.startswith(name + ".") for item in bpy.data.objects):
        raise ValueError("Import name already exists; choose a new asset name")
    _object_mode()
    return name


def _drop_created(objects, volumes):
    for item in list(set(bpy.data.objects) - objects):
        bpy.data.objects.remove(item, do_unlink=True)
    for item in list(set(bpy.data.volumes) - volumes):
        if item.users == 0:
            bpy.data.volumes.remove(item)


def import_vdb(path, name, workspace):
    label = _import_name(name)
    file_path, data = workspace_bytes(workspace, path, {".vdb"}, "OpenVDB", limit=VDB_LIMIT)
    if len(data) < 8 or int.from_bytes(data[:8], "little") != VDB_MAGIC:
        raise ValueError("Expected an OpenVDB file")
    previous, previous_volumes = set(bpy.data.objects), set(bpy.data.volumes)
    descriptor, temporary = tempfile.mkstemp(prefix=".cavi-import-", suffix=".vdb", dir=file_path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        try:
            if "FINISHED" not in bpy.ops.object.volume_import(
                    filepath=temporary, use_sequence_detection=False, relative_path=False):
                raise ValueError("Volume import did not finish")
            created = set(bpy.data.objects) - previous
            if len(created) != 1 or next(iter(created)).type != "VOLUME":
                raise ValueError("Volume import did not create one volume")
            volume = next(iter(created))
            volume.name = label
            grids = list(volume.data.grids)
            if not grids:
                raise ValueError("Volume file has no grids")
        except Exception:
            _drop_created(previous, previous_volumes)
            raise
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {**info(volume), "domain": {"kind": "volume", "grids": [grid.name for grid in grids][:32]}}


HANDLERS = {
    "create_geometry_group": create_geometry_group,
    "add_geometry_node": add_geometry_node,
    "link_geometry_node": link_geometry_node,
    "sculpt_stroke": sculpt_stroke,
    "rigid_body": rigid_body,
    "particle_system": particle_system,
    "hair_curves": hair_curves,
    "volume_to_mesh": volume_to_mesh,
}
