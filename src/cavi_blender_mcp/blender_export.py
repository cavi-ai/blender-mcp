"""Engine-targeted exports: LOD groups, collision, bake pairs, axis presets and USD."""

import re
from contextlib import ExitStack, nullcontext
from pathlib import Path

import bpy

from .blender_bridge import obj, output_file, selected, with_empties
from .naming import COLLISION_PREFIXES, LOD, base_name, pair_base
from .presets import AXIS_PRESETS, USD_AXES

FORMATS = {".fbx", ".glb", ".usd", ".usda", ".usdc"}


def lod_siblings(value):
    base = base_name(value.name)
    pattern = re.compile(re.escape(base) + r"_LOD(\d+)$")
    found = sorted((int(m.group(1)), item) for item in bpy.context.scene.objects
                   if item.type == "MESH" and (m := pattern.match(item.name)))
    if len(found) < 2 or found[0][0] != 0:
        raise ValueError(f"{value.name} needs {base}_LOD0 plus at least one _LODn sibling")
    return [item for _, item in found]


def collision_objects(base):
    pattern = re.compile("^(" + "|".join(COLLISION_PREFIXES) + ")" + re.escape(base) + r"_\d+$")
    found = sorted((item for item in bpy.context.scene.objects
                    if item.type == "MESH" and pattern.match(item.name)), key=lambda x: x.name)
    if not found:
        raise ValueError(f"No UCX_/UBX_/USP_ collision objects for {base}")
    return found


def fbx(path, preset, empties=False, animations=False):
    object_types = {"MESH", "EMPTY", "ARMATURE"} if animations else (
        {"MESH", "EMPTY"} if empties else {"MESH"})
    return bpy.ops.export_scene.fbx(
        filepath=str(path), use_selection=True, object_types=object_types,
        mesh_smooth_type="FACE", use_tspace=True, add_leaf_bones=False,
        bake_anim=animations, bake_anim_use_all_bones=animations,
        bake_anim_use_nla_strips=False, bake_anim_use_all_actions=animations,
        bake_anim_force_startend_keying=animations,
        global_scale=1, path_mode="STRIP", **AXIS_PRESETS[preset])


def usd(path, preset, instances):
    forward, up = USD_AXES[preset]
    return bpy.ops.wm.usd_export(
        filepath=str(path), selected_objects_only=True, export_animation=False,
        export_hair=False, export_lights=False, export_cameras=False, export_materials=True,
        export_uvmaps=True, export_normals=True, use_instancing=instances,
        evaluation_mode="RENDER", export_textures_mode="KEEP",
        convert_orientation=up != "Z", export_global_forward_selection=forward,
        export_global_up_selection=up)


def write(path, objects, selection, preset, instances, empties, animations=False):
    suffix = path.suffix.lower()
    with selected(selection):
        if suffix == ".fbx":
            from .export_instances import instance_meshes

            with instance_meshes(objects) if instances else nullcontext():
                result = fbx(path, preset, empties, animations)
        elif suffix == ".glb":
            result = bpy.ops.export_scene.gltf(
                filepath=str(path), export_format="GLB", use_selection=True,
                export_apply=not animations, export_animations=animations,
                export_skins=animations, export_animation_mode="ACTIONS",
                export_morph=True, export_morph_animation=animations)
        else:
            result = usd(path, preset, instances)
    if "FINISHED" not in result:
        raise RuntimeError("Export did not finish")


def flag(p, key):
    value = p.get(key, False)
    if type(value) is not bool:
        raise ValueError(f"{key} must be boolean")
    return value


def preset_for(p, suffix):
    preset = p.get("axis")
    if preset is not None and preset not in AXIS_PRESETS:
        raise ValueError(f"axis must be one of {sorted(AXIS_PRESETS)}")
    if preset is not None and suffix == ".glb":
        raise ValueError("axis presets apply to FBX and USD; glTF is always +Y up")
    return preset or "unity"


def actions_for(rig):
    found = []
    animation = rig.animation_data
    if animation:
        if animation.action is not None:
            found.append(animation.action)
        for track in animation.nla_tracks:
            for strip in track.strips:
                if strip.type == "META":
                    raise ValueError("Nested META NLA strips are not supported")
                if strip.action is not None and strip.action not in found:
                    found.append(strip.action)
    return found


