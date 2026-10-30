"""Engine-targeted exports: LOD groups, collision, bake pairs, axis presets and USD."""

import re
from contextlib import ExitStack, nullcontext
from pathlib import Path

import bpy

from .blender_bridge import obj, output_file, selected
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


def fbx(path, preset, empties=False):
    return bpy.ops.export_scene.fbx(
        filepath=str(path), use_selection=True,
        object_types={"MESH", "EMPTY"} if empties else {"MESH"},
        mesh_smooth_type="FACE", use_tspace=True, add_leaf_bones=False, bake_anim=False,
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


def write(path, objects, selection, preset, instances, empties):
    suffix = path.suffix.lower()
    with selected(selection):
        if suffix == ".fbx":
            from .export_instances import instance_meshes

            with instance_meshes(objects) if instances else nullcontext():
                result = fbx(path, preset, empties)
        elif suffix == ".glb":
            result = bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB",
                                               use_selection=True, export_apply=True)
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


def export_asset(p):
    if p.get("bake_pair") is not None:
        return bake_pair(p)
    names = p.get("names")
    if not isinstance(names, list) or not 1 <= len(names) <= 1000:
        raise ValueError("Provide between 1 and 1000 mesh names")
    suffix = Path(p["path"]).suffix.lower()
    if suffix not in FORMATS:
        raise ValueError(f"Expected extension in {sorted(FORMATS)}")
    preset = preset_for(p, suffix)
    lods, collision = flag(p, "lods"), flag(p, "collision")
    instances, empties = flag(p, "preserve_instances"), flag(p, "include_empties")
    if instances and suffix == ".glb":
        raise ValueError("preserve_instances applies to static FBX or USD exports")
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
    selection = list(objects)
    if empties:
        for value in objects:
            parent = value.parent
            while parent is not None:
                if (parent.type == "EMPTY" and parent not in selection
                        and parent.name in bpy.context.scene.objects):
                    selection.append(parent)
                parent = parent.parent
    with output_file(p["path"], FORMATS) as path:
        write(path, meshes if instances else objects, selection, preset, instances, empties)
    return {"path": str(path), "bytes": path.stat().st_size, "axis": preset,
            "objects": [item.name for item in objects],
            "lods": [item.name for item in meshes if LOD.search(item.name)] if lods else [],
            "collision": [item.name for item in found]}


def bake_pair(p):
    if any(p.get(k) for k in ("names", "lods", "collision", "preserve_instances",
                              "include_empties")):
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
