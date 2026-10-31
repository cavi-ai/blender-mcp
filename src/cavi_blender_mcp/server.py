"""Typed MCP tools for the Blender bridge."""

from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal

import anyio
from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from .client import BridgeClient
from .generation import generate

mcp = FastMCP(
    "cavi-blender-mcp",
    instructions=(
        "Inspect the scene before editing. Saves and exports refuse existing paths. "
        "Paths are relative to the Blender session workspace. Claim session_control ownership "
        "before edits and pass lease_id. Never retry an uncertain mutation."
    ),
)
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Vector2 = tuple[Number, Number]
Vector3 = tuple[Number, Number, Number]
RGBA = tuple[Number, Number, Number, Number]
ObjectName = Annotated[str, Field(description="Exact object name from scene_info.")]
LeaseId = Annotated[str | None, Field(description="lease_id from session_control claim.")]
MUTATING = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
ADDITIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
LEASE_FREE = frozenset(
    {"scene_info", "object_info", "runtime_status", "session_control", "inspect_mesh_quality",
     "render_preview", "review_sheet", "inspect_rig"}
)
Names = Annotated[list[str], Field(min_length=1, max_length=256)]
Check = Literal["naming", "topology", "lightmap", "transforms", "origin", "materials"]
View = Literal["front", "back", "left", "right", "top", "persp"]
Preserve = Literal["seams", "sharp", "boundary"]
Step = Literal["merge", "delete_loose", "recalc_normals", "triangulate", "clear_custom_normals"]


class NamingRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mesh_prefix: Annotated[str | None, Field(max_length=16)] = None
    lod_suffix: Annotated[str, Field(max_length=32)] = "_LOD{n}"
    collision_prefixes: Annotated[list[str], Field(max_length=8)] = ["UCX_", "UBX_", "USP_"]


class BakePair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    high: Names
    low: Names


class BoneSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=63)]
    head: Vector3
    tail: Vector3
    parent: Annotated[str | None, Field(min_length=1, max_length=63)] = None
    connect: StrictBool = False
    deform: StrictBool = True
    roll_degrees: Number = 0


class PoseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bone: Annotated[str, Field(min_length=1, max_length=63)]
    rotation_degrees: Vector3 | None = None
    location: Vector3 | None = None
    scale: Vector3 | None = None


class KeyframeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frame: Annotated[StrictInt, Field(ge=1, le=1_000_000)]
    poses: Annotated[list[PoseSpec], Field(min_length=1, max_length=128)]


def call(operation_name, **params):
    client = BridgeClient()
    if operation_name not in LEASE_FREE:
        # Legacy bridges reject this envelope instead of ignoring a lease parameter.
        return client.call("owned_edit", {"operation": operation_name, "params": params})
    return client.call(operation_name, params)


async def run(function, *args, **kwargs):
    return await anyio.to_thread.run_sync(partial(function, *args, **kwargs))


def pick(action, values, required=(), defaults=None):
    """Keep only parameters used by the action; refuse unrelated or missing ones."""
    defaults = defaults or {}
    allowed = set(required) | set(defaults)
    extra = sorted(k for k, v in values.items() if v is not None and k not in allowed)
    if extra:
        raise ValueError(f"{action} does not accept: {', '.join(extra)}")
    missing = [k for k in required if values.get(k) is None]
    if missing:
        raise ValueError(f"{action} requires: {', '.join(missing)}")
    chosen = {k: values[k] for k in required}
    chosen.update({k: defaults[k] if values.get(k) is None else values[k] for k in defaults})
    return chosen


@mcp.tool(annotations=READ_ONLY)
async def scene_info(
    name: Annotated[str | None, Field(description="Return only this object's details.")] = None,
    limit: Annotated[StrictInt, Field(ge=1, le=1000)] = 200,
    offset: Annotated[StrictInt, Field(ge=0)] = 0,
) -> dict[str, Any]:
    """Inspect Blender version, file, workspace and a page of scene objects, or one object."""
    if name is not None:
        return await run(call, "object_info", name=name)
    return await run(call, "scene_info", limit=limit, offset=offset)


