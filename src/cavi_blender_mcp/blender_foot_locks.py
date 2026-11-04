"""Independent sampled rig copies with editable two-bone contact anchors."""

import math

import bpy
from mathutils import Vector

from .blender_bridge import info, new_name, vector
from .blender_errors import preflight
from .blender_rig import action_context
from .blender_rig_bake import bake
from .blender_rig_contacts import contact_frames
from .blender_rig_controls import armature
from .blender_rigging import label

CONTACT_KEYS = {
    "bone",
    "point",
    "start_frame",
    "end_frame",
    "samples",
    "max_drift_m",
    "max_height_error_m",
    "ground_z_m",
}
LOCK_KEYS = {"pole", "pole_angle_degrees", "blend_in_frames", "blend_out_frames"}


def prepare(rig, source, windows, name):
    if not isinstance(windows, list) or not 1 <= len(windows) <= 16:
        raise ValueError("foot_locks needs 1 to 16 declared windows")
    unit = bpy.context.scene.unit_settings.scale_length
    if not math.isfinite(unit) or unit <= 0:
        raise ValueError("Contact locks need a finite positive metre scale")
    parsed = []
    for index, spec in enumerate(windows):
        if not isinstance(spec, dict) or set(spec) - CONTACT_KEYS - LOCK_KEYS:
            raise ValueError("Invalid foot-lock fields")
        contact = {key: value for key, value in spec.items() if key in CONTACT_KEYS}
        contact_frames(rig, source, contact)
        foot = rig.pose.bones[contact["bone"]]
        lower = foot.parent
        upper = lower.parent if lower else None
        if upper is None or (foot.bone.head_local - lower.bone.tail_local).length > 1e-5:
            raise ValueError("Contact foot needs a two-bone parent chain ending at its head")
        pole = vector(spec.get("pole"))
        angle = spec.get("pole_angle_degrees", 0)
        if type(angle) not in (int, float) or not math.isfinite(angle):
            raise ValueError("pole_angle_degrees must be finite")
        blend_in, blend_out = spec.get("blend_in_frames", 3), spec.get("blend_out_frames", 3)
        if any(type(x) is not int or not 1 <= x <= 1000 for x in (blend_in, blend_out)):
            raise ValueError("Contact blends must span 1 to 1000 frames")
        begin = max(source.frame_range[0], contact["start_frame"] - blend_in)
        end = min(source.frame_range[1], contact["end_frame"] + blend_out)
        chain = {lower.name, upper.name}
        for previous in parsed:
            if chain & previous["chain"] and max(begin, previous["begin"]) < min(
                end, previous["end"]
            ):
                raise ValueError("Overlapping contact blends share an IK chain")
        prefix = name.encode()[:35].decode("utf-8", "ignore") + f"_Lock{index:02}"
        parsed.append(
            {
                "contact": contact,
                "pole": pole,
                "angle": angle,
                "begin": begin,
                "end": end,
                "chain": chain,
                "lower": lower.name,
                "foot": foot.name,
                "index": index,
                "anchor": new_name(prefix + "_Anchor"),
                "pole_name": new_name(prefix + "_Pole"),
            }
        )
    return parsed, unit


def influence_keys(action, constraints, item):
    contact = item["contact"]
    start, end = contact["start_frame"], contact["end_frame"]
    keys = {
        action.frame_range[0]: (0, "CONSTANT"),
        action.frame_range[1]: (0, "CONSTANT"),
        item["begin"]: (0, "LINEAR"),
        item["end"]: (0, "CONSTANT"),
        start: (1, "CONSTANT"),
        end: (1, "LINEAR"),
    }
    paths = set()
    for constraint in constraints:
        paths.add(constraint.path_from_id("influence"))
        for frame, (value, _) in sorted(keys.items()):
            constraint.influence = value
            if not constraint.keyframe_insert("influence", frame=frame):
                raise RuntimeError("Could not key contact influence")
    for layer in action.layers:
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", ()):
                for curve in bag.fcurves:
                    if curve.data_path in paths:
                        for point in curve.keyframe_points:
                            point.interpolation = keys[point.co.x][1]


