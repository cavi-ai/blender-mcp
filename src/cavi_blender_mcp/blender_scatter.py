"""Fixed, code-defined Geometry Nodes scatter; no caller-authored node graphs."""

import math

import bpy
import numpy as np

from .blender_bridge import MAX_MODIFIERS, number, obj
from .blender_geometry import MAX_TRIANGLES, triangle_count

MAX_INSTANCES = 100000
MAX_REALIZED_TRIANGLES = 2000000


def areas(value, mesh):
    local = np.empty(len(mesh.polygons), np.float64)
    mesh.polygons.foreach_get("area", local)
    mesh.calc_loop_triangles()
    verts = np.empty(len(mesh.loop_triangles) * 3, np.int64)
    mesh.loop_triangles.foreach_get("vertices", verts)
    co = np.empty(len(mesh.vertices) * 3, np.float64)
    mesh.vertices.foreach_get("co", co)
    matrix = np.array(value.matrix_world, np.float64)
    tri = (co.reshape(-1, 3) @ matrix[:3, :3].T)[verts].reshape(-1, 3, 3)
    world = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2
    return float(local.sum()), float(world.sum())


def build(label, density, distance, seed, scale, jitter, realize):
    tree = bpy.data.node_groups.new(label, "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = tree.nodes, tree.links
    source, sink = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    points = nodes.new("GeometryNodeDistributePointsOnFaces")
    if distance > 0:
        points.distribute_method = "POISSON"
        points.inputs["Distance Min"].default_value = distance
        points.inputs["Density Max"].default_value = density
    else:
        points.inputs["Density"].default_value = density
    points.inputs["Seed"].default_value = seed
    spin, size = nodes.new("FunctionNodeRandomValue"), nodes.new("FunctionNodeRandomValue")
    for node, low, high, offset in ((spin, 0, math.radians(jitter), 1),
                                    (size, scale[0], scale[1], 2)):
        node.data_type = "FLOAT"
        node.inputs["Min"].default_value, node.inputs["Max"].default_value = low, high
        node.inputs["Seed"].default_value = seed + offset
    axis = nodes.new("ShaderNodeCombineXYZ")
    euler = nodes.new("FunctionNodeEulerToRotation")
    pool = nodes.new("GeometryNodeCollectionInfo")
    pool.inputs["Separate Children"].default_value = True
    pool.inputs["Reset Children"].default_value = True
    place = nodes.new("GeometryNodeInstanceOnPoints")
    place.inputs["Pick Instance"].default_value = True
    join = nodes.new("GeometryNodeJoinGeometry")
    surface = nodes.new("GeometryNodeSeparateComponents")
    links.new(source.outputs[0], surface.inputs["Geometry"])
    # Only the top-level mesh; never distribute over earlier instances.
    links.new(surface.outputs["Mesh"], points.inputs["Mesh"])
    links.new(points.outputs["Points"], place.inputs["Points"])
    links.new(spin.outputs["Value"], axis.inputs["Z"])
    links.new(axis.outputs["Vector"], euler.inputs["Euler"])
    links.new(euler.outputs["Rotation"], place.inputs["Rotation"])
    links.new(size.outputs["Value"], place.inputs["Scale"])
    links.new(pool.outputs["Instances"], place.inputs["Instance"])
    result = place.outputs["Instances"]
    if realize:
        flat = nodes.new("GeometryNodeRealizeInstances")
        links.new(result, flat.inputs["Geometry"])
        result = flat.outputs["Geometry"]
    links.new(source.outputs[0], join.inputs["Geometry"])
    links.new(result, join.inputs["Geometry"])
    links.new(join.outputs["Geometry"], sink.inputs[0])
    return tree, pool


def scatter(p):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before this operation")
    target = obj(p["name"], mesh=True)
    if len(target.modifiers) >= MAX_MODIFIERS:
        raise ValueError(f"Modifier stack is limited to {MAX_MODIFIERS}")
    surface = target.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    if not 0 < triangle_count(surface) <= MAX_TRIANGLES:
        raise ValueError(f"Target must have 1 to {MAX_TRIANGLES} evaluated triangles")
    collection = bpy.data.collections.get(p.get("collection") or "")
    if collection is None:
        raise ValueError("Instance collection does not exist")
    members = [item for item in collection.all_objects if item.type == "MESH"]
    if not members or len(collection.all_objects) > 256:
        raise ValueError("Instance collection needs 1 to 256 objects including a mesh")
    if target.name in collection.all_objects:
        raise ValueError("Target cannot be inside its instance collection")
    density = number(p.get("density"), 0.0001, 10000, "density")
    distance = number(p.get("min_distance", 0), 0, 1000, "min_distance")
    seed = p.get("seed", 0)
    if type(seed) is not int or not 0 <= seed <= 1000000:
        raise ValueError("seed must be an integer from 0 to 1000000")
    scale = p.get("scale_range", [1, 1])
    if (not isinstance(scale, list) or len(scale) != 2
            or not 0.01 <= number(scale[0], 0.01, 100, "scale_range") <= number(
                scale[1], 0.01, 100, "scale_range")):
        raise ValueError("scale_range must be [min, max] within 0.01-100")
    jitter = number(p.get("rotation_jitter_degrees", 360), 0, 360, "rotation_jitter_degrees")
    realize = p.get("realize", False)
    if type(realize) is not bool:
        raise ValueError("realize must be boolean")
    local, world = areas(target, surface)
    if local <= 0 or world <= 0:
        raise ValueError("Target has no surface area")
    estimate = int(world * density)
    if estimate > MAX_INSTANCES:
        raise ValueError(f"About {estimate} instances exceed the {MAX_INSTANCES} budget")
    if realize and estimate * max(triangle_count(m.data) for m in members) > (
            MAX_REALIZED_TRIANGLES):
        raise ValueError(f"Realized scatter would exceed {MAX_REALIZED_TRIANGLES} triangles")
    # Distribution runs in local space; convert world density and spacing.
    stretch = math.sqrt(world / local)
    tree, pool = build("CAVI Scatter", density * world / local, distance / stretch, seed,
                       scale, jitter, realize)
    try:
        pool.inputs["Collection"].default_value = collection
        modifier = target.modifiers.new("CAVI Scatter", "NODES")
        modifier.node_group = tree
    except Exception:
        bpy.data.node_groups.remove(tree)
        raise
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = target.evaluated_get(depsgraph)
    instances = triangles = None
    if realize:
        triangles = triangle_count(evaluated.data)
        over = triangles > MAX_REALIZED_TRIANGLES + MAX_TRIANGLES
    else:
        instances = sum(1 for item in depsgraph.object_instances
                        if item.is_instance and item.parent
                        and item.parent.original == target)
        over = instances > MAX_INSTANCES * (1 + len(target.modifiers))
    if over:
        target.modifiers.remove(modifier)
        bpy.data.node_groups.remove(tree)
        raise RuntimeError("Evaluated scatter exceeded its budget; modifier removed")
    return {"name": target.name, "modifier": modifier.name, "node_group": tree.name,
            "collection": collection.name, "estimated_instances": estimate,
            "instances": instances, "evaluated_triangles": triangles, "realize": realize,
            "seed": seed}