@mcp.tool(annotations=READ_ONLY)
async def inspect_mesh_quality(
    names: Annotated[list[ObjectName], Field(min_length=1, max_length=32)],
    texture_resolution: tuple[Annotated[StrictInt, Field(ge=1, le=4096)],
                              Annotated[StrictInt, Field(ge=1, le=4096)]] = (1024, 1024),
    uv_layer: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    checks: Annotated[list[Check] | None, Field(max_length=6)] = None,
    naming: NamingRules | None = None,
    lightmap_uv: Annotated[str, Field(min_length=1, max_length=63)] = "UVMap_Lightmap",
    lightmap_resolution: Annotated[StrictInt, Field(ge=16, le=4096)] = 64,
) -> dict[str, Any]:
    """Measure static mesh budgets, texel density, UV stretch and material bindings.

    Uses the render-active UV layer unless named. Refuses modifiers, rigs and shape keys.
    The materials check reports PBR map bindings, color spaces, packing and graph issues.
    """
    return await run(call, "inspect_mesh_quality", names=names,
                     texture_resolution=texture_resolution, uv_layer=uv_layer,
                     checks=checks or [],
                     naming=naming.model_dump() if naming else None,
                     lightmap_uv=lightmap_uv, lightmap_resolution=lightmap_resolution)


@mcp.tool(annotations=READ_ONLY)
async def inspect_rig(
    armature: ObjectName,
    meshes: Annotated[list[ObjectName], Field(min_length=1, max_length=8)],
    max_influences: Annotated[StrictInt, Field(ge=1, le=32)] = 4,
) -> dict[str, Any]:
    """Inspect skin weights, rest bones and linked clips without changing action or pose.

    Exact meshes must each have one vertex-group armature modifier bound to the rig.
    Influence limit is a caller-selected target, not a universal engine requirement.
    This does not validate animation deformation or exported bindings.
    """
    return await run(call, "inspect_rig", armature=armature, meshes=meshes,
                     max_influences=max_influences)


@mcp.tool(annotations=MUTATING)
async def rig_edit(
    action: Literal["create", "bind", "weights", "pose", "keyframe", "clear_pose"],
    name: Annotated[str, Field(description="New armature, armature or skinned mesh.")],
    location: Vector3 | None = None,
    bones: Annotated[list[BoneSpec] | None, Field(min_length=1, max_length=128)] = None,
    names: Annotated[list[str] | None, Field(min_length=1, max_length=16)] = None,
    max_influences: Annotated[StrictInt | None, Field(ge=1, le=32)] = None,
    clean_threshold: Annotated[Number | None, Field(ge=0, le=1)] = None,
    normalize: StrictBool | None = None,
    poses: Annotated[list[PoseSpec] | None, Field(min_length=1, max_length=128)] = None,
    keyframes: Annotated[list[KeyframeSpec] | None, Field(min_length=1, max_length=32)] = None,
    action_name: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    frame: Annotated[StrictInt | None, Field(ge=1, le=1_000_000)] = None,
    reset: StrictBool | None = None,
    lease_id: LeaseId = None,
) -> dict[str, Any]:
    """Create an armature, bind or repair weights, or author an animation.

    create: bones, location=(0,0,0); bind: name=armature, names=meshes;
    weights: name=mesh, max_influences=4, clean_threshold=.0001, normalize=true;
    pose: name=armature, poses, frame, reset=false;
    keyframe: name=armature, action_name, keyframes=[{frame, poses}];
    clear_pose: name=armature, frame.
    """
    values = {"location": location, "bones": bones, "names": names,
              "max_influences": max_influences, "clean_threshold": clean_threshold,
              "normalize": normalize, "poses": poses, "keyframes": keyframes,
              "action_name": action_name, "frame": frame, "reset": reset}
    if action == "create":
        operation = "create_armature"
        params = pick(action, values, ["bones"], {"location": (0, 0, 0)})
        params["bones"] = [bone.model_dump() for bone in params["bones"]]
    elif action == "bind":
        operation = "bind_skin"
        params = pick(action, values, ["names"])
    elif action == "weights":
        operation = "repair_weights"
        params = pick(action, values, (), {
            "max_influences": 4, "clean_threshold": 0.0001, "normalize": True})
    elif action == "pose":
        operation = "pose_rig"
        params = pick(action, values, ["poses"], {"frame": None, "reset": False})
        params["poses"] = [pose.model_dump() for pose in params["poses"]]
    elif action == "keyframe":
        operation = "keyframe_rig"
        params = pick(action, values, ["action_name", "keyframes"])
        params["keyframes"] = [
            {"frame": item.frame, "poses": [pose.model_dump() for pose in item.poses]}
            for item in params["keyframes"]]
    else:
        operation = "clear_pose"
        params = pick(action, values, (), {"frame": None})
    return await run(call, operation, lease_id=lease_id, name=name, **params)