def lock_contacts(p):
    with preflight():
        rig = armature(p.get("name"))
        source = bpy.data.actions.get(label(p.get("source_action"), "source_action"))
        if source is None:
            raise ValueError("Source action does not exist")
        name = label(p.get("action_name"), "action_name")
        if name in bpy.data.actions:
            raise ValueError("Action name already exists")
        parsed, unit = prepare(rig, source, p.get("foot_locks"), name)
        target_name = new_name(p.get("new_name"))
        start, end = source.frame_range
        if start != int(start) or end != int(end) or start < 1:
            raise ValueError(
                "Contact source needs whole-frame clip boundaries starting at frame 1 or later"
            )
    scene = bpy.context.scene
    frame = (scene.frame_current, scene.frame_subframe)
    prepared = None
    objects = []
    constraints = []
    receipts = []
    try:
        with action_context(rig, source):
            prepared = bake(
                {
                    "name": rig.name,
                    "new_name": target_name,
                    "action_name": name,
                    "start_frame": int(start),
                    "end_frame": int(end),
                    "frame_step": p.get("frame_step", 1),
                    "names": p.get("names") or [],
                }
            )
        original = rig
        rig = bpy.data.objects[target_name]
        action = rig.animation_data.action
        anchors = []
        with action_context(rig, action):
            for item in parsed:
                scene.frame_set(item["contact"]["start_frame"])
                bpy.context.view_layer.update()
                evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
                matrix = evaluated.matrix_world @ evaluated.pose.bones[item["foot"]].matrix
                point = matrix @ Vector(item["contact"]["point"])
                matrix.translation.z += item["contact"]["ground_z_m"] / unit - point.z
                if any(not math.isfinite(x) for row in matrix for x in row):
                    raise ValueError("Contact anchor has nonfinite transforms")
                hip = evaluated.matrix_world @ evaluated.pose.bones[item["lower"]].parent.head
                axis = matrix.translation - hip
                offset = Vector(item["pole"]) - hip
                if axis.length < 1e-8 or (offset - offset.project(axis)).length < 1e-6:
                    raise ValueError(
                        "Contact pole must define a bend plane away from the hip-ankle line"
                    )
                anchors.append(matrix)
        for item, matrix in zip(parsed, anchors, strict=True):
            anchor = bpy.data.objects.new(item["anchor"], None)
            objects.append(anchor)
            scene.collection.objects.link(anchor)
            anchor.matrix_world = matrix
            anchor.empty_display_type = "ARROWS"
            anchor.empty_display_size = 0.12
            pole = bpy.data.objects.new(item["pole_name"], None)
            objects.append(pole)
            scene.collection.objects.link(pole)
            pole.location = item["pole"]
            pole.empty_display_size = 0.12
            lower, foot = rig.pose.bones[item["lower"]], rig.pose.bones[item["foot"]]
            ik = lower.constraints.new("IK")
            constraints.append((lower, ik))
            ik.name = f"ContactLock_{item['index']:02}_IK"
            ik.target = anchor
            ik.pole_target = pole
            ik.chain_count = 2
            ik.iterations = 500
            ik.use_stretch = False
            ik.use_tail = True
            ik.pole_angle = math.remainder(math.radians(item["angle"]), math.tau)
            rotation = foot.constraints.new("COPY_ROTATION")
            constraints.append((foot, rotation))
            rotation.name = f"ContactLock_{item['index']:02}_Rotation"
            rotation.target = anchor
            rotation.owner_space = "WORLD"
            rotation.target_space = "WORLD"
            rotation.mix_mode = "REPLACE"
            influence_keys(action, [ik, rotation], item)
            receipts.append(
                {
                    "bone": foot.name,
                    "anchor": anchor.name,
                    "pole": pole.name,
                    "ik_constraint": ik.name,
                    "rotation_constraint": rotation.name,
                    "contact": item["contact"],
                    "blend_range": [item["begin"], item["end"]],
                }
            )
        scene.frame_set(frame[0], subframe=frame[1])
        bpy.context.view_layer.update()
    except Exception:
        owned = (
            []
            if prepared is None
            else [
                bpy.data.objects[prepared["name"]],
                *[bpy.data.objects[item["name"]] for item in prepared["skins"]],
            ]
        )
        data = [(item.type, item.data) for item in owned]
        for item in [*reversed(objects), *owned]:
            bpy.data.objects.remove(item, do_unlink=True)
        for kind, item in data:
            if item.users == 0:
                (bpy.data.meshes if kind == "MESH" else bpy.data.armatures).remove(item)
        if prepared is not None:
            bpy.data.actions.remove(bpy.data.actions[prepared["action"]])
        scene.frame_set(frame[0], subframe=frame[1])
        raise
    return {
        **info(rig),
        "armature": rig.name,
        "action": action.name,
        "source_action": source.name,
        "source": original.name,
        "skins": prepared["skins"],
        "preparation": prepared,
        "locks": receipts,
        "source_action_preserved": True,
        "contact_validation": "required",
    }