def shape_key_actions(value):
    keys = value.data.shape_keys
    if keys is None or keys.animation_data is None:
        return []
    found = []
    animation = keys.animation_data
    if animation.action is not None:
        found.append(animation.action)
    for track in animation.nla_tracks:
        for strip in track.strips:
            if strip.type == "META":
                raise ValueError("Nested META NLA strips are not supported")
            if strip.action is not None and strip.action not in found:
                found.append(strip.action)
    return found


def animation_targets(objects):
    armatures, morph = [], []
    for value in objects:
        modifiers = [modifier for modifier in value.modifiers
                     if modifier.type == "ARMATURE" and modifier.object is not None]
        if len(modifiers) > 1:
            raise ValueError("Each animated mesh needs at most one armature modifier")
        if modifiers:
            rig = modifiers[0].object
            if rig.type != "ARMATURE":
                raise ValueError("Animated meshes must bind to an armature")
            if rig not in armatures:
                armatures.append(rig)
        linked = shape_key_actions(value)
        if linked:
            morph.append(value)
        if not modifiers and not linked:
            raise ValueError("Each animated mesh needs an armature or shape-key action")
    return armatures, morph


def export_asset(p):
    if p.get("bake_pair") is not None:
        return bake_pair(p)
    names = p.get("names")
    animations = flag(p, "animations")
    maximum = 64 if animations else 1000
    if not isinstance(names, list) or not 1 <= len(names) <= maximum:
        raise ValueError(f"Provide between 1 and {maximum} mesh names")
    if animations and len(set(names)) != len(names):
        raise ValueError("Animated exports need unique mesh names")
    suffix = Path(p["path"]).suffix.lower()
    if suffix not in FORMATS:
        raise ValueError(f"Expected extension in {sorted(FORMATS)}")
    preset = preset_for(p, suffix)
    lods, collision = flag(p, "lods"), flag(p, "collision")
    instances, empties = flag(p, "preserve_instances"), flag(p, "include_empties")
    if instances and suffix == ".glb":
        raise ValueError("preserve_instances applies to static FBX or USD exports")
    if animations:
        if suffix not in {".fbx", ".glb"}:
            raise ValueError("animations apply to FBX and GLB exports")
        if lods or collision or instances:
            raise ValueError("animations cannot combine with lods, collision or instances")
    objects = []
    for name in names:
        value = obj(name, mesh=True)
        for item in lod_siblings(value) if lods else [value]:
            if item not in objects:
                objects.append(item)
    meshes = list(objects)
    found = []
    if collision:
        for base in dict.fromkeys(base_name(item.name) for item in meshes):
            found += [item for item in collision_objects(base) if item not in objects]
        objects += found
    if animations:
        armatures, morph_meshes = animation_targets(meshes)
        vertices = sum(len(item.data.vertices) for item in meshes)
        triangles = sum(sum(len(face.vertices) - 2 for face in item.data.polygons)
                        for item in meshes)
        if vertices > 100000 or triangles > 200000:
            raise ValueError("Animated exports are limited to 100,000 vertices and 200,000 triangles")
        actions = []
        for rig in armatures:
            if len(rig.data.bones) > 128:
                raise ValueError("Animated exports are limited to 128 bones per armature")
            linked = actions_for(rig)
            if len(linked) > 32:
                raise ValueError("Animated exports are limited to 32 actions")
            actions += [{"name": action.name, "frame_range": list(action.frame_range),
                         "armature": rig.name} for action in linked]
        shape_key_animations = []
        for mesh in morph_meshes:
            linked = shape_key_actions(mesh)
            if len(linked) > 32:
                raise ValueError("Animated exports are limited to 32 shape-key actions")
            shape_key_animations += [
                {"name": action.name, "frame_range": list(action.frame_range),
                 "mesh": mesh.name} for action in linked]
        if not actions and not shape_key_animations:
            raise ValueError("No actions on the exported objects")
        skinned = [item for item in meshes
                   if any(modifier.type == "ARMATURE" for modifier in item.modifiers)]
        selected_objects = objects + armatures
        selection = with_empties(selected_objects) if empties else selected_objects
        with output_file(p["path"], FORMATS) as path:
            write(path, objects, selection, preset, False, empties, animations=True)
        return {"path": str(path), "bytes": path.stat().st_size, "axis": preset,
                "objects": [item.name for item in selected_objects],
                "armatures": [item.name for item in armatures],
                "skinned_meshes": [item.name for item in skinned],
                "morph_meshes": [item.name for item in morph_meshes],
                "animations": actions,
                "shape_key_animations": shape_key_animations}
    selection = with_empties(objects) if empties else list(objects)
    with output_file(p["path"], FORMATS) as path:
        write(path, meshes if instances else objects, selection, preset, instances, empties)
    return {"path": str(path), "bytes": path.stat().st_size, "axis": preset,
            "objects": [item.name for item in objects],
            "lods": [item.name for item in meshes if LOD.search(item.name)] if lods else [],
            "collision": [item.name for item in found]}