@mcp.tool(annotations=ADDITIVE)
async def render_preview(
    path: Annotated[str, Field(description="New workspace .png path.")],
    resolution: Annotated[StrictInt, Field(description="Square size, 64-2048 px.")] = 512,
    names: Annotated[list[str] | None, Field(min_length=1, max_length=1000,
                                             description="Meshes to isolate.")] = None,
    direction: Annotated[Vector3, Field(description="Camera direction from center.")] = (
        1.5, -2, 1.4),
    color_mode: Literal["material", "vertex"] = "material",
    renderer: Literal["workbench", "eevee"] = "workbench",
    orthographic: StrictBool = False,
) -> Image:
    """Render a PNG preview; restores scene state. No lease needed. Eevee max 1024 px."""
    result = await run(
        call,
        "render_preview",
        path=path,
        resolution=resolution,
        names=names,
        direction=direction,
        color_mode=color_mode,
        renderer=renderer,
        orthographic=orthographic,
    )
    return Image(path=result["path"])


@mcp.tool(annotations=ADDITIVE)
async def session_control(
    action: Literal["inspect", "claim", "renew", "release"],
    owner: Annotated[str | None, Field(max_length=128)] = None,
    expected_project: Annotated[
        str | None, Field(description="Exact project_id from inspect.")
    ] = None,
    lease_id: Annotated[str | None, Field(max_length=128)] = None,
    ttl_seconds: Annotated[StrictInt, Field(ge=30, le=3600)] = 600,
) -> dict[str, Any]:
    """Inspect ownership or claim, renew or release an edit lease.

    Claim returns a private lease_id; pass it on every edit. Expiry and release never
    save, close or discard a project.
    """
    return await run(
        call,
        "session_control",
        action=action,
        owner=owner,
        expected_project=expected_project,
        lease_id=lease_id,
        ttl_seconds=ttl_seconds,
    )


