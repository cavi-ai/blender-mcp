"""Typed MCP tools for the Blender bridge."""

from functools import partial
from pathlib import Path
from typing import Annotated, Literal

import anyio
from cavi_mcp_core.server import DESTRUCTIVE, READ_ONLY, WRITES
from cavi_mcp_core.server import Server as CoreServer
from mcp.server.mcpserver import Image
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictInt, WithJsonSchema

from .catalog import BlenderServer
from .client import BridgeClient
from .contracts import (
    AssetLibraryResult,
    AssetResult,
    LevelEditResult,
    MapBakeResult,
    MaterialAssignment,
    MeshEditResult,
    MeshQuality,
    ObjectEditResult,
    Ownership,
    ProceduralAssetResult,
    RigEditResult,
    RigInspection,
    RigMotionComparison,
    ScatterResult,
    SceneEditResult,
    SceneInfo,
    SkinClearance,
    UVLayout,
)
from .generation import generate
from .operations import SERVER_LEASE_FREE
from .rig_models import (
    ClipTiming,
    Constraint,
    ContactReference,
    ContactWindow,
    FootLockWindow,
    MotionSkinPair,
    NlaStripSettings,
    RetargetCalibration,
    VertexWeights,
)
from .rig_models import Name as RigName
from .scene_models import CameraSpec, LightSpec, PreviewSettings, RenderSpec, WorldSpec

Server = CoreServer

mcp = BlenderServer(
    "cavi-blender-mcp",
    package="cavi-blender-mcp",
    instructions=(
        "Inspect the scene before editing. Saves and exports refuse existing paths. "
        "Paths are relative to the Blender session workspace. Claim session_control ownership "
        "before edits and pass lease_id. Never retry an uncertain mutation."
    ),
)
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]


def _vector_schema(size):
    return WithJsonSchema({'type': 'array', 'items': {'type': 'number'},
                           'minItems': size, 'maxItems': size})


Vector2 = Annotated[tuple[Number, Number], _vector_schema(2)]
Vector3 = Annotated[tuple[Number, Number, Number], _vector_schema(3)]
RGBA = Annotated[tuple[Number, Number, Number, Number], _vector_schema(4)]
ObjectName = Annotated[str, Field(description="scene_info name.")]
LeaseId = str | None
MUTATING = DESTRUCTIVE
ADDITIVE = WRITES
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


class ShaderImage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    color_space: str
    alpha_mode: Literal['STRAIGHT', 'PREMUL', 'CHANNEL_PACKED', 'NONE'] = 'STRAIGHT'
    tiles: Annotated[list[Annotated[StrictInt, Field(ge=1001)]] | None, Field(min_length=1)] = None


class BakePair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    high: Names
    low: Names


class UVTransform(BaseModel):
    model_config = ConfigDict(extra='forbid')
    faces: Annotated[list[Annotated[StrictInt, Field(ge=0)]], Field(min_length=1, max_length=20000)]
    offset: Vector2 = (0, 0)
    scale: Vector2 = (1, 1)
    rotation_degrees: Number = 0
    pivot: Vector2 = (0, 0)


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


class ShapeKeyframe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frame: Annotated[StrictInt, Field(ge=1, le=1_000_000)]
    value: Annotated[Number, Field(ge=0, le=1)]


class Placement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: ObjectName
    name: Annotated[str, Field(min_length=1, max_length=63)]
    location: Vector3 = (0, 0, 0)
    rotation_degrees: Vector3 = (0, 0, 0)
    scale: Vector3 = (1, 1, 1)
    linked: StrictBool = False


def call(operation_name, **params):
    client = BridgeClient()
    if operation_name not in SERVER_LEASE_FREE:
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
    definition: StrictBool | None = None,
    faces: StrictBool | None = None,
) -> SceneInfo:
    """Inspect the scene or one object. With name and definition=true, page through a
    collection instance's nested source objects and report its shared scene placements.
    faces=true pages source mesh polygons with local centers/normals and a geometry fingerprint.
    """
    if faces:
        if name is None or definition:
            raise ValueError('faces requires a mesh name and cannot be combined with definition')
        return await run(call, 'inspect_mesh_faces', name=name, limit=limit, offset=offset)
    if definition:
        if name is None:
            raise ValueError('definition requires a scene-instance name')
        return await run(call, 'inspect_collection_instance', name=name, limit=limit, offset=offset)
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
) -> MeshQuality:
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
async def inspect_uv_layout(
    names: Annotated[list[ObjectName], Field(min_length=1, max_length=32)],
    texture_resolution: tuple[Annotated[StrictInt, Field(ge=1, le=16384)],
                              Annotated[StrictInt, Field(ge=1, le=16384)]] | None = None,
    padding_pixels: Annotated[Number | None, Field(ge=0, le=256)] = None,
    uv_layer: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    comparison_budget: Annotated[StrictInt | None, Field(ge=1, le=1000000)] = None,
    material: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    udim_image: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
) -> UVLayout:
    """Source UVs, max 20,000 triangles; layer index 0 unless named. material filters faces.
    texture_resolution + padding_pixels: unique 0..1 overlaps and gutters.
    udim_image: coverage of native tiles by source UVs; excludes shader vector transforms.
    comparison_budget bounds candidates, 50 per inspected triangle unless given.
    Incomplete work cannot pass. No geometry,
    selection or image edits; modifiers are not evaluated.
    """
    if udim_image is not None:
        if texture_resolution is not None or padding_pixels is not None:
            raise ValueError('UDIM coverage does not take texture_resolution or padding_pixels')
        return await run(call, 'inspect_udim_coverage', names=names, uv_layer=uv_layer,
                         comparison_budget=comparison_budget, material=material, udim_image=udim_image)
    if texture_resolution is None or padding_pixels is None:
        raise ValueError('Unique-tile analysis requires texture_resolution and padding_pixels')
    return await run(call, "inspect_uv_layout", names=names,
                     texture_resolution=texture_resolution, padding_pixels=padding_pixels,
                     uv_layer=uv_layer, comparison_budget=comparison_budget, material=material)


