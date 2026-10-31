"""Read-only rig bindings, skin weights and animation QA."""

import math
from contextlib import contextmanager

import bpy
import numpy as np

CHECKS = {"root_motion", "loop", "deformation"}
MAX_SAMPLES = 32
MAX_DEFORMATION_WORK = 2000000


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




def action_slot(rig, action):
    slots = [slot for slot in action.slots if slot.target_id_type == "OBJECT"]
    if not slots:
        raise ValueError("Action has no object slot")
    return next((slot for slot in slots if slot.name_display == rig.name), slots[0])


@contextmanager
def action_context(rig, action):
    if rig.animation_data is None:
        rig.animation_data_create()
    animation = rig.animation_data
    previous_action = animation.action
    previous_slot = animation.action_slot
    scene = bpy.context.scene
    previous_frame = scene.frame_current
    try:
        animation.action = action
        animation.action_slot = action_slot(rig, action)
        yield
    finally:
        animation.action = previous_action
        if previous_action is not None and previous_slot is not None:
            try:
                animation.action_slot = previous_slot
            except (TypeError, RuntimeError):
                pass
        scene.frame_set(previous_frame)


def sample_frames(action, samples):
    start, end = action.frame_range
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError("Action needs a finite non-empty frame range")
    frames = sorted({round(start + (end - start) * index / (samples - 1))
                     for index in range(samples)})
    if len(frames) < 2:
        raise ValueError("Action frame range is too short for sampling")
    return frames


def pose_matrices(rig, frames):
    poses = []
    for frame in frames:
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        poses.append({bone.name: rig.pose.bones[bone.name].matrix.copy()
                      for bone in rig.data.bones})
    return poses


def root_motion_report(rig, action, frames, poses):
    roots = [bone.name for bone in rig.data.bones if bone.parent is None]
    if not roots:
        raise ValueError("Rig has no root bone for root-motion analysis")
    entries = []
    maximum = 0.0
    loop = 0.0
    for name in roots:
        points = [pose[name].translation.copy() for pose in poses]
        start, end = points[0], points[-1]
        displacement = (end - start).length
        horizontal = math.hypot(end.x - start.x, end.y - start.y)
        vertical = abs(end.z - start.z)
        travel = max((point - start).length for point in points)
        maximum = max(maximum, travel)
        loop = max(loop, displacement)
        entries.append({"name": name, "start": list(start), "end": list(end),
                        "displacement": displacement, "horizontal": horizontal,
                        "vertical": vertical, "max_travel": travel})
    return {"action": action.name, "frames": [frames[0], frames[-1]],
            "samples": len(frames), "root_bones": entries,
            "max_travel": maximum, "loop_distance": loop,
            "loops": loop <= 1e-3}


def loop_report(rig, frames, poses):
    first, last = poses[0], poses[-1]
    max_translation = max_rotation = max_scale = 0.0
    worst_bone = None
    worst_kind = None
    for bone in rig.data.bones:
        start, end = first[bone.name], last[bone.name]
        translation = (end.translation - start.translation).length
        rotation = abs(start.to_quaternion().rotation_difference(
            end.to_quaternion()).angle)
        scale = max(abs(a - b) for a, b in zip(start.to_scale(), end.to_scale()))
        if translation > max_translation:
            max_translation, worst_bone, worst_kind = translation, bone.name, "translation"
        if rotation > max_rotation:
            max_rotation, worst_bone, worst_kind = rotation, bone.name, "rotation"
        max_scale = max(max_scale, scale)
    return {"frames": [frames[0], frames[-1]], "max_translation": max_translation,
            "max_rotation_degrees": math.degrees(max_rotation),
            "max_scale_delta": max_scale, "worst_bone": worst_bone,
            "worst_kind": worst_kind,
            "loop_closes": max_translation <= 1e-4 and max_rotation <= 1e-3
            and max_scale <= 1e-4}