@mcp.tool(annotations=MUTATING)
async def object_edit(
    action: Literal["create_primitive", "create_mesh", "transform", "set_color", "shade",
                    "apply_transforms", "set_origin", "snap_to_grid", "rename", "add_socket",
                    "duplicate", "parent", "unparent", "move_to_collection"],
    name: Annotated[str, Field(description="Object name; new and unique for create_*.")],
    kind: Literal["cube", "sphere", "cylinder", "cone", "plane"] | None = None,
    location: Vector3 | None = None,
    rotation_degrees: Annotated[Vector3 | None, Field(description="XYZ Euler.")] = None,
    scale: Annotated[Vector3 | None, Field(description="Positive.")] = None,
    vertices: Annotated[list[Vector3] | None, Field(min_length=3, max_length=10000)] = None,
    faces: Annotated[
        list[Annotated[list[StrictInt], Field(min_length=3, max_length=64)]] | None,
        Field(min_length=1, max_length=20000, description="Zero-based, outward winding."),
    ] = None,
    rgba: Annotated[RGBA | None, Field(description="Components 0-1.")] = None,
    slot: Annotated[StrictInt | None, Field(ge=0, le=31)] = None,
    smooth: StrictBool | None = None,
    components: Annotated[list[Literal["location", "rotation", "scale"]] | None,
                          Field(min_length=1, max_length=3)] = None,
    make_single_user: StrictBool | None = None,
    origin: Literal["bounds_bottom_center", "bounds_center", "world_origin", "point"] | None = None,
    grid: Annotated[Number | None, Field(ge=0.001, le=100)] = None,
    new_name: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    count: Annotated[StrictInt | None, Field(ge=1, le=256)] = None,
    offset: Vector3 | None = None,
    linked: StrictBool | None = None,
    create: StrictBool | None = None,
    lease_id: LeaseId = None,
) -> dict[str, Any]:
    """Create or edit one object. Params per action:
    create_primitive: kind, location; create_mesh: vertices, faces;
    transform: location, rotation_degrees, scale; set_color: rgba, slot=0; shade: smooth=false;
    apply_transforms: components=[rotation,scale], make_single_user=false;
    set_origin: origin=bounds_bottom_center (point: world location); snap_to_grid: grid;
    rename: new_name; add_socket: new_name, local location, rotation_degrees;
    duplicate: new_name, count=1, offset=(0,0,0), linked=false;
    parent: new_name (parent); unparent: no extra params;
    move_to_collection: new_name (collection), create=true.
    """
    values = {"kind": kind, "location": location, "rotation_degrees": rotation_degrees,
              "scale": scale, "vertices": vertices, "faces": faces, "rgba": rgba, "slot": slot,
              "smooth": smooth, "components": components, "make_single_user": make_single_user,
              "origin": origin, "grid": grid, "new_name": new_name, "count": count,
              "offset": offset, "linked": linked, "create": create}
    operation, params = {
        "create_primitive": ("create_primitive",
                             lambda: pick(action, values, ["kind"], {"location": (0, 0, 0)})),
        "create_mesh": ("create_mesh", lambda: pick(action, values, ["vertices", "faces"])),
        "transform": ("transform_object", lambda: pick(action, values, (), {
            "location": None, "rotation_degrees": None, "scale": None})),
        "set_color": ("set_color", lambda: pick(action, values, ["rgba"], {"slot": 0})),
        "shade": ("shade_mesh", lambda: pick(action, values, (), {"smooth": False})),
        "apply_transforms": ("apply_transforms", lambda: pick(action, values, (), {
            "components": ["rotation", "scale"], "make_single_user": False})),
        "set_origin": ("set_origin", lambda: pick(action, values, (), {
            "origin": "bounds_bottom_center", "location": None})),
        "snap_to_grid": ("snap_to_grid", lambda: pick(action, values, ["grid"])),
        "rename": ("rename_object", lambda: pick(action, values, ["new_name"])),
        "add_socket": ("add_socket", lambda: pick(action, values, ["new_name"], {
            "location": None, "rotation_degrees": None})),
        "duplicate": ("duplicate_object", lambda: pick(action, values, ["new_name"], {
            "count": 1, "offset": (0, 0, 0), "linked": False})),
        "parent": ("parent_object", lambda: pick(action, values, ["new_name"])),
        "unparent": ("unparent_object", lambda: pick(action, values)),
        "move_to_collection": ("move_to_collection", lambda: pick(action, values, ["new_name"], {
            "create": True})),
    }[action]
    return await run(call, operation, lease_id=lease_id, name=name, **params())