@mcp.tool(annotations=READ_ONLY)
async def inspect_rig(
    armature: ObjectName,
    meshes: Annotated[list[ObjectName], Field(min_length=1, max_length=8)],
    max_influences: Annotated[StrictInt, Field(ge=1, le=32)] = 4,
    action: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    checks: Annotated[list[Literal["root_motion", "loop", "deformation"]] | None,
                      Field(max_length=3)] = None,
    samples: Annotated[StrictInt, Field(ge=2, le=32)] = 8,
    contacts: Annotated[list[ContactWindow] | None, Field(min_length=1, max_length=16)] = None,
    contact_reference: ContactReference | None = None,
    contact_frame_offset: Number = 0,
    contact_frame_scale: Annotated[Number, Field(gt=0)] = 1,
) -> RigInspection:
    """Inspect skin weights, rest bones and linked clips without changing action or pose.

    Exact meshes must each have one vertex-group armature modifier bound to the rig.
    Influence limit is a caller-selected target, not a universal engine requirement.
    checks: root_motion, loop and deformation sample the named or active action.
    contacts: declared bone-local markers and frame windows measure horizontal drift
    and absolute height error against a world-Z ground plane in metres.
    contact_reference: source rig/action maps marker offsets across fixed rest-axis
    changes. Candidate time = source time * contact_frame_scale + contact_frame_offset.
    """
    arguments = {'armature': armature, 'meshes': meshes, 'max_influences': max_influences,
                 'action': action, 'checks': checks or [], 'samples': samples}
    if contacts is not None:
        arguments['contacts'] = [item.model_dump() for item in contacts]
    if contact_reference is not None:
        arguments['contact_reference'] = contact_reference.model_dump()
    if contact_frame_offset != 0:
        arguments['contact_frame_offset'] = contact_frame_offset
    if contact_frame_scale != 1:
        arguments['contact_frame_scale'] = contact_frame_scale
    return await run(call, "inspect_rig", **arguments)


@mcp.tool(annotations=READ_ONLY)
async def inspect_skin_clearance(
    body: ObjectName,
    garments: Annotated[list[ObjectName], Field(min_length=1, max_length=8)],
    start_frame: Annotated[StrictInt, Field(ge=1, le=1000000)],
    end_frame: Annotated[StrictInt, Field(ge=1, le=1000000)],
    min_clearance_m: Annotated[Number, Field(ge=0)],
    samples: Annotated[StrictInt, Field(ge=2, le=32)] = 9,
    surface_samples: Literal["vertices", "vertices_and_centres"] = "vertices_and_centres",
    max_queries: Annotated[StrictInt, Field(ge=1, le=1000000)] = 1000000,
) -> SkinClearance:
    """Sample signed garment gaps against closed evaluated body components, restoring the frame.

    Probes vertices and optionally triangle centres in metres. Ambiguous classification,
    open bodies and exhausted query budgets cannot pass. Does not certify continuous collision.
    """
    return await run(call, "inspect_skin_clearance", body=body, garments=garments,
        start_frame=start_frame, end_frame=end_frame, min_clearance_m=min_clearance_m,
        samples=samples, surface_samples=surface_samples, max_queries=max_queries)


@mcp.tool(annotations=READ_ONLY)
async def compare_rig_motion(
    source: ObjectName,
    candidate: ObjectName,
    meshes: Annotated[list[MotionSkinPair], Field(min_length=1, max_length=8)],
    start_frame: Annotated[StrictInt, Field(ge=1, le=1000000)],
    end_frame: Annotated[StrictInt, Field(ge=1, le=1000000)],
    max_error_m: Annotated[Number, Field(ge=0)],
    samples: Annotated[StrictInt, Field(ge=2, le=32)] = 9,
    space: Literal["world", "start_root"] = "world",
    vertex_match: Literal["index", "point_set"] = "index",
    candidate_frame_offset: Annotated[Number, Field(ge=-1000000, le=1000000)] = 0,
    candidate_frame_scale: Annotated[Number, Field(gt=0)] = 1,
) -> RigMotionComparison:
    """Compare evaluated skin positions and matching bone heads on the current timeline.

    Index matching is for unchanged vertex order. Bidirectional point sets allow export seam
    splits; they do not establish vertex correspondence. start_root removes only initial rig
    placement. Candidate time = source time * candidate_frame_scale + candidate_frame_offset.
    Restores frame and subframe; no edits.
    """
    options = {'candidate_frame_scale': candidate_frame_scale} if candidate_frame_scale != 1 else {}
    return await run(call, "compare_rig_motion", source=source, candidate=candidate,
        meshes=[pair.model_dump() for pair in meshes], start_frame=start_frame, end_frame=end_frame,
        max_error_m=max_error_m, samples=samples, space=space, vertex_match=vertex_match,
        candidate_frame_offset=candidate_frame_offset, **options)