def bake_pair(p):
    if any(p.get(k) for k in ("names", "lods", "collision", "preserve_instances",
                              "include_empties", "animations")):
        raise ValueError("bake_pair is exported alone")
    pair = p["bake_pair"]
    if not isinstance(pair, dict) or set(pair) != {"high", "low"}:
        raise ValueError("bake_pair needs high and low name lists")
    path = Path(p["path"])
    if path.suffix.lower() != ".fbx":
        raise ValueError("bake_pair writes FBX files")
    preset = preset_for(p, ".fbx")
    groups = {}
    for role in ("low", "high"):
        names = pair[role]
        if not isinstance(names, list) or not 1 <= len(names) <= 256 or len(set(names)) != len(
            names
        ):
            raise ValueError(f"bake_pair {role} needs 1 to 256 unique names")
        bases = {}
        for name in names:
            value = obj(name, mesh=True)
            base = pair_base(value.name)
            if base in bases:
                raise ValueError(f"Several {role} objects share base {base}; join them first")
            bases[base] = value
        groups[role] = bases
    if set(groups["low"]) != set(groups["high"]):
        raise ValueError("Every low object needs a high object with the same base name")
    if set(pair["low"]) & set(pair["high"]):
        raise ValueError("An object cannot be both low and high")
    plan = []
    for role, bases in groups.items():
        for base, value in bases.items():
            target = f"{base}_{role}"
            if len(target.encode()) > 63:
                raise ValueError(f"{target} exceeds 63 bytes")
            plan.append((value, target, role))
    members = {value for value, _, _ in plan}
    for value, target, _ in plan:
        holder = bpy.data.objects.get(target)
        if holder is not None and holder not in members:
            raise ValueError(f"{target} is used by another object")
    stem = path.with_suffix("")
    outputs = {}
    with ExitStack() as stack:
        for role in ("low", "high"):
            outputs[role] = stack.enter_context(output_file(f"{stem}_{role}.fbx", {".fbx"}))
        stack.enter_context(renamed(plan))
        for role in ("low", "high"):
            objects = [value for value, _, r in plan if r == role]
            write(outputs[role], objects, objects, preset, False, False)
        names = {role: sorted(target for _, target, r in plan if r == role)
                 for role in ("low", "high")}
    return {"axis": preset, "pairs": len(groups["low"]),
            "low": {"path": str(outputs["low"]), "bytes": outputs["low"].stat().st_size,
                    "objects": names["low"]},
            "high": {"path": str(outputs["high"]), "bytes": outputs["high"].stat().st_size,
                     "objects": names["high"]}}


class renamed:
    """Temporarily rename objects and single-user meshes; restores on exit."""

    def __init__(self, plan):
        self.plan = plan
        self.saved = []

    def apply(self, pairs):
        for index, (item, _) in enumerate(pairs):
            item.name = f"__cavi_pair_{index}"
        for item, label in pairs:
            item.name = label
            if item.name != label:
                raise RuntimeError(f"Could not name {label}")

    def __enter__(self):
        objects = [(value, target) for value, target, _ in self.plan]
        meshes = [(value.data, target) for value, target, _ in self.plan
                  if value.data.users == 1 and (target not in bpy.data.meshes
                                                or bpy.data.meshes[target] is value.data)]
        self.saved = [(item, item.name) for item, _ in objects + meshes]
        try:
            self.apply(objects)
            self.apply(meshes)
        except Exception:
            self.__exit__()
            raise
        return self

    def __exit__(self, *_):
        for index, (item, _) in enumerate(self.saved):
            item.name = f"__cavi_restore_{index}"
        for item, label in self.saved:
            item.name = label
