"""Fixed, code-defined Geometry Nodes scatter; no caller-authored node graphs."""

import math

import bpy
import numpy as np
from mathutils import Vector

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


def filters(nodes, links, points, up, cos_slope, group):
    """Slope selection against a local up vector and a vertex-group density factor."""
    if up is not None:
        normal, dot = nodes.new("GeometryNodeInputNormal"), nodes.new("ShaderNodeVectorMath")
        dot.operation = "DOT_PRODUCT"
        dot.inputs[1].default_value = up
        compare = nodes.new("FunctionNodeCompare")
        compare.data_type, compare.operation = "FLOAT", "GREATER_EQUAL"
        compare.inputs[1].default_value = cos_slope
        links.new(normal.outputs["Normal"], dot.inputs[0])
        links.new(dot.outputs["Value"], compare.inputs[0])
        links.new(compare.outputs["Result"], points.inputs["Selection"])
    if group is not None:
        weight = nodes.new("GeometryNodeInputNamedAttribute")
        weight.data_type = "FLOAT"
        weight.inputs["Name"].default_value = group
        if points.distribute_method == "POISSON":
            links.new(weight.outputs["Attribute"], points.inputs["Density Factor"])
        else:
            # Random mode has no factor socket; its density input takes the field directly.
            scaled = nodes.new("ShaderNodeMath")
            scaled.operation = "MULTIPLY"
            scaled.inputs[1].default_value = points.inputs["Density"].default_value
            links.new(weight.outputs["Attribute"], scaled.inputs[0])
            links.new(scaled.outputs["Value"], points.inputs["Density"])


def build(label, density, distance, seed, scale, jitter, realize, align=False, up=None,
          cos_slope=None, group=None):
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
    if align:
        # Spin about the aligned local Z, so jitter never tilts instances off the normal.
        turn = nodes.new("FunctionNodeRotateRotation")
        turn.rotation_space = "LOCAL"
        links.new(points.outputs["Rotation"], turn.inputs["Rotation"])
        links.new(euler.outputs["Rotation"], turn.inputs["Rotate By"])
        links.new(turn.outputs["Rotation"], place.inputs["Rotation"])
    else:
        links.new(euler.outputs["Rotation"], place.inputs["Rotation"])
    filters(nodes, links, points, up, cos_slope, group)
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
    realize, align = p.get("realize", False), p.get("align_to_normal", False)
    if type(realize) is not bool or type(align) is not bool:
        raise ValueError("realize and align_to_normal must be boolean")
    group = p.get("density_group")
    if group is not None and target.vertex_groups.get(group) is None:
        raise ValueError("density_group must name a vertex group on the target")
    up = cos_slope = None
    if p.get("max_slope_degrees") is not None:
        slope = number(p["max_slope_degrees"], 0, 90, "max_slope_degrees")
        linear = target.matrix_world.to_3x3()
        lengths = [column.length for column in linear.transposed()]
        # Local face normals keep world angles only under rotation and uniform scale.
        if (min(lengths) <= 0 or max(lengths) - min(lengths) > 1e-6 * max(lengths)
                or abs(abs(linear.determinant()) - lengths[0] ** 3) > 1e-6 * lengths[0] ** 3):
            raise ValueError("max_slope_degrees needs a target with uniform scale and no shear")
        up = tuple((linear.inverted() @ Vector((0, 0, 1))).normalized())
        cos_slope = math.cos(math.radians(slope))
    local, world = areas(target, surface)
    if local <= 0 or world <= 0:
        raise ValueError("Target has no surface area")
    from .blender_geometry import unit_scale

    area_m2 = world * unit_scale() ** 2
    estimate = int(area_m2 * density)
    if estimate > MAX_INSTANCES:
        raise ValueError(f"About {estimate} instances exceed the {MAX_INSTANCES} budget")
    if realize and estimate * max(triangle_count(m.data) for m in members) > (
            MAX_REALIZED_TRIANGLES):
        raise ValueError(f"Realized scatter would exceed {MAX_REALIZED_TRIANGLES} triangles")
    # Distribution runs in local space; convert metre density and scene-unit spacing.
    stretch = math.sqrt(world / local)
    tree, pool = build("CAVI Scatter", density * area_m2 / local, distance / stretch, seed,
                       scale, jitter, realize, align, up, cos_slope, group)
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
            "seed": seed, "align_to_normal": align, "max_slope_degrees": p.get("max_slope_degrees"),
            "density_group": group}