@mcp.tool(annotations=MUTATING)
async def rig_edit(
    action: Literal["create", "bind", "weights", "pose", "keyframe", "clear_pose",
                    "retarget", "set_action", "rename_action", "delete_action",
                    "nla_push", "nla_edit", "nla_remove", "constraint", "remove_constraint",
                    "assign_weights", "transfer_weights", "bake", "contact_lock"],
    name: str,
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
    source: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    source_action: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    mapping: Annotated[dict[str, str] | None, Field(max_length=128)] = None,
    samples: Annotated[StrictInt | None, Field(ge=2, le=256)] = None,
    new_name: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    track_name: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    strip_name: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    start_frame: Annotated[StrictInt | None, Field(ge=1, le=1_000_000)] = None,
    end_frame: Annotated[StrictInt | None, Field(ge=1, le=1_000_000)] = None,
    frame_step: Annotated[Number | None, Field(gt=0, le=10000)] = None,
    constraint: Constraint | None = None,
    bone: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    constraint_name: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    vertex_weights: Annotated[list[VertexWeights] | None,
                              Field(min_length=1, max_length=100000)] = None,
    replace: StrictBool | None = None,
    max_distance_m: Annotated[Number | None, Field(gt=0)] = None,
    max_discarded_weight: Annotated[Number | None, Field(ge=0, le=1)] = None,
    shape_names: Annotated[list[RigName] | None, Field(max_length=64)] = None,
    calibration: RetargetCalibration | None = None,
    skinning_mode: Literal['preserve', 'linear'] | None = None,
    foot_locks: Annotated[list[FootLockWindow] | None, Field(min_length=1, max_length=16)] = None,
    timing: ClipTiming | None = None,
    strip_settings: NlaStripSettings | None = None,
    animation_target: Literal['OBJECT', 'SHAPE_KEYS'] | None = None,
    lease_id: LeaseId = None,
) -> RigEditResult:
    """Edit rigs."""
    values = {"location": location, "bones": bones, "names": names,
              "max_influences": max_influences, "clean_threshold": clean_threshold,
              "normalize": normalize, "poses": poses, "keyframes": keyframes,
              "action_name": action_name, "frame": frame, "reset": reset,
              "source": source, "source_action": source_action, "mapping": mapping,
              "samples": samples, "new_name": new_name, "track_name": track_name,
              "strip_name": strip_name, "start_frame": start_frame,
              "end_frame": end_frame, "frame_step": frame_step, 'constraint': constraint,
              'bone': bone, 'constraint_name': constraint_name, 'vertex_weights': vertex_weights,
              'replace': replace, 'max_distance_m': max_distance_m,
              'max_discarded_weight': max_discarded_weight, 'shape_names': shape_names,
              'calibration': calibration, 'skinning_mode': skinning_mode, 'foot_locks': foot_locks,
              'timing': timing, 'strip_settings': strip_settings,
              'animation_target': animation_target}
    clip_action = action in {'set_action', 'nla_push', 'nla_edit', 'nla_remove'}
    if clip_action:
        values.pop('animation_target')
    if action == 'contact_lock':
        operation = 'lock_rig_contacts'
        params = pick(action, values, ['source_action', 'action_name', 'new_name', 'foot_locks'],
                      {'names': [], 'frame_step': 1})
        params['foot_locks'] = [item.model_dump() for item in params['foot_locks']]
    elif action == 'transfer_weights':
        operation = 'transfer_skin_weights'
        params = pick(action, values, ['source', 'new_name', 'max_distance_m', 'max_discarded_weight'],
                      {'max_influences': 4, 'shape_names': []})
    elif action == 'constraint':
        operation = 'add_constraint'
        params = pick(action, values, ['constraint'])
        params['constraint'] = params['constraint'].model_dump()
    elif action == 'remove_constraint':
        operation = 'remove_constraint'
        params = pick(action, values, ['bone', 'constraint_name'])
    elif action == 'assign_weights':
        operation = 'assign_weights'
        params = pick(action, values, ['vertex_weights'], {'replace': True, 'normalize': False})
        params['vertex_weights'] = [item.model_dump() for item in params['vertex_weights']]
    elif action == 'bake':
        operation = 'bake_rig'
        params = pick(action, values, ['new_name', 'action_name', 'start_frame', 'end_frame'],
                      {'frame_step': 1, 'names': [], 'skinning_mode': 'preserve', 'timing': None})
        if params['timing'] is None:
            del params['timing']
        else:
            params['timing'] = params['timing'].model_dump()
    elif action == "create":
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
    elif action == "retarget":
        operation = "retarget_rig"
        params = pick(action, values, ["source", "source_action", "action_name"], {
            "mapping": None, "samples": None, "calibration": None})
        if params['calibration'] is not None:
            params['calibration'] = params['calibration'].model_dump()
        else:
            del params['calibration']
    elif action == "set_action":
        operation = "set_action"
        params = pick(action, values, (), {"action_name": None})
    elif action == "rename_action":
        operation = "rename_action"
        params = pick(action, values, ["action_name", "new_name"])
    elif action == "delete_action":
        operation = "delete_action"
        params = pick(action, values, ["action_name"])
    elif action == "nla_push":
        operation = "nla_push"
        params = pick(action, values, (), {
            "action_name": None, "track_name": None, "strip_name": None,
            "start_frame": 1, "strip_settings": None})
        if params.get('strip_settings') is not None:
            params['strip_settings'] = params['strip_settings'].model_dump(exclude_none=True)
        else:
            params.pop('strip_settings')
    elif action == 'nla_edit':
        operation = 'nla_edit'
        params = pick(action, values, ['track_name', 'strip_name', 'strip_settings'])
        params['strip_settings'] = params['strip_settings'].model_dump(exclude_none=True)
    elif action == "nla_remove":
        operation = "nla_remove"
        params = pick(action, values, (), {"track_name": None, "strip_name": None})
    else:
        operation = "clear_pose"
        params = pick(action, values, (), {"frame": None})
    if clip_action and animation_target is not None:
        params['animation_target'] = animation_target
    return await run(call, operation, lease_id=lease_id, name=name, **params)


