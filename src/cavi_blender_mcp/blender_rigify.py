"""Rigify metarigs and generated rigs from Blender's bundled Rigify add-on."""

import importlib

import addon_utils
import bpy
from mathutils import Vector

from .blender_bridge import info, new_name, obj, selected, vector
from .blender_rigging import bone_rows

TEMPLATES = {"basic_human": "Basic.basic_human", "basic_quadruped": "Basic.basic_quadruped",
             "human": "human"}
GENERATED = ("objects", "meshes", "armatures", "collections", "texts", "actions")


def rigify():
    """Enable the bundled Rigify add-on; its registration needs a preferences entry."""
    if not addon_utils.check("rigify")[1]:
        addon_utils.enable("rigify", default_set=True, persistent=False)
    if not addon_utils.check("rigify")[1]:
        raise RuntimeError("Blender's bundled Rigify add-on could not be enabled")


def fit(data, target):
    """Scale and place the metarig's edit bones on the target's world bounds; feet at its base."""
    bones = list(data.edit_bones)
    points = [point for bone in bones for point in (bone.head, bone.tail)]
    low = Vector(min(p[i] for p in points) for i in range(3))
    high = Vector(max(p[i] for p in points) for i in range(3))
    corners = [target.matrix_world @ Vector(corner) for corner in target.bound_box]
    bottom = Vector(min(c[i] for c in corners) for i in range(3))
    top = Vector(max(c[i] for c in corners) for i in range(3))
    if high.z - low.z <= 0 or top.z - bottom.z <= 1e-4:
        raise ValueError("source must be a mesh with nonzero height")
    scale = (top.z - bottom.z) / (high.z - low.z)
    pivot = Vector(((low.x + high.x) / 2, (low.y + high.y) / 2, low.z))
    for bone in bones:
        bone.head = (bone.head - pivot) * scale
        bone.tail = (bone.tail - pivot) * scale
        bone.bbone_x *= scale
        bone.bbone_z *= scale
    return Vector(((bottom.x + top.x) / 2, (bottom.y + top.y) / 2, bottom.z))


def add_metarig(p):
    name = new_name(p.get("name"))
    template = p.get("template")
    if template not in TEMPLATES:
        raise ValueError(f"template must be one of {sorted(TEMPLATES)}")
    location, source = p.get("location"), p.get("source")
    if location is not None and source is not None:
        raise ValueError("metarig takes location or source, not both")
    target = None if source is None else obj(source, mesh=True)
    position = vector(location or [0, 0, 0])
    rigify()
    module = importlib.import_module(f"rigify.metarigs.{TEMPLATES[template]}")
    data = bpy.data.armatures.new(name)
    meta = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(meta)
    try:
        with selected([meta]):
            module.create(meta)
            if target is not None:
                position = fit(data, target)
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.data.objects.remove(meta, do_unlink=True)
        bpy.data.armatures.remove(data)
        raise
    meta.location = position
    bpy.context.view_layer.update()
    return {**info(meta), "template": template, "bone_count": len(data.bones),
            "bones": bone_rows(data)}


def generate_rigify(p):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before generating a rig")
    meta = obj(p.get("name"))
    rigify()
    if meta.type != "ARMATURE" or not any(bone.rigify_type for bone in meta.pose.bones):
        raise ValueError("name must be a Rigify metarig")
    rig_name = new_name(p.get("new_name"))
    from rigify import generate

    before = {kind: set(getattr(bpy.data, kind)) for kind in GENERATED}
    settings = meta.data.rigify_rig_basename, meta.data.rigify_target_rig
    meta.data.rigify_rig_basename, meta.data.rigify_target_rig = rig_name, None
    try:
        with selected([meta]):
            generate.generate_rig(bpy.context, meta)
        rig = bpy.data.objects.get(rig_name)
        if rig is None or rig.type != "ARMATURE":
            raise RuntimeError(f"Rigify did not create {rig_name}")
    except Exception as exc:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for kind in GENERATED:
            store = getattr(bpy.data, kind)
            for item in set(store) - before[kind]:
                store.remove(item)
        meta.data.rigify_rig_basename, meta.data.rigify_target_rig = settings
        raise RuntimeError(f"Rigify could not generate {meta.name}: {exc}") from exc
    deform = sorted(bone.name for bone in rig.data.bones if bone.use_deform)
    return {**info(rig), "metarig": meta.name, "bone_count": len(rig.data.bones),
            "deform_bones": deform}


HANDLERS = {"add_metarig": add_metarig, "generate_rigify": generate_rigify}