@mcp.tool(annotations=MUTATING)
async def mesh_edit(
    action: Literal["modifier", "unwrap", "decimate_to", "remesh_quad", "lod_chain",
                    "lightmap_uv", "texel_density", "collision", "cleanup", "boolean",
                    "join", "separate", "mirror", "array", "solidify"],
    name: ObjectName,
    kind: Literal["bevel", "decimate", "subdivision", "voxel_remesh"] | None = None,
    amount: Annotated[Number | None, Field(
        description="Bevel width (0,100], decimate ratio (0,1], subdivision 1-3, voxel size "
        "[0.005,1].")] = None,
    apply: Annotated[StrictBool | None, Field(description="Bake; needs no modifiers.")] = None,
    angle_limit_degrees: Annotated[Number | None, Field(ge=1, le=89)] = None,
    island_margin: Annotated[Number | None, Field(ge=0, le=0.5)] = None,
    uv_layer: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    target_triangles: Annotated[StrictInt | None, Field(ge=4, le=500000)] = None,
    target_faces: Annotated[StrictInt | None, Field(ge=16, le=100000)] = None,
    symmetry_axis: Literal["X", "Y", "Z"] | None = None,
    preserve: Annotated[list[Preserve] | None, Field(max_length=3)] = None,
    ratios: Annotated[list[Annotated[Number, Field(gt=0, lt=1)]] | None,
                      Field(min_length=1, max_length=6)] = None,
    triangle_targets: Annotated[list[Annotated[StrictInt, Field(ge=4)]] | None,
                                Field(min_length=1, max_length=6)] = None,
    rename_source: StrictBool | None = None,
    lightmap_resolution: Annotated[StrictInt | None, Field(ge=16, le=4096)] = None,
    margin_px: Annotated[Number | None, Field(ge=0, le=64)] = None,
    target_px_per_m: Annotated[Number | None, Field(gt=0, le=100000)] = None,
    texture_resolution: Annotated[StrictInt | None, Field(ge=1, le=4096)] = None,
    pack: StrictBool | None = None,
    shape: Literal["convex", "box", "sphere"] | None = None,
    max_hull_vertices: Annotated[StrictInt | None, Field(ge=4, le=255)] = None,
    merge_distance: Annotated[Number | None, Field(ge=0, le=1)] = None,
    steps: Annotated[list[Step] | None, Field(max_length=5)] = None,
    operand: Annotated[str | None, Field(description="Exact boolean operand mesh.")] = None,
    operation: Literal["union", "difference", "intersect"] | None = None,
    solver: Literal["exact", "fast"] | None = None,
    keep_operand: StrictBool | None = None,
    self_intersection: StrictBool | None = None,
    names: Annotated[list[str] | None, Field(min_length=1, max_length=64)] = None,
    by: Literal["loose_parts", "materials"] | None = None,
    count: Annotated[StrictInt | None, Field(ge=2, le=1000)] = None,
    offset: Vector3 | None = None,
    thickness: Annotated[Number | None, Field(gt=0, le=100)] = None,
    clipping: StrictBool | None = None,
    lease_id: LeaseId = None,
) -> dict[str, Any]:
    """Edit mesh surface. Params per action (defaults after =):
    modifier: kind, amount, apply=false; unwrap: angle_limit_degrees=66, island_margin=.02,
    uv_layer; decimate_to: target_triangles|amount, symmetry_axis, preserve=[seams];
    remesh_quad: target_faces, preserve=[boundary]; lod_chain: ratios=[.5,.25,.125]|
    triangle_targets, rename_source=false, symmetry_axis, preserve; lightmap_uv:
    uv_layer=UVMap_Lightmap, lightmap_resolution=64, margin_px=4; texel_density:
    target_px_per_m, texture_resolution=1024, uv_layer, pack=false; collision: shape=convex,
    max_hull_vertices=32; cleanup: merge_distance=.0001, steps=[merge,delete_loose,recalc_normals];
    boolean: operand, operation, solver=exact, keep_operand=false, self_intersection=false;
    join: names; separate: by=loose_parts; mirror: symmetry_axis=X, merge_distance=.001,
    clipping=false; array: count, offset; solidify: thickness, offset=-1.
    """
    values = {"kind": kind, "amount": amount, "apply": apply,
              "angle_limit_degrees": angle_limit_degrees, "island_margin": island_margin,
              "uv_layer": uv_layer, "target_triangles": target_triangles,
              "target_faces": target_faces, "symmetry_axis": symmetry_axis,
              "preserve": preserve, "ratios": ratios, "triangle_targets": triangle_targets,
              "rename_source": rename_source, "lightmap_resolution": lightmap_resolution,
              "margin_px": margin_px, "target_px_per_m": target_px_per_m,
              "texture_resolution": texture_resolution, "pack": pack, "shape": shape,
              "max_hull_vertices": max_hull_vertices, "merge_distance": merge_distance,
              "steps": steps, "operand": operand, "operation": operation, "solver": solver,
              "keep_operand": keep_operand, "self_intersection": self_intersection,
              "names": names, "by": by, "count": count, "offset": offset,
              "thickness": thickness, "clipping": clipping}
    if action == "modifier":
        operation = "add_modifier"
        params = pick(action, values, ["kind", "amount"], {"apply": False})
    elif action == "unwrap":
        operation = "unwrap_mesh"
        params = pick(action, values, (), {"angle_limit_degrees": 66, "island_margin": 0.02,
                                           "uv_layer": None})
    elif action in {"decimate_to", "lod_chain"}:
        operation = action
        extra = ({"amount": None, "target_triangles": None} if action == "decimate_to" else
                 {"ratios": None, "triangle_targets": None, "rename_source": False})
        params = pick(action, values, (), {**extra, "symmetry_axis": None,
                                           "preserve": ["seams"]})
        params["preserve_seams"] = "seams" in preserved(params.pop("preserve"), {"seams"})
    elif action == "remesh_quad":
        operation = action
        params = pick(action, values, ["target_faces"], {"preserve": ["boundary"]})
        kept = preserved(params.pop("preserve"), {"sharp", "boundary"})
        params.update(preserve_sharp="sharp" in kept, preserve_boundary="boundary" in kept)
    elif action == "lightmap_uv":
        operation = action
        params = pick(action, values, (), {"uv_layer": "UVMap_Lightmap",
                                           "lightmap_resolution": 64, "margin_px": 4,
                                           "angle_limit_degrees": 66})
    elif action == "texel_density":
        operation = action
        params = pick(action, values, ["target_px_per_m"], {
            "texture_resolution": 1024, "uv_layer": None, "pack": False})
    elif action == "boolean":
        operation = "boolean_mesh"
        params = pick(action, values, ["operand", "operation"], {
            "solver": "exact", "keep_operand": False, "self_intersection": False})
    elif action == "join":
        operation = "join_meshes"
        params = pick(action, values, ["names"])
    elif action == "separate":
        operation = "separate_mesh"
        params = pick(action, values, (), {"by": "loose_parts"})
    elif action == "mirror":
        operation = "mirror_mesh"
        params = pick(action, values, (), {
            "symmetry_axis": "X", "merge_distance": 0.001, "clipping": False})
    elif action == "array":
        operation = "array_mesh"
        params = pick(action, values, ["count", "offset"])
    elif action == "solidify":
        operation = "solidify_mesh"
        params = pick(action, values, ["thickness"], {"offset": -1})
    elif action == "collision":
        operation = action
        params = pick(action, values, (), {"shape": "convex", "max_hull_vertices": 32})
    else:
        operation = "cleanup_mesh"
        params = pick(action, values, (), {
            "merge_distance": 0.0001, "steps": ["merge", "delete_loose", "recalc_normals"]})
    return await run(call, operation, lease_id=lease_id, name=name, **params)