@mcp.tool(annotations=MUTATING)
async def scene_edit(
    action: Literal['camera', 'light', 'world', 'render'],
    camera: CameraSpec | None = None,
    light: LightSpec | None = None,
    world: WorldSpec | None = None,
    render: RenderSpec | None = None,
    lease_id: LeaseId = None,
) -> SceneEditResult:
    """Author persistent camera/light definitions, a managed color/HDRI world, or
    render the actual scene through its named camera. Existing camera/light names
    update in place; worlds update only graphs this tool authored. Render settings
    persist for saved-project reproducibility. PNG/TIFF default to 16-bit, EXR
    supports 16/32-bit. max_pixels is caller-configurable; samples bound work and
    cycles_time_limit caps Cycles sampling. GPU uses configured enabled Cycles devices.
    Existing render_preview remains a separate quick-preview path."""
    definitions = {'camera': camera, 'light': light, 'world': world, 'render': render}
    params = pick(action, definitions, [action])
    return await run(call, 'scene_authoring', lease_id=lease_id, action=action,
                     definition=params[action].model_dump())


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
    settings: PreviewSettings | None = None,
) -> Image:
    """Render a PNG preview; restores scene state. No lease needed. Eevee max 1024 px.

    settings selects temporary display controls, compositing and PNG depth; omission
    preserves scene settings. Enabled curves/white balance reuse the scene's controls.
    """
    options = {} if settings is None else {'settings': settings.model_dump()}
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
        **options,
    )
    return Image(path=result["path"])


