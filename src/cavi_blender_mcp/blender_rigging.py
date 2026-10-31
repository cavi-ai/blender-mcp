"""Armature creation, automatic skin binding and vertex-weight repair."""

import math

import bpy
from mathutils import Vector

from .blender_bridge import info, new_name, number, obj, selected, vector
from .blender_rig import weights

MAX_BONES = 128
MAX_BIND_BONES = 64
MAX_BIND_MESHES = 16
MAX_BIND_VERTICES = 50000
MAX_WEIGHT_VERTICES = 100000
MAX_WEIGHT_GROUPS = 512
MAX_ASSIGNMENTS = 1000000
BONE_KEYS = {"name", "head", "tail", "parent", "connect", "deform", "roll_degrees"}


def label(value, field="name"):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > 63:
        raise ValueError(f"{field} must be nonempty and at most 63 UTF-8 bytes")
    return value


def bones(params):
    specs = params.get("bones")
    if not isinstance(specs, list) or not 1 <= len(specs) <= MAX_BONES:
        raise ValueError(f"bones must list 1 to {MAX_BONES} bone specifications")
    parsed, names = [], set()
    for spec in specs:
        if not isinstance(spec, dict) or not set(spec) <= BONE_KEYS:
            raise ValueError("bones contains an unsupported specification")
        name = label(spec.get("name"))
        if name in names:
            raise ValueError(f"Bone {name} is repeated")
        names.add(name)
        head, tail = vector(spec.get("head")), vector(spec.get("tail"))
        if (Vector(tail) - Vector(head)).length < 1e-6:
            raise ValueError(f"Bone {name} needs a nonzero length")
        parent = spec.get("parent")
        if parent is not None:
            parent = label(parent, "parent")
            if parent == name:
                raise ValueError(f"Bone {name} cannot parent itself")
        connect, deform = spec.get("connect", False), spec.get("deform", True)
        if type(connect) is not bool or type(deform) is not bool:
            raise ValueError("connect and deform must be boolean")
        roll = number(spec.get("roll_degrees", 0), -3600, 3600, "roll_degrees")
        parsed.append({"name": name, "head": head, "tail": tail, "parent": parent,
                       "connect": connect, "deform": deform, "roll_degrees": roll})
    by_name = {spec["name"]: spec for spec in parsed}
    for spec in parsed:
        parent = spec["parent"]
        if parent is not None and parent not in by_name:
            raise ValueError(f"Bone {spec['name']} references missing parent {parent}")
        seen, current = set(), spec["name"]
        while current is not None:
            if current in seen:
                raise ValueError("Bone hierarchy contains a cycle")
            seen.add(current)
            current = by_name[current]["parent"] if current in by_name else None
        if spec["connect"]:
            if parent is None:
                raise ValueError(f"Connected bone {spec['name']} needs a parent")
            if (Vector(spec["head"]) - Vector(by_name[parent]["tail"])).length > 1e-4:
                raise ValueError(f"Connected bone {spec['name']} must start at its parent tail")
    return parsed


def create_armature(p):
    name = new_name(p.get("name"))
    location = vector(p.get("location") or [0, 0, 0])
    specs = bones(p)
    data = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(rig)
    rig.location = location
    rig.show_in_front = True
    data.display_type = "OCTAHEDRAL"
    try:
        with selected([rig]):
            bpy.ops.object.mode_set(mode="EDIT")
            created = {}
            for spec in specs:
                bone = data.edit_bones.new(spec["name"])
                bone.head = spec["head"]
                bone.tail = spec["tail"]
                created[spec["name"]] = bone
            for spec in specs:
                bone = created[spec["name"]]
                if spec["parent"] is not None:
                    bone.parent = created[spec["parent"]]
                    bone.use_connect = spec["connect"]
                bone.use_deform = spec["deform"]
                bone.roll = math.radians(spec["roll_degrees"])
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        bpy.data.objects.remove(rig, do_unlink=True)
        bpy.data.armatures.remove(data)
        raise
    rolls = {spec["name"]: spec["roll_degrees"] for spec in specs}
    return {**info(rig), "bone_count": len(data.bones),
            "bones": [{"name": bone.name,
                       "parent": bone.parent.name if bone.parent else None,
                       "head": list(bone.head_local), "tail": list(bone.tail_local),
                       "deform": bone.use_deform, "connect": bone.use_connect,
                       "roll_degrees": rolls[bone.name]} for bone in data.bones]}


def snapshot(mesh):
    return {"mesh": mesh, "data": mesh.data.copy(), "parent": mesh.parent,
            "parent_type": mesh.parent_type,
            "parent_inverse": mesh.matrix_parent_inverse.copy(),
            "world": mesh.matrix_world.copy()}


def restore(snapshots):
    for snap in reversed(snapshots):
        mesh = snap["mesh"]
        for modifier in list(mesh.modifiers):
            mesh.modifiers.remove(modifier)
        current = mesh.data
        mesh.data = snap["data"]
        if current.users == 0:
            bpy.data.meshes.remove(current)
        mesh.parent = snap["parent"]
        mesh.parent_type = snap["parent_type"]
        mesh.matrix_parent_inverse = snap["parent_inverse"]
        mesh.matrix_world = snap["world"]