def preserved(values, allowed):
    if len(set(values)) != len(values) or not set(values) <= allowed:
        raise ValueError(f"preserve accepts only: {', '.join(sorted(allowed))}")
    return set(values)


@mcp.tool(annotations=MUTATING)
async def assign_material(
    names: Annotated[list[str], Field(min_length=1, max_length=32)],
    material_name: Annotated[str, Field(min_length=1, max_length=63)],
    base_color_texture: Annotated[str | None, Field(description="Workspace sRGB image.")] = None,
    base_color: RGBA | None = None,
    roughness: Number | None = None,
    metallic: Number | None = None,
    roughness_texture: str | None = None,
    metallic_texture: str | None = None,
    normal_texture: str | None = None,
    normal_strength: Number | None = None,
    emission_texture: str | None = None,
    emission_strength: Number | None = None,
    alpha_texture: str | None = None,
    alpha_mode: Literal["opaque", "clip", "blend"] | None = None,
    uv_scale: Vector2 | None = None,
    uv_offset: Vector2 | None = None,
    uv_rotation_degrees: Number | None = None,
    update_existing: StrictBool | None = None,
    slot: Annotated[StrictInt, Field(ge=0, le=31)] = 0,
    lease_id: LeaseId = None,
) -> dict[str, Any]:
    """Assign or update a PBR material. Maps are workspace PNG/JPEG files.

    Normal, roughness, metallic and alpha maps are Non-Color; base color and emission
    are sRGB. update_existing edits a material created by this tool and bound to the slot.
    """
    return await run(call, "assign_material", names=names, material_name=material_name,
                     base_color_texture=base_color_texture, base_color=base_color,
                     roughness=roughness, metallic=metallic,
                     roughness_texture=roughness_texture,
                     metallic_texture=metallic_texture, normal_texture=normal_texture,
                     normal_strength=normal_strength, emission_texture=emission_texture,
                     emission_strength=emission_strength, alpha_texture=alpha_texture,
                     alpha_mode=alpha_mode, uv_scale=uv_scale, uv_offset=uv_offset,
                     uv_rotation_degrees=uv_rotation_degrees,
                     update_existing=False if update_existing is None else update_existing,
                     slot=slot, lease_id=lease_id)