def deformation_report(meshes, frames):
    work = sum(len(mesh.data.vertices) for mesh in meshes) * len(frames)
    if work > MAX_DEFORMATION_WORK:
        raise ValueError(f"Deformation sampling exceeds {MAX_DEFORMATION_WORK} vertex samples")
    reports = []
    for mesh in meshes:
        first_dimensions = None
        first_bounds = None
        max_dimensions = np.zeros(3)
        max_ratio = 0.0
        max_centroid = 0.0
        previous_centroid = None
        non_finite = False
        for frame in frames:
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated = mesh.evaluated_get(depsgraph)
            try:
                result = evaluated.to_mesh()
                coordinates = np.empty(len(result.vertices) * 3, np.float64)
                result.vertices.foreach_get("co", coordinates)
                matrix = np.array(evaluated.matrix_world, np.float64)
                world = (coordinates.reshape(-1, 3) @ matrix[:3, :3].T
                         + matrix[:3, 3])
                if not np.isfinite(world).all():
                    non_finite = True
                low, high = world.min(axis=0), world.max(axis=0)
                dimensions = high - low
                centroid = (low + high) / 2
                if first_dimensions is None:
                    first_dimensions = dimensions.copy()
                    first_bounds = (low.copy(), high.copy())
                max_dimensions = np.maximum(max_dimensions, dimensions)
                if first_dimensions.max() > 0:
                    max_ratio = max(max_ratio, float(dimensions.max()
                                                     / first_dimensions.max()))
                if previous_centroid is not None:
                    max_centroid = max(max_centroid,
                                       float(np.linalg.norm(centroid - previous_centroid)))
                previous_centroid = centroid
            finally:
                evaluated.to_mesh_clear()
        size = float(first_dimensions.max()) if first_dimensions is not None else 0.0
        reports.append({
            "name": mesh.name, "vertices": len(mesh.data.vertices),
            "samples": len(frames),
            "dimensions_start": first_dimensions.tolist(),
            "bounds_start": {"min": first_bounds[0].tolist(),
                             "max": first_bounds[1].tolist()},
            "max_dimensions": max_dimensions.tolist(),
            "max_dimension_ratio": max_ratio,
            "max_centroid_movement": max_centroid,
            "non_finite": non_finite,
            "exploded": max_ratio > 5 or max_centroid > max(1e-6, size * 10),
        })
    return reports

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
    requested = params.get("checks") or []
    if (not isinstance(requested, list) or len(set(requested)) != len(requested)
            or any(check not in CHECKS for check in requested)):
        raise ValueError(f"checks must be a list from {sorted(CHECKS)}")
    samples = params.get("samples", 8)
    if type(samples) is not int or not 2 <= samples <= MAX_SAMPLES:
        raise ValueError(f"samples must be an integer from 2 to {MAX_SAMPLES}")
    action_name = params.get("action")
    if action_name is not None and (
            not isinstance(action_name, str) or not action_name
            or len(action_name.encode()) > 63):
        raise ValueError("action must be a nonempty name of at most 63 UTF-8 bytes")
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
    checks_report = None
    analyzed_action = None
    if requested:
        current = rig.animation_data
        action = (bpy.data.actions.get(action_name) if action_name
                  else current.action if current else None)
        if action is None:
            raise ValueError("Action does not exist" if action_name
                             else "No active action to analyze")
        analyzed_action = action.name
        with action_context(rig, action):
            frames = sample_frames(action, samples)
            poses = (pose_matrices(rig, frames)
                     if "root_motion" in requested or "loop" in requested else None)
            checks_report = {}
            if "root_motion" in requested:
                checks_report["root_motion"] = root_motion_report(
                    rig, action, frames, poses)
            if "loop" in requested:
                checks_report["loop"] = loop_report(rig, frames, poses)
            if "deformation" in requested:
                checks_report["deformation"] = deformation_report(meshes, frames)
    not_checked = ["foot sliding", "UV mapping quality", "shader appearance",
                   "Unity import"]
    if "deformation" not in requested:
        not_checked.insert(0, "animation deformation")
    result = {"file": bpy.data.filepath or None, "dirty": bpy.data.is_dirty,
              "blender_version": bpy.app.version_string, "frame": scene.frame_current,
              "fps": scene.render.fps / scene.render.fps_base,
              "armature": rig.name, "pose_position": rig.data.pose_position,
              "root_bones": [b.name for b in rig.data.bones if not b.parent],
              "deform_bones": len(deform), "bones": bones, "meshes": reports,
              "clips": clips, "active_action": animation.action.name
              if animation and animation.action else None,
              "nla_enabled": animation.use_nla if animation else False,
              "not_checked": not_checked}
    if checks_report is not None:
        result["analyzed_action"] = analyzed_action
        result["animation_checks"] = checks_report
    return result
