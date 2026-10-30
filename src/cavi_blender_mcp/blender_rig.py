"""Read-only rig bindings and skin weights; never changes action or pose."""
import math

import bpy


def weights(value, deform, limit):
    groups = {g.index: g.name for g in value.vertex_groups if g.name in deform}
    unweighted, unnormalized, over_limit, invalid = [], [], [], []
    maximum, minimum_sum, maximum_sum = 0, None, None
    for vertex in value.data.vertices:
        entries = [g.weight for g in vertex.groups if g.group in groups]
        if any(not math.isfinite(w) or w < 0 or w > 1 for w in entries):
            invalid.append(vertex.index)
            continue
        positive = [w for w in entries if w > 0]
        total = sum(positive)
        maximum = max(maximum, len(positive))
        minimum_sum = total if minimum_sum is None else min(minimum_sum, total)
        maximum_sum = total if maximum_sum is None else max(maximum_sum, total)
        if not positive:
            unweighted.append(vertex.index)
        elif abs(total - 1) > 1e-4:
            unnormalized.append(vertex.index)
        if len(positive) > limit:
            over_limit.append(vertex.index)
    return {"unweighted_vertices": len(unweighted), "unweighted_sample": unweighted[:16],
            "unnormalized_vertices": len(unnormalized),
            "unnormalized_sample": unnormalized[:16], "invalid_vertices": len(invalid),
            "invalid_sample": invalid[:16], "max_influences": maximum,
            "influence_limit": limit, "over_limit_vertices": len(over_limit),
            "over_limit_sample": over_limit[:16], "sum_min": minimum_sum, "sum_max": maximum_sum,
            "normalization_tolerance": 1e-4,
            "ignored_groups": [g.name for g in value.vertex_groups if g.name not in deform]}


def inspect(params, find_object):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Inspect rigs in Object Mode")
    rig = find_object(params["armature"])
    if rig.type != "ARMATURE":
        raise ValueError("armature must name an armature object")
    names = params.get("meshes")
    if not isinstance(names, list) or not 1 <= len(names) <= 8 or len(set(names)) != len(names):
        raise ValueError("Choose 1 to 8 unique mesh names")
    limit = params.get("max_influences", 4)
    if type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError("max_influences must be an integer from 1 to 32")
    if len(rig.data.bones) > 512:
        raise ValueError("Rig exceeds 512 bones")
    meshes = [find_object(name, mesh=True) for name in names]
    if sum(len(m.data.vertices) for m in meshes) > 100000:
        raise ValueError("Skin inspection exceeds 100000 vertices")
    for value in meshes:
        if len(value.data.loops) > 300000:
            raise ValueError("Skin inspection exceeds 300000 polygon corners per mesh")
        modifiers = list(value.modifiers)
        if (len(modifiers) != 1 or modifiers[0].type != "ARMATURE"
                or modifiers[0].object != rig or not modifiers[0].use_vertex_groups
                or modifiers[0].use_bone_envelopes):
            raise ValueError("Each mesh needs one vertex-group armature modifier bound to this rig")
        if len(value.vertex_groups) > 512 or len(value.material_slots) > 64:
            raise ValueError("Skin exceeds 512 vertex groups or 64 material slots")
    if sum(len(v.groups) for m in meshes for v in m.data.vertices) > 1000000:
        raise ValueError("Skin inspection exceeds 1000000 weight assignments")
    linked = []
    animation = rig.animation_data
    if animation:
        if animation.action:
            linked.append((animation.action, "active", animation.action_slot))
        if sum(len(t.strips) for t in animation.nla_tracks) > 32:
            raise ValueError("Rig exceeds 32 NLA strips")
        for track in animation.nla_tracks:
            for strip in track.strips:
                if strip.type == "META":
                    raise ValueError("Nested META NLA strips need a separate clip inventory")
                if strip.action:
                    linked.append((strip.action, "nla:" + track.name, strip.action_slot))
    if len(linked) > 32:
        raise ValueError("Rig exceeds 32 linked clips")
    clips = [{"name": a.name, "binding": binding, "frame_range": list(a.frame_range),
              "slot": slot.identifier if slot else None}
             for a, binding, slot in linked]
    deform = {bone.name for bone in rig.data.bones if bone.use_deform}
    bones = [{"name": b.name, "parent": b.parent.name if b.parent else None,
              "deform": b.use_deform, "length": b.length,
              "finite_rest_matrix": all(math.isfinite(v) for row in b.matrix_local for v in row),
              "finite_pose_matrix": all(math.isfinite(v) for row in rig.pose.bones[b.name].matrix
                                        for v in row)} for b in rig.data.bones]
    reports = []
    triangles = 0
    for value in meshes:
        value.data.calc_loop_triangles()
        triangles += len(value.data.loop_triangles)
        if triangles > 100000:
            raise ValueError("Skin inspection exceeds 100000 triangles")
        reports.append({"name": value.name, "mesh": value.data.name,
                        "vertices": len(value.data.vertices),
                        "triangles": len(value.data.loop_triangles),
                        "uv_layers": [layer.name for layer in value.data.uv_layers],
                        "shape_keys": value.data.shape_keys is not None,
                        "materials": [s.material.name if s.material else None
                                      for s in value.material_slots],
                        "modifier_enabled": value.modifiers[0].show_viewport,
                        "preserve_volume": value.modifiers[0].use_deform_preserve_volume,
                        "weights": weights(value, deform, limit)})
    scene = bpy.context.scene
    return {"file": bpy.data.filepath or None, "dirty": bpy.data.is_dirty,
            "blender_version": bpy.app.version_string, "frame": scene.frame_current,
            "fps": scene.render.fps / scene.render.fps_base,
            "armature": rig.name, "pose_position": rig.data.pose_position,
            "root_bones": [b.name for b in rig.data.bones if not b.parent],
            "deform_bones": len(deform), "bones": bones, "meshes": reports,
            "clips": clips, "active_action": animation.action.name
            if animation and animation.action else None,
            "nla_enabled": animation.use_nla if animation else False,
            "not_checked": ["animation deformation", "foot sliding", "UV mapping quality",
                            "shader appearance", "Unity import"]}