@mcp.tool(annotations=ADDITIVE)
async def session_control(
    action: Literal["inspect", "claim", "renew", "release", "break"],
    owner: Annotated[str | None, Field(max_length=128)] = None,
    expected_project: Annotated[
        str | None, Field(description="Exact project_id from inspect.")
    ] = None,
    lease_id: Annotated[str | None, Field(max_length=128)] = None,
    ttl_seconds: Annotated[StrictInt, Field(ge=30, le=3600)] = 600,
) -> Ownership:
    """Inspect ownership or claim, renew, release or break an edit lease.

    Claim returns a private lease_id; pass it on every edit. Break needs expected_project
    and a lease unused for 300 s. Expiry, release and break never save, close or discard
    a project.
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
                    "duplicate", "make_unique", "make_single_user", "parent", "unparent", "move_to_collection", "shape_key_add",
                    "shape_key_value", "shape_key_keyframe", "shape_key_remove"],
    name: Annotated[str, Field(description="Object name; new and unique for create_*.")],
    kind: Literal["cube", "sphere", "cylinder", "cone", "plane"] | None = None,
    location: Vector3 | None = None,
    rotation_degrees: Annotated[Vector3 | None, Field(description="XYZ Euler.")] = None,
    scale: Annotated[Vector3 | None, Field(description="Nonzero; negative mirrors.")] = None,
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
    value: Annotated[Number | None, Field(ge=0, le=1)] = None,
    keyframes: Annotated[list[ShapeKeyframe] | None, Field(min_length=1, max_length=32)] = None,
    action_name: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    source: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    offsets: Annotated[list[Annotated[list[Number], Field(min_length=4, max_length=4)]] | None,
                       Field(max_length=10000)] = None,
    lease_id: LeaseId = None,
) -> ObjectEditResult:
    """Create or edit one object. Params per action:
    create_primitive: kind, location; create_mesh: vertices, faces;
    transform: location, rotation_degrees, scale; set_color: rgba, slot=0; shade: smooth=false;
    apply_transforms: components=[rotation,scale], make_single_user=false;
    set_origin: origin=bounds_bottom_center (point: world location); snap_to_grid: grid;
    rename: new_name; add_socket: new_name, local location, rotation_degrees;
    duplicate: new_name, count=1, offset=(0,0,0), linked=false;
    make_unique: new_name (independent collection definition for this instance);
    make_single_user: no extra params; copy shared mesh data, keep the object;
    parent: new_name (parent); unparent: no extra params;
    move_to_collection: new_name (collection), create=true;
    shape_key_add: new_name, value=0, offsets, source; shape_key_value: new_name, value;
    shape_key_keyframe: new_name, action_name, keyframes=[{frame, value}];
    shape_key_remove: new_name.
    """
    values = {"kind": kind, "location": location, "rotation_degrees": rotation_degrees,
              "scale": scale, "vertices": vertices, "faces": faces, "rgba": rgba, "slot": slot,
              "smooth": smooth, "components": components, "make_single_user": make_single_user,
              "origin": origin, "grid": grid, "new_name": new_name, "count": count,
              "offset": offset, "linked": linked, "create": create, "value": value,
              "keyframes": keyframes, "action_name": action_name, "source": source,
              "offsets": offsets}
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
        "make_unique": ("make_instance_unique", lambda: pick(action, values, ["new_name"])),
        "make_single_user": ("make_mesh_single_user", lambda: pick(action, values)),
        "parent": ("parent_object", lambda: pick(action, values, ["new_name"])),
        "unparent": ("unparent_object", lambda: pick(action, values)),
        "move_to_collection": ("move_to_collection", lambda: pick(action, values, ["new_name"], {
            "create": True})),
        "shape_key_add": ("shape_key_add", lambda: pick(action, values, ["new_name"], {
            "value": 0, "offsets": None, "source": None})),
        "shape_key_value": ("shape_key_value", lambda: pick(action, values, ["new_name", "value"])),
        "shape_key_keyframe": ("shape_key_keyframe", lambda: {
            **pick(action, values, ["new_name", "action_name", "keyframes"]),
            "keyframes": [item.model_dump() for item in keyframes],
        }),
        "shape_key_remove": ("shape_key_remove", lambda: pick(action, values, ["new_name"])),
    }[action]
    return await run(call, operation, lease_id=lease_id, name=name, **params())


@mcp.tool(annotations=MUTATING)
async def mesh_edit(
    action: Literal["modifier", "unwrap", "decimate_to", "remesh_quad", "lod_chain",
                    "lightmap_uv", "texel_density", "collision", "cleanup", "boolean",
                    "join", "separate", "extract_faces", "extrude_faces", "mirror", "array", "solidify", "uv_transform"],
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
    new_name: ObjectName | None = None,
    face_indices: Annotated[list[Annotated[StrictInt, Field(ge=0)]] | None,
                            Field(min_length=1, max_length=20000)] = None,
    count: Annotated[StrictInt | None, Field(ge=2, le=1000)] = None,
    offset: Vector3 | None = None,
    thickness: Annotated[Number | None, Field(gt=0, le=100)] = None,
    clipping: StrictBool | None = None,
    uv_transform: UVTransform | None = None,
    lease_id: LeaseId = None,
    expected_mesh_sha256: Annotated[str | None, Field(pattern='^[0-9a-f]{64}$')] = None,
) -> MeshEditResult:
    """Edit a leased mesh."""
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
              "names": names, "by": by, "new_name": new_name, "face_indices": face_indices,
              "count": count, "offset": offset,
              "thickness": thickness, "clipping": clipping, "uv_transform": uv_transform,
              'expected_mesh_sha256': expected_mesh_sha256}
    if action == 'extrude_faces':
        from .mesh_regions import selection

        params = pick(action, values, ['face_indices', 'offset'], {'expected_mesh_sha256': None})
        selection(params['face_indices'], params['offset'], expected=params['expected_mesh_sha256'])
        return await run(call, 'extrude_faces', lease_id=lease_id, name=name, **params)
    if action == "modifier":
        operation = "add_modifier"
        params = pick(action, values, ["kind", "amount"], {"apply": False})
    elif action == "unwrap":
        operation = "unwrap_mesh"
        params = pick(action, values, (), {"angle_limit_degrees": 66, "island_margin": None,
                                           "margin_px": 4, "texture_resolution": 1024,
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
    elif action == 'uv_transform':
        operation = 'transform_uv'
        params = pick(action, values, ['uv_transform'], {'uv_layer':None})
        params['transform'] = params.pop('uv_transform').model_dump()
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
    elif action == "extract_faces":
        operation = action
        params = pick(action, values, ["new_name", "face_indices"])
        if len(set(params["face_indices"])) != len(params["face_indices"]):
            raise ValueError("face_indices must be unique")
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
    names: Annotated[list[str] | None, Field(min_length=1, max_length=32)] = None,
    material_name: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
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
    uv_layer: Annotated[str | None, Field(max_length=63,
        description="Named mesh UV for textures and normal tangents; empty selects render-active UVs.")] = None,
    update_existing: StrictBool | None = None,
    slot: Annotated[StrictInt, Field(ge=0, le=31)] = 0,
    lease_id: LeaseId = None,
    instance: str | None = None,
    link_mode: Literal['DATA', 'OBJECT'] | None = None,
    action: Literal['assign', 'inspect', 'set_inputs', 'set_image', 'make_unique'] = 'assign',
    group_path: list[str] | None = None,
    node: str | None = None,
    inputs: dict[str, JsonValue] | None = None,
    outputs: dict[str, JsonValue] | None = None,
    image: ShaderImage | None = None,
    offset: Annotated[StrictInt | None, Field(ge=0)] = None,
    limit: Annotated[StrictInt | None, Field(ge=1, le=1000)] = None,
) -> MaterialAssignment:
    """assign: names, material_name; color/emission sRGB, data Non-Color.
    instance scopes kit meshes; OBJECT shares geometry.
    uv_layer selects named sampling and normal tangents without changing mesh UV flags.
    inspect: group_path, node, offset/limit; read-only.
    set_inputs: node, inputs/outputs socket IDs; linear, links kept, shared users
    affected, config detached. set_image: node, image(path,color_space,alpha_mode,tiles); packed.
    make_unique: names, new material_name; copy groups, share images/actions.
    """
    if material_name is None:
        raise ValueError('material_name is required')
    shader = {'group_path': group_path, 'node': node, 'inputs': inputs, 'outputs': outputs, 'image': image, 'offset': offset, 'limit': limit}
    values = {'names': names, 'base_color_texture': base_color_texture, 'base_color': base_color,
            'roughness': roughness, 'metallic': metallic, 'roughness_texture': roughness_texture,
            'metallic_texture': metallic_texture, 'normal_texture': normal_texture, 'normal_strength': normal_strength,
            'emission_texture': emission_texture, 'emission_strength': emission_strength,
            'alpha_texture': alpha_texture, 'alpha_mode': alpha_mode, 'uv_scale': uv_scale,
            'uv_offset': uv_offset, 'uv_rotation_degrees': uv_rotation_degrees,
            'update_existing': update_existing, 'instance': instance, 'link_mode': link_mode,
            'uv_layer': uv_layer,
            'slot': slot if slot != 0 else None}
    if action == 'make_unique':
        pick(action, shader)
        params = pick(action, values, ['names'], {'slot': 0, 'link_mode': 'OBJECT'})
        return await run(call, 'make_material_unique', material_name=material_name, lease_id=lease_id, **params)
    if action != 'assign':
        pick(action, values)
        if action == 'inspect':
            params = pick(action, shader, (), {'group_path': [], 'node': None, 'offset': 0, 'limit': 100})
            return await run(call, 'inspect_material_nodes', material_name=material_name, **params)
        if action == 'set_image':
            params = pick(action, shader, ['node', 'image'], {'group_path': []})
            params['image'] = image.model_dump(exclude_none=True)
            return await run(call, 'set_material_image', material_name=material_name, lease_id=lease_id, **params)
        params = pick(action, shader, ['node'], {'group_path': [], 'inputs': {}, 'outputs': {}})
        if not (params['inputs'] or params['outputs']):
            raise ValueError('Provide nonempty inputs or outputs')
        if not params['outputs']:
            params.pop('outputs')
        return await run(call, 'set_material_inputs', material_name=material_name, lease_id=lease_id, **params)
    pick(action, shader)
    if names is None:
        raise ValueError('assign requires names')
    operation = 'assign_instance_material' if instance is not None else (
        'assign_object_material' if link_mode is not None else 'assign_material')
    options = {}
    if uv_layer is not None:
        options['uv_layer'] = uv_layer
    if instance is not None:
        options['instance'] = instance
    if link_mode is not None:
        options['link_mode'] = link_mode
    return await run(call, operation, names=names, material_name=material_name,
                     base_color_texture=base_color_texture, base_color=base_color,
                     roughness=roughness, metallic=metallic,
                     roughness_texture=roughness_texture,
                     metallic_texture=metallic_texture, normal_texture=normal_texture,
                     normal_strength=normal_strength, emission_texture=emission_texture,
                     emission_strength=emission_strength, alpha_texture=alpha_texture,
                     alpha_mode=alpha_mode, uv_scale=uv_scale, uv_offset=uv_offset,
                     uv_rotation_degrees=uv_rotation_degrees,
                     update_existing=False if update_existing is None else update_existing,
                     slot=slot, lease_id=lease_id, **options)


class ShaderBakeSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    material: Annotated[str, Field(min_length=1, max_length=63)]
    node: Annotated[str, Field(min_length=1, max_length=63)]
    socket: Annotated[str, Field(min_length=1, max_length=255)]
    group_path: Annotated[list[str], Field(max_length=16)] = []
    direction: Literal['INPUT', 'OUTPUT'] = 'OUTPUT'
    role: Literal['data', 'color'] = 'data'


@mcp.tool(annotations=MUTATING)
async def bake(
    map: Literal["normal", "ao", "curvature", "lightmap", "shader"],
    name: ObjectName,
    path: Annotated[str, Field(description="New workspace PNG; shader also accepts EXR.")],
    high: Annotated[list[str] | None, Field(min_length=1, max_length=64)] = None,
    resolution: Annotated[StrictInt, Field(ge=64, le=4096)] = 1024,
    samples: Annotated[StrictInt, Field(ge=1, le=256)] = 16,
    margin: Annotated[StrictInt, Field(ge=0, le=64)] = 4,
    bit_depth: Literal[8, 16, 32] | None = None,
    cage_extrusion: Annotated[Number | None, Field(ge=0, le=1)] = None,
    max_ray_distance: Annotated[Number | None, Field(ge=0, le=10)] = None,
    normal_space: Literal["tangent", "object"] | None = None,
    uv_layer: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    isolate: StrictBool = True,
    source: ShaderBakeSource | None = None,
    lease_id: LeaseId = None,
) -> MapBakeResult:
    """Bake geometry or an explicit shader socket. PNG defaults to 16-bit; shader EXR to 32-bit.

    high: normal/AO projection. Shader uses source socket identifiers and a target UV atlas;
    data is raw, color PNG is sRGB. Signed/HDR samples require EXR. Alpha needs a separate socket.
    """
    if map == 'shader':
        if source is None:
            raise ValueError('shader requires source')
        pick(map, {'high':high, 'cage_extrusion':cage_extrusion,
                   'max_ray_distance':max_ray_distance, 'normal_space':normal_space})
        depth = bit_depth if bit_depth is not None else (32 if Path(path).suffix.lower()=='.exr' else 16)
        if depth not in ({16,32} if Path(path).suffix.lower()=='.exr' else {8,16}):
            raise ValueError('bit_depth validation: PNG accepts 8/16; EXR accepts 16/32')
        return await run(call, 'bake_shader', name=name, path=path,
            source=source.model_dump(), resolution=resolution, samples=samples, margin=margin,
            bit_depth=depth, uv_layer=uv_layer, isolate=isolate, lease_id=lease_id)
    if source is not None:
        raise ValueError('source applies only to shader bakes')
    if bit_depth is not None and bit_depth not in {8,16}:
        raise ValueError('bit_depth validation: geometry bakes accept 8/16')
    values = {"high": high, "resolution": resolution, "samples": samples, "margin": margin,
              "bit_depth": 16 if bit_depth is None else bit_depth,
              "cage_extrusion": cage_extrusion, "max_ray_distance": max_ray_distance,
              "normal_space": normal_space, "uv_layer": uv_layer, "isolate": isolate}
    defaults = {"resolution": 1024, "samples": 16, "margin": 4, "bit_depth": 16,
                "uv_layer": None, "isolate": True}
    if map in {"normal", "ao"}:
        defaults.update({"high": None, "cage_extrusion": 0.01, "max_ray_distance": 0.1})
    if map == "normal":
        defaults["normal_space"] = "tangent"
    params = pick(map, values, (), defaults)
    return await run(call, "bake_png", lease_id=lease_id, map=map, name=name, path=path,
                     **params)


@mcp.tool(annotations=MUTATING)
async def asset_io(
    action: Literal["import", "export", "save", "generate", "open"],
    path: Annotated[str, Field(description="Workspace path; existing file for import/open, new otherwise.")],
    name: Annotated[str | None, Field(min_length=1, max_length=58)] = None,
    names: Annotated[list[str] | None, Field(max_length=1000)] = None,
    preserve_instances: StrictBool | None = None,
    include_empties: StrictBool | None = None,
    image: str | None = None,
    resolution: Annotated[StrictInt | None, Field(ge=64, le=192)] = None,
    lods: StrictBool | None = None,
    collision: StrictBool | None = None,
    animations: StrictBool | None = None,
    baked_animation: StrictBool | None = None,
    assembly: StrictBool | None = None,
    animation_sample_step: Annotated[Number | None, Field(gt=0)] = None,
    textures: StrictBool | None = None,
    bake_pair: BakePair | None = None,
    axis: Literal["unity", "unreal", "godot"] | None = None,
    uv_layer: Annotated[str | None, Field(min_length=1,max_length=63)] = None,
    lease_id: LeaseId = None,
    expected_sha256: Annotated[str | None, Field(pattern='^[0-9a-f]{64}$')] = None,
) -> AssetResult:
    """Import/export meshes or save/open .blend. Open requires clean source;
    expected_sha256 pins its bytes. File UI/scripts are disabled.
    uv_layer selects UV0 (USD st); bake_pair exports low/high FBX.
    generate creates a GLB from image without a lease; resolution applies to TripoSR.
    """
    values = {"name": name, "names": names, "preserve_instances": preserve_instances,
              "include_empties": include_empties, "image": image, "resolution": resolution,
              "lods": lods, "collision": collision, "animations": animations,
              "textures": textures, "bake_pair": bake_pair, "axis": axis,
              "baked_animation": baked_animation, "animation_sample_step": animation_sample_step,
              'assembly': assembly,'uv_layer':uv_layer,'expected_sha256':expected_sha256}
    if action == 'open':
        params = pick(action, values, (), {'expected_sha256': None})
        return await run(call, 'open_project', lease_id=lease_id, path=path, **params)
    if action == 'export' and assembly is True:
        values.pop('assembly')
        params = pick(action, values, ['names'], {'axis': None, 'textures': False,'uv_layer':None})
        if params['uv_layer'] is None:params.pop('uv_layer')
        return await run(call, 'export_uv_assembly' if uv_layer is not None else 'export_assembly', path=path, lease_id=lease_id, **params)
    if action == 'export' and assembly is False:
        values.pop('assembly')
    if action == "generate":
        params = pick(action, values, ["image"], {"resolution": None})
        workspace = (await run(call, "scene_info", limit=1))["workspace"]
        return await run(generate, workspace, params["image"], path, params["resolution"])
    if action == "import":
        suffix = Path(path).suffix.lower()
        operation = {".fbx": "import_fbx", ".obj": "import_obj",
                     ".usd": "import_usd", ".usda": "import_usd",
                     ".usdc": "import_usd"}.get(suffix, "import_mesh")
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
                                              "textures": False, "axis": None, "baked_animation": False, "animation_sample_step": None,'uv_layer':None})
    if params['uv_layer'] is None:params.pop('uv_layer')
    else:
        return await run(call,'export_uv_asset',lease_id=lease_id,path=path,**params)
    if (params["lods"] or params["collision"] or params["animations"]
            or params["textures"] or params["axis"] or params["baked_animation"] or params["animation_sample_step"] is not None
            or path.lower().endswith((".usd", ".usda", ".usdc"))):
        return await run(call, "export_asset", lease_id=lease_id, path=path, **params)
    for key in ("lods", "collision", "animations", "textures", "axis", "baked_animation", "animation_sample_step"):
        params.pop(key)
    # A distinct bridge operation makes older bridges fail before writing a file.
    operation = "export_instances" if params["preserve_instances"] else "export_mesh"
    return await run(call, operation, lease_id=lease_id, path=path, **params)


@mcp.tool(annotations=ADDITIVE)
async def asset_library(
    action: Literal['inspect', 'append'],
    path: str,
    kind: Literal['objects', 'collections', 'materials', 'node_groups'] = 'collections',
    names: Annotated[list[str] | None, Field(min_length=1, max_length=256)] = None,
    expected_sha256: Annotated[str | None, Field(pattern='^[0-9a-f]{64}$')] = None,
    offset: Annotated[StrictInt | None, Field(ge=0)] = None,
    limit: Annotated[StrictInt | None, Field(ge=1, le=1000)] = None,
    instance_collections: StrictBool | None = None,
    lease_id: LeaseId = None,
) -> AssetLibraryResult:
    """Inspect .blend names or append editable native assets. Append instance_collections=true
    creates placement empties sharing imported collection definitions (kind=collections only).
    """
    values = {'names': names, 'expected_sha256': expected_sha256, 'offset': offset, 'limit': limit,
              'instance_collections': instance_collections}
    if action == 'inspect':
        params = pick(action, values, (), {'offset': 0, 'limit': 100})
        return await run(call, 'inspect_asset_library', path=path, kind=kind, **params)
    params = pick(action, values, ['names', 'expected_sha256'], {'instance_collections': None})
    if params.pop('instance_collections'):
        if kind != 'collections':
            raise ValueError('instance_collections requires kind=collections')
        operation = 'append_asset_library_instances'
    else:
        operation = 'append_asset_library'
    return await run(call, operation, path=path, kind=kind, lease_id=lease_id, **params)


@mcp.tool(annotations=MUTATING)
async def geometry_nodes(
    action: Literal['inspect', 'set_inputs', 'bake_copy'],
    name: str,
    modifier: str | None = None,
    inputs: dict[str, JsonValue] | None = None,
    attributes: dict[str, str | None] | None = None,
    new_name: str | None = None,
    instance: str | None = None,
    lease_id: LeaseId = None,
) -> ProceduralAssetResult:
    """Inspect/edit exposed inputs or snapshot an evaluated mesh. For inspect/set_inputs,
    instance names a scene collection instance containing the source object; edits affect
    its shared definition. Use scene_info definition=true to find exact member names.
    """
    values = {'modifier': modifier, 'inputs': inputs, 'attributes': attributes, 'new_name': new_name,
              'instance': instance}
    if action == 'inspect':
        params = pick(action, values, (), {'modifier': None, 'instance': None})
        scoped = params.pop('instance')
        if scoped is not None:
            return await run(call, 'inspect_instance_geometry_nodes', name=name, instance=scoped, **params)
        return await run(call, 'inspect_geometry_nodes', name=name, **params)
    if action == 'set_inputs':
        params = pick(action, values, ['modifier'], {'inputs': {}, 'attributes': {}, 'instance': None})
        scoped = params.pop('instance')
        if not (params['inputs'] or params['attributes']):
            raise ValueError('Provide inputs or attributes')
        if scoped is not None:
            return await run(call, 'set_instance_geometry_inputs', name=name, instance=scoped, lease_id=lease_id, **params)
        return await run(call, 'set_geometry_inputs', name=name, lease_id=lease_id, **params)
    params = pick(action, values, ['new_name'])
    return await run(call, 'snapshot_geometry', name=name, lease_id=lease_id, **params)


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
async def level_edit(
    action: Literal["terrain", "place", "snap"],
    name: Annotated[str | None, Field(min_length=1, max_length=63,
                                      description="New terrain object name.")] = None,
    image: Annotated[str | None, Field(max_length=1024,
                                       description="Workspace PNG/JPEG heightmap.")] = None,
    size: Vector2 | None = None,
    height: Annotated[Number | None, Field(ge=0.01, le=1000)] = None,
    resolution: Annotated[StrictInt | None, Field(ge=2, le=501)] = None,
    location: Vector3 | None = None,
    seed: Annotated[StrictInt | None, Field(ge=0, le=1000000)] = None,
    octaves: Annotated[StrictInt | None, Field(ge=1, le=8)] = None,
    frequency: Annotated[Number | None, Field(ge=1, le=64)] = None,
    placements: Annotated[list[Placement] | None,
                          Field(min_length=1, max_length=256)] = None,
    collection: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    names: Annotated[list[ObjectName] | None, Field(min_length=1, max_length=256)] = None,
    terrain: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    offset: Annotated[Number | None, Field(ge=-1000, le=1000)] = None,
    align_to_normal: StrictBool | None = None,
    lease_id: LeaseId = None,
) -> LevelEditResult:
    """Build a terrain mesh or assemble objects in a level.

    terrain: name, image or noise seed/octaves/frequency, size=(100,100),
    height=10, resolution=128, location; place: placements=[{source, name, location,
    rotation_degrees, scale, linked}], collection; snap: names, terrain, offset,
    align_to_normal=false.
    """
    values = {"name": name, "image": image, "size": size, "height": height,
              "resolution": resolution, "location": location, "seed": seed,
              "octaves": octaves, "frequency": frequency, "placements": placements,
              "collection": collection, "names": names, "terrain": terrain,
              "offset": offset, "align_to_normal": align_to_normal}
    if action == "terrain":
        operation = "create_terrain"
        params = pick(action, values, ["name"], {
            "size": (100.0, 100.0), "height": 10.0, "resolution": 128,
            "location": (0.0, 0.0, 0.0), "image": None, "seed": 0,
            "octaves": 4, "frequency": 4.0})
    elif action == "place":
        operation = "place_objects"
        params = pick(action, values, ["placements"], {"collection": None})
        params["placements"] = [item.model_dump() for item in params["placements"]]
    else:
        operation = "snap_to_surface"
        params = pick(action, values, ["names", "terrain"], {
            "offset": 0.0, "align_to_normal": False})
    return await run(call, operation, lease_id=lease_id, **params)


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
) -> ScatterResult:
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