@mcp.tool(annotations=MUTATING)
async def bake(
    map: Literal["normal", "ao"],
    name: ObjectName,
    path: Annotated[str, Field(description="New workspace .png path.")],
    high: Annotated[list[str] | None, Field(min_length=1, max_length=64)] = None,
    resolution: Annotated[StrictInt, Field(ge=64, le=4096)] = 1024,
    samples: Annotated[StrictInt, Field(ge=1, le=256)] = 16,
    margin: Annotated[StrictInt, Field(ge=0, le=64)] = 4,
    cage_extrusion: Annotated[Number, Field(ge=0, le=1)] = 0.01,
    max_ray_distance: Annotated[Number, Field(ge=0, le=10)] = 0.1,
    normal_space: Literal["tangent", "object"] | None = None,
    uv_layer: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    isolate: StrictBool = True,
    lease_id: LeaseId = None,
) -> dict[str, Any]:
    """Bake a normal or AO map into a new PNG; high-poly sources are optional.

    normal: tangent or object space; ao: ambient occlusion. high enables selected-to-active.
    The low-poly mesh is copied for baking, so the scene materials and selection are restored.
    """
    values = {"high": high, "resolution": resolution, "samples": samples, "margin": margin,
              "cage_extrusion": cage_extrusion, "max_ray_distance": max_ray_distance,
              "normal_space": normal_space, "uv_layer": uv_layer, "isolate": isolate}
    defaults = {"high": None, "resolution": 1024, "samples": 16, "margin": 4,
                "cage_extrusion": 0.01, "max_ray_distance": 0.1, "uv_layer": None,
                "isolate": True}
    if map == "normal":
        defaults["normal_space"] = "tangent"
    params = pick(map, values, (), defaults)
    return await run(call, "bake_map", lease_id=lease_id, map=map, name=name, path=path,
                     **params)