def bind_skin(p):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before binding")
    rig = obj(p.get("name"))
    if rig.type != "ARMATURE":
        raise ValueError("name must be an armature object")
    names = p.get("names")
    if (not isinstance(names, list) or not 1 <= len(names) <= MAX_BIND_MESHES
            or len(set(names)) != len(names)):
        raise ValueError(f"names must list 1 to {MAX_BIND_MESHES} unique meshes")
    if len(rig.data.bones) > MAX_BIND_BONES:
        raise ValueError(f"Binding is limited to {MAX_BIND_BONES} bones")
    meshes = [obj(name, mesh=True) for name in names]
    if any(mesh is rig for mesh in meshes):
        raise ValueError("The armature cannot bind itself")
    total = 0
    for mesh in meshes:
        if mesh.data.users != 1:
            raise ValueError("Binding requires single-user mesh data")
        if mesh.data.shape_keys is not None:
            raise ValueError("Binding refuses shape-keyed meshes; remove or apply shape keys")
        if mesh.modifiers:
            raise ValueError("Bind meshes must have no modifiers; apply them first")
        total += len(mesh.data.vertices)
    if total > MAX_BIND_VERTICES:
        raise ValueError(f"Binding is limited to {MAX_BIND_VERTICES} vertices")
    snapshots = [snapshot(mesh) for mesh in meshes]
    try:
        with selected([rig, *meshes]):
            result = bpy.ops.object.parent_set(type="ARMATURE_AUTO", keep_transform=True)
        if "FINISHED" not in result:
            raise RuntimeError("Automatic weight binding did not finish")
        for mesh in meshes:
            bound = [modifier for modifier in mesh.modifiers
                     if modifier.type == "ARMATURE" and modifier.object is rig]
            if len(bound) != 1:
                raise RuntimeError("Automatic binding did not add one armature modifier")
    except Exception:
        restore(snapshots)
        for snap in snapshots:
            if snap["data"].users == 0:
                bpy.data.meshes.remove(snap["data"])
        raise
    for snap in snapshots:
        bpy.data.meshes.remove(snap["data"])
    deform = {bone.name for bone in rig.data.bones if bone.use_deform}
    report = []
    for mesh in meshes:
        report.append({"name": mesh.name, "parent": mesh.parent.name if mesh.parent else None,
                       "vertex_groups": len(mesh.vertex_groups), "armature_modifier": True,
                       "weights": weights(mesh, deform, 4)})
    return {"armature": rig.name, "bone_count": len(rig.data.bones),
            "bindings": len(meshes), "meshes": report}


def repair_weights(p):
    if bpy.context.mode != "OBJECT":
        raise ValueError("Switch Blender to Object Mode before repairing weights")
    mesh = obj(p.get("name"), mesh=True)
    if mesh.data.users != 1:
        raise ValueError("Weight repair requires single-user mesh data")
    rig = mesh.find_armature()
    if rig is None:
        raise ValueError("Skin a mesh with an armature before repairing weights")
    modifiers = [modifier for modifier in mesh.modifiers
                 if modifier.type == "ARMATURE" and modifier.object is rig]
    if len(modifiers) != 1:
        raise ValueError("Weight repair needs one armature modifier bound to the rig")
    if not mesh.vertex_groups:
        raise ValueError("Mesh has no vertex groups to repair")
    if len(mesh.data.vertices) > MAX_WEIGHT_VERTICES:
        raise ValueError(f"Weight repair is limited to {MAX_WEIGHT_VERTICES} vertices")
    if len(mesh.vertex_groups) > MAX_WEIGHT_GROUPS:
        raise ValueError(f"Weight repair is limited to {MAX_WEIGHT_GROUPS} groups")
    if sum(len(vertex.groups) for vertex in mesh.data.vertices) > MAX_ASSIGNMENTS:
        raise ValueError(f"Weight repair is limited to {MAX_ASSIGNMENTS} assignments")
    maximum = p.get("max_influences", 4)
    if type(maximum) is not int or not 1 <= maximum <= 32:
        raise ValueError("max_influences must be an integer from 1 to 32")
    threshold = number(p.get("clean_threshold", 0.0001), 0, 1, "clean_threshold")
    normalize = p.get("normalize", True)
    if type(normalize) is not bool:
        raise ValueError("normalize must be boolean")
    deform = {bone.name for bone in rig.data.bones if bone.use_deform}
    before = weights(mesh, deform, maximum)
    snapshot = mesh.data.copy()
    try:
        with selected([mesh]):
            if threshold > 0:
                result = bpy.ops.object.vertex_group_clean(
                    group_select_mode="BONE_DEFORM", limit=threshold, keep_single=True)
                if "FINISHED" not in result:
                    raise RuntimeError("Weight cleaning did not finish")
            result = bpy.ops.object.vertex_group_limit_total(
                group_select_mode="BONE_DEFORM", limit=maximum)
            if "FINISHED" not in result:
                raise RuntimeError("Weight limiting did not finish")
            if normalize:
                result = bpy.ops.object.vertex_group_normalize_all(
                    group_select_mode="BONE_DEFORM", lock_active=False)
                if "FINISHED" not in result:
                    raise RuntimeError("Weight normalization did not finish")
    except Exception:
        current = mesh.data
        mesh.data = snapshot
        if current.users == 0:
            bpy.data.meshes.remove(current)
        raise
    bpy.data.meshes.remove(snapshot)
    after = weights(mesh, deform, maximum)
    return {**info(mesh), "armature": rig.name, "before": before, "after": after,
            "options": {"max_influences": maximum, "clean_threshold": threshold,
                        "normalize": normalize}}


HANDLERS = {"create_armature": create_armature, "bind_skin": bind_skin,
            "repair_weights": repair_weights}