@mcp.tool(annotations=ADDITIVE)
async def asset_io(
    action: Literal["import", "export", "save", "generate"],
    path: Annotated[str, Field(description="Workspace path; new file except for import.")],
    name: Annotated[str | None, Field(min_length=1, max_length=58)] = None,
    names: Annotated[list[str] | None, Field(max_length=1000)] = None,
    preserve_instances: StrictBool | None = None,
    include_empties: StrictBool | None = None,
    image: str | None = None,
    resolution: Annotated[StrictInt | None, Field(ge=64, le=192)] = None,
    lods: StrictBool | None = None,
    collision: StrictBool | None = None,
    animations: StrictBool | None = None,
    bake_pair: BakePair | None = None,
    axis: Literal["unity", "unreal", "godot"] | None = None,
    lease_id: LeaseId = None,
) -> dict[str, Any]:
    """Move assets in or out. Params per action:
    import: GLB, FBX or OBJ path, name (new prefix); export: names, .fbx/.glb/.usd path,
    preserve_instances, include_empties, lods, collision, animations (FBX/GLB only),
    axis=unity; or bake_pair alone (writes <stem>_low.fbx, <stem>_high.fbx);
    save: .blend path; generate: image, .glb path, resolution=128 (local TripoSR, no lease).
    """
    values = {"name": name, "names": names, "preserve_instances": preserve_instances,
              "include_empties": include_empties, "image": image, "resolution": resolution,
              "lods": lods, "collision": collision, "animations": animations,
              "bake_pair": bake_pair, "axis": axis}
    if action == "generate":
        params = pick(action, values, ["image"], {"resolution": 128})
        workspace = (await run(call, "scene_info", limit=1))["workspace"]
        return await run(generate, workspace, params["image"], path, params["resolution"])
    if action == "import":
        suffix = Path(path).suffix.lower()
        operation = {".fbx": "import_fbx", ".obj": "import_obj"}.get(suffix, "import_mesh")
        return await run(call, operation, lease_id=lease_id, path=path,
                         **pick(action, values, ["name"]))
    if action == "save":
        pick(action, values)
        return await run(call, "save_project", lease_id=lease_id, path=path)
    if bake_pair is not None:
        params = pick(action, values, ["bake_pair"], {"axis": None})
        params["bake_pair"] = bake_pair.model_dump()
        return await run(call, "export_asset", lease_id=lease_id, path=path, **params)
    params = pick(action, values, ["names"], {"preserve_instances": False,
                                              "include_empties": False, "lods": False,
                                              "collision": False, "animations": False,
                                              "axis": None})
    if (params["lods"] or params["collision"] or params["animations"] or params["axis"]
            or path.lower().endswith((".usd", ".usda", ".usdc"))):
        return await run(call, "export_asset", lease_id=lease_id, path=path, **params)
    for key in ("lods", "collision", "animations", "axis"):
        params.pop(key)
    # A distinct bridge operation makes older bridges fail before writing a file.
    operation = "export_instances" if params["preserve_instances"] else "export_mesh"
    return await run(call, operation, lease_id=lease_id, path=path, **params)


@mcp.tool(annotations=ADDITIVE)
async def review_sheet(
    path: Annotated[str, Field(description="New workspace .png path.")],
    names: Annotated[list[str] | None, Field(min_length=1, max_length=1000)] = None,
    views: Annotated[list[View] | None, Field(min_length=1, max_length=6)] = None,
    mode: Literal["shaded", "wireframe", "uv_checker", "texel_heatmap", "matcap"] = "shaded",
    resolution: Annotated[StrictInt, Field(ge=256, le=2048, description="Sheet width.")] = 1024,
    target_px_per_m: Annotated[Number | None, Field(gt=0, le=100000)] = None,
    texture_resolution: Annotated[StrictInt | None, Field(ge=1, le=4096)] = None,
    uv_layer: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
) -> Image:
    """Render a multi-view PNG contact sheet; no lease. Heatmap: blue < target_px_per_m=512
    (green) < red."""
    result = await run(call, "review_sheet", path=path, names=names, views=views, mode=mode,
                       resolution=resolution, target_px_per_m=target_px_per_m,
                       texture_resolution=texture_resolution, uv_layer=uv_layer)
    return Image(path=result["path"])


@mcp.tool(annotations=MUTATING)
async def scatter(
    name: ObjectName,
    collection: Annotated[str, Field(min_length=1, max_length=63)],
    density: Annotated[Number, Field(gt=0, le=10000, description="Points per square metre.")],
    seed: Annotated[StrictInt, Field(ge=0, le=1000000)] = 0,
    min_distance: Annotated[Number, Field(ge=0, le=1000)] = 0,
    scale_range: tuple[Number, Number] = (1, 1),
    rotation_jitter_degrees: Annotated[Number, Field(ge=0, le=360)] = 360,
    realize: StrictBool = False,
    lease_id: LeaseId = None,
) -> dict[str, Any]:
    """Add a fixed Geometry Nodes modifier instancing a collection over the mesh surface."""
    return await run(call, "scatter", lease_id=lease_id, name=name, collection=collection,
                     density=density, seed=seed, min_distance=min_distance,
                     scale_range=scale_range, rotation_jitter_degrees=rotation_jitter_degrees,
                     realize=realize)


def main():
    import sys

    if len(sys.argv) > 1:
        from .cli import main as cli_main

        raise SystemExit(cli_main())
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
