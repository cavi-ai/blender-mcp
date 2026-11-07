"""Typed MCP tools for the Blender bridge."""

from functools import partial
from pathlib import Path
from typing import Annotated, Literal

import anyio
from cavi_mcp_core.server import DESTRUCTIVE, READ_ONLY, WRITES
from cavi_mcp_core.server import Server as CoreServer
from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import UnexpectedToolError
from mcp.types import CallToolResult
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    WithJsonSchema,
    model_validator,
)

from .catalog import BlenderServer
from .client import BridgeClient
from .contracts import (
    AssetLibraryResult,
    AssetResult,
    ImageReceipt,
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
from .scene_models import (
    CameraRay,
    CameraSpec,
    LightSpec,
    PreviewSettings,
    RenderSpec,
    SurfaceRay,
    WorldSpec,
)

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
ObjectName = str
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


class FaceRegion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    seed: Annotated[StrictInt, Field(ge=0)]
    stop_at: Annotated[list[Literal['seam','material','uv']], Field(max_length=3)] = []
    angle_limit_degrees: Annotated[Number | None, Field(ge=0, le=180)] = None

    @model_validator(mode='after')
    def distinct_boundaries(self):
        if len(set(self.stop_at))!=len(self.stop_at):
            raise ValueError('region.stop_at boundaries must be unique')
        return self


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


class UVRegion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    bounds: tuple[Number, Number, Number, Number]
    texture_resolution: tuple[StrictInt, StrictInt]
    margin_px: Number
    allow_overlap: StrictBool = False
    allow_pinned: StrictBool = False

    @model_validator(mode='after')
    def valid_region(self):
        from .uv_regions import region

        region(self.model_dump(mode='json'))
        return self


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


def png_result(path):
    try:
        content = Image(path=path).to_image_content()
    except (OSError, ValueError, TypeError) as exc:
        raise UnexpectedToolError('Rendered PNG result could not be encoded') from exc
    return CallToolResult(content=[content],
                          structured_content={'path': path, 'mime_type': 'image/png'})


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
    name: Annotated[str | None, Field(description="Object")] = None,
    limit: Annotated[StrictInt, Field(ge=1, le=1000, description="Limit")] = 200,
    offset: Annotated[StrictInt, Field(ge=0, description="Offset")] = 0,
    definition: Annotated[StrictBool | None, Field(description='Instance contents')] = None,
    faces: Annotated[StrictBool | None, Field(description='Source polygons')] = None,
    edges: Annotated[StrictBool | None, Field(description='Source edges/seams')] = None,
    uv_layer: Annotated[str | None, Field(min_length=1, max_length=63, description='Face/pick/region UV map')] = None,
    vertices: Annotated[StrictBool | None, Field(description='Source vertices')] = None,
    surface_ray: Annotated[SurfaceRay | CameraRay | None, Field(description='World ray or camera pixel; range in metres')] = None,
    region: Annotated[FaceRegion | None, Field(description='Connected source-face page')] = None,
) -> SceneInfo:
    """Inspect objects, source topology or camera-picked scene surfaces."""
    if region is not None:
        if name is None or faces or edges or vertices or definition or surface_ray is not None:
            raise ValueError('region requires a mesh name and excludes other inspection modes')
        if ('uv' in region.stop_at) != (uv_layer is not None):
            raise ValueError('region UV boundaries require uv_layer; other regions exclude it')
        return await run(call,'inspect_face_region',name=name,region=region.model_dump(mode='json'),
                         uv_layer=uv_layer,limit=limit,offset=offset)
    if surface_ray is not None:
        if vertices or faces or edges or definition or offset or limit != 200:
            raise ValueError('surface_ray requires a mesh name and excludes pagination and other modes')
        if name is None:
            if not isinstance(surface_ray,CameraRay):
                raise ValueError('World surface_ray requires a mesh name')
            if not surface_ray.evaluated:
                raise ValueError('Scene camera picking requires evaluated=true')
            return await run(call,'pick_scene_surface',surface_ray=surface_ray.model_dump(mode='json'),uv_layer=uv_layer)
        return await run(call,'pick_mesh_surface',name=name,surface_ray=surface_ray.model_dump(mode='json'),uv_layer=uv_layer)
    if vertices:
        if name is None or faces or edges or definition or uv_layer is not None:
            raise ValueError('vertices requires a mesh name and excludes other page modes')
        return await run(call, 'inspect_mesh_vertices', name=name, limit=limit, offset=offset)
    if uv_layer is not None and (not faces or edges or definition or name is None):
        raise ValueError('uv_layer requires a named source-face page')
    if edges:
        if name is None or faces or definition:
            raise ValueError('edges requires a mesh name and cannot be combined with faces or definition')
        return await run(call, 'inspect_mesh_edges', name=name, limit=limit, offset=offset)
    if faces:
        if name is None or definition:
            raise ValueError('faces requires a mesh name and cannot be combined with definition')
        params = {'name': name, 'limit': limit, 'offset': offset}
        if uv_layer is not None:
            params['uv_layer'] = uv_layer
        return await run(call, 'inspect_mesh_faces', **params)
    if definition:
        if name is None:
            raise ValueError('definition requires a scene-instance name')
        return await run(call, 'inspect_collection_instance', name=name, limit=limit, offset=offset)
    if name is not None:
        return await run(call, "object_info", name=name)
    return await run(call, "scene_info", limit=limit, offset=offset)


@mcp.tool(annotations=READ_ONLY)
async def inspect_mesh_quality(
    names: Annotated[list[ObjectName], Field(min_length=1, max_length=32, description="Objects")],
    texture_resolution: Annotated[tuple[Annotated[StrictInt, Field(ge=1, le=4096)],
                              Annotated[StrictInt, Field(ge=1, le=4096)]], Field(description="Pixels")] = (1024, 1024),
    uv_layer: Annotated[str | None, Field(min_length=1, max_length=63, description="UV map")] = None,
    checks: Annotated[list[Check] | None, Field(max_length=6, description="Empty: all checks")] = None,
    naming: Annotated[NamingRules | None, Field(description="Rules")] = None,
    lightmap_uv: Annotated[str, Field(min_length=1, max_length=63, description="Lightmap UVs")] = "UVMap_Lightmap",
    lightmap_resolution: Annotated[StrictInt, Field(ge=16, le=4096, description="Lightmap pixels")] = 64,
) -> MeshQuality:
    """Check static mesh budgets, density/stretch and PBR color spaces/packing/graphs.
    No modifiers/rigs/shape keys; default render-active UVs."""
    return await run(call, "inspect_mesh_quality", names=names,
                     texture_resolution=texture_resolution, uv_layer=uv_layer,
                     checks=checks or [],
                     naming=naming.model_dump() if naming else None,
                     lightmap_uv=lightmap_uv, lightmap_resolution=lightmap_resolution)


@mcp.tool(annotations=READ_ONLY)
async def inspect_uv_layout(
    names: Annotated[list[ObjectName], Field(min_length=1, max_length=32, description="Objects")],
    texture_resolution: Annotated[tuple[Annotated[StrictInt, Field(ge=1, le=16384)],
                              Annotated[StrictInt, Field(ge=1, le=16384)]] | None, Field(description="Pixels")] = None,
    padding_pixels: Annotated[Number | None, Field(ge=0, le=256, description="Gutter; requires resolution")] = None,
    uv_layer: Annotated[str | None, Field(min_length=1, max_length=63, description='UV map; default UV0')] = None,
    comparison_budget: Annotated[StrictInt | None, Field(ge=1, le=1000000, description='Pair cap; default 50/triangle')] = None,
    material: Annotated[str | None, Field(min_length=1, max_length=63, description="Material filter")] = None,
    udim_image: Annotated[str | None, Field(min_length=1, max_length=63, description='UDIM coverage only; no shader transforms/gutters')] = None,
) -> UVLayout:
    """Source UV overlaps/gutters or UDIM coverage; max 20,000 triangles.
    Unevaluated; incomplete work fails."""
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
    armature: Annotated[ObjectName, Field(description="Rig")],
    meshes: Annotated[list[ObjectName], Field(min_length=1, max_length=8, description='Skins: one vertex-group modifier bound to armature')],
    max_influences: Annotated[StrictInt, Field(ge=1, le=32, description="Influences/vertex")] = 4,
    action: Annotated[str | None, Field(min_length=1, max_length=63, description="Clip; default active")] = None,
    checks: Annotated[list[Literal["root_motion", "loop", "deformation"]] | None,
                      Field(max_length=3, description="Clip checks")] = None,
    samples: Annotated[StrictInt, Field(ge=2, le=32, description="Samples")] = 8,
    contacts: Annotated[list[ContactWindow] | None, Field(min_length=1, max_length=16, description='Markers/windows: XY drift/absolute Z error (m)')] = None,
    contact_reference: Annotated[ContactReference | None, Field(description='Source rig/clip: marker offsets across rest axes')] = None,
    contact_frame_offset: Annotated[Number, Field(description="Candidate frame shift")] = 0,
    contact_frame_scale: Annotated[Number, Field(gt=0, description='Candidate frame=source*scale+ contact_frame_offset')] = 1,
) -> RigInspection:
    """Inspect skin weights/rest bones/linked clips."""
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
    body: Annotated[ObjectName, Field(description="Closed body")],
    garments: Annotated[list[ObjectName], Field(min_length=1, max_length=8, description="Distinct garments")],
    start_frame: Annotated[StrictInt, Field(ge=1, le=1000000, description="First")],
    end_frame: Annotated[StrictInt, Field(ge=1, le=1000000, description="Last")],
    min_clearance_m: Annotated[Number, Field(ge=0, description="Minimum signed gap (m)")],
    samples: Annotated[StrictInt, Field(ge=2, le=32, description="Samples")] = 9,
    surface_samples: Annotated[Literal["vertices", "vertices_and_centres"], Field(description="Samples")] = "vertices_and_centres",
    max_queries: Annotated[StrictInt, Field(ge=1, le=1000000, description="Query cap")] = 1000000,
) -> SkinClearance:
    """Sample signed garment gaps (m); restore frame. Requires closed unambiguous bodies and complete budgets.
    Sampling cannot certify continuous collision."""
    return await run(call, "inspect_skin_clearance", body=body, garments=garments,
        start_frame=start_frame, end_frame=end_frame, min_clearance_m=min_clearance_m,
        samples=samples, surface_samples=surface_samples, max_queries=max_queries)


@mcp.tool(annotations=READ_ONLY)
async def compare_rig_motion(
    source: Annotated[ObjectName, Field(description="Source rig")],
    candidate: Annotated[ObjectName, Field(description="Candidate rig")],
    meshes: Annotated[list[MotionSkinPair], Field(min_length=1, max_length=8, description="Paired skins")],
    start_frame: Annotated[StrictInt, Field(ge=1, le=1000000, description="First")],
    end_frame: Annotated[StrictInt, Field(ge=1, le=1000000, description="Last")],
    max_error_m: Annotated[Number, Field(ge=0, description="Error cap (m)")],
    samples: Annotated[StrictInt, Field(ge=2, le=32, description="Samples")] = 9,
    space: Annotated[Literal["world", "start_root"], Field(description="World/start-root-relative positions")] = "world",
    vertex_match: Annotated[Literal["index", "point_set"], Field(description='index: same vertex order; point_set: bidirectional nearest points, unpaired')] = "index",
    candidate_frame_offset: Annotated[Number, Field(ge=-1000000, le=1000000, description="Candidate frame shift")] = 0,
    candidate_frame_scale: Annotated[Number, Field(gt=0, description='Candidate frame=source*scale+ candidate_frame_offset')] = 1,
) -> RigMotionComparison:
    """Compare evaluated skin/bone motion; restore frame/subframe."""
    options = {'candidate_frame_scale': candidate_frame_scale} if candidate_frame_scale != 1 else {}
    return await run(call, "compare_rig_motion", source=source, candidate=candidate,
        meshes=[pair.model_dump() for pair in meshes], start_frame=start_frame, end_frame=end_frame,
        max_error_m=max_error_m, samples=samples, space=space, vertex_match=vertex_match,
        candidate_frame_offset=candidate_frame_offset, **options)


@mcp.tool(annotations=MUTATING)
async def rig_edit(
    action: Annotated[Literal["create", "bind", "weights", "pose", "keyframe", "clear_pose",
                    "retarget", "set_action", "rename_action", "delete_action",
                    "nla_push", "nla_edit", "nla_remove", "constraint", "remove_constraint",
                    "assign_weights", "transfer_weights", "bake", "contact_lock"], Field(description="Action")],
    name: Annotated[str, Field(description="Skin mesh/rig/clip; create: new")],
    location: Annotated[Vector3 | None, Field(description="World position")] = None,
    bones: Annotated[list[BoneSpec] | None, Field(min_length=1, max_length=128, description="Bones")] = None,
    names: Annotated[list[str] | None, Field(min_length=1, max_length=16, description="bind: skins; optional for bake/contact_lock")] = None,
    max_influences: Annotated[StrictInt | None, Field(ge=1, le=32, description="Influences")] = None,
    clean_threshold: Annotated[Number | None, Field(ge=0, le=1, description="Weight cutoff")] = None,
    normalize: Annotated[StrictBool | None, Field(description="Normalize")] = None,
    poses: Annotated[list[PoseSpec] | None, Field(min_length=1, max_length=128, description="Poses")] = None,
    keyframes: Annotated[list[KeyframeSpec] | None, Field(min_length=1, max_length=32, description="Keys")] = None,
    action_name: Annotated[str | None, Field(min_length=1, max_length=63, description="Clip")] = None,
    frame: Annotated[StrictInt | None, Field(ge=1, le=1_000_000, description="Frame")] = None,
    reset: Annotated[StrictBool | None, Field(description="Reset pose")] = None,
    source: Annotated[str | None, Field(min_length=1, max_length=63, description="Rig/skin")] = None,
    source_action: Annotated[str | None, Field(min_length=1, max_length=63, description="Source")] = None,
    mapping: Annotated[dict[str, str] | None, Field(max_length=128, description="Bone map")] = None,
    samples: Annotated[StrictInt | None, Field(ge=2, le=256, description="Samples")] = None,
    new_name: Annotated[str | None, Field(min_length=1, max_length=63, description="Result")] = None,
    track_name: Annotated[str | None, Field(min_length=1, max_length=63, description="Track")] = None,
    strip_name: Annotated[str | None, Field(min_length=1, max_length=63, description="Strip")] = None,
    start_frame: Annotated[StrictInt | None, Field(ge=1, le=1_000_000, description="First")] = None,
    end_frame: Annotated[StrictInt | None, Field(ge=1, le=1_000_000, description="Last")] = None,
    frame_step: Annotated[Number | None, Field(gt=0, le=10000, description="Step")] = None,
    constraint: Annotated[Constraint | None, Field(description="Constraint")] = None,
    bone: Annotated[str | None, Field(min_length=1, max_length=63, description="Bone")] = None,
    constraint_name: Annotated[str | None, Field(min_length=1, max_length=63, description="Name")] = None,
    vertex_weights: Annotated[list[VertexWeights] | None,
                              Field(min_length=1, max_length=100000, description="Weights")] = None,
    replace: Annotated[StrictBool | None, Field(description="Replace")] = None,
    max_distance_m: Annotated[Number | None, Field(gt=0, description="Radius (m)")] = None,
    max_discarded_weight: Annotated[Number | None, Field(ge=0, le=1, description="Loss/vertex")] = None,
    shape_names: Annotated[list[RigName] | None, Field(max_length=64, description="Shapes")] = None,
    calibration: Annotated[RetargetCalibration | None, Field(description="Rest alignment")] = None,
    skinning_mode: Annotated[Literal['preserve', 'linear'] | None, Field(description="Baked skinning")] = None,
    foot_locks: Annotated[list[FootLockWindow] | None, Field(min_length=1, max_length=16, description="Contact windows")] = None,
    timing: Annotated[ClipTiming | None, Field(description="Timing")] = None,
    strip_settings: Annotated[NlaStripSettings | None, Field(description="nla_edit required; optional nla_push")] = None,
    animation_target: Annotated[Literal['OBJECT', 'SHAPE_KEYS'] | None, Field(description="Owner")] = None,
    lease_id: Annotated[LeaseId, Field(description="Lease")] = None,
) -> RigEditResult:
    """Edit rigs, skin weights and animation clips."""
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
    action: Annotated[Literal['camera', 'light', 'world', 'render'], Field(description="Action")],
    camera: Annotated[CameraSpec | None, Field(description='camera: create/update named camera')] = None,
    light: Annotated[LightSpec | None, Field(description='light: create/update named light')] = None,
    world: Annotated[WorldSpec | None, Field(description='world: color/HDRI; updates require managed graphs')] = None,
    render: Annotated[RenderSpec | None, Field(description='render: persistent; PNG/TIFF default 16-bit, EXR 16/32; enabled Cycles GPU')] = None,
    lease_id: Annotated[LeaseId, Field(description="Lease")] = None,
) -> SceneEditResult:
    """Author cameras/lights/managed worlds; render named cameras."""
    definitions = {'camera': camera, 'light': light, 'world': world, 'render': render}
    params = pick(action, definitions, [action])
    return await run(call, 'scene_authoring', lease_id=lease_id, action=action,
                     definition=params[action].model_dump())


@mcp.tool(annotations=ADDITIVE)
async def render_preview(
    path: Annotated[str, Field(description="New workspace PNG")],
    resolution: Annotated[StrictInt, Field(description="Square pixels: 64-2048")] = 512,
    names: Annotated[list[str] | None, Field(min_length=1, max_length=1000,
                                             description="Meshes to isolate")] = None,
    direction: Annotated[Vector3, Field(description="Center-to-camera direction")] = (
        1.5, -2, 1.4),
    color_mode: Annotated[Literal["material", "vertex"], Field(description="Material/vertex colors")] = "material",
    renderer: Annotated[Literal["workbench", "eevee"], Field(description="Renderer")] = "workbench",
    orthographic: Annotated[StrictBool, Field(description="Orthographic")] = False,
    settings: Annotated[PreviewSettings | None, Field(description="Temporary display/compositing/PNG depth; omitted keeps scene controls; enabled curves/white balance reuse them")] = None,
) -> ImageReceipt:
    """Render PNG; restore scene. Lease-free; Eevee max 1024 px."""
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
    return png_result(result["path"])


@mcp.tool(annotations=ADDITIVE)
async def session_control(
    action: Annotated[Literal["inspect", "claim", "renew", "release", "break"], Field(description="Action")],
    owner: Annotated[str | None, Field(max_length=128, description="claim: owner")] = None,
    expected_project: Annotated[
        str | None, Field(description="project_id")
    ] = None,
    lease_id: Annotated[str | None, Field(max_length=128, description="renew/release: lease")] = None,
    ttl_seconds: Annotated[StrictInt, Field(ge=30, le=3600, description="Lease seconds")] = 600,
) -> Ownership:
    """Manage edit leases; claim returns lease_id. Break requires expected_project and 300s idle.
    Lease changes never save/close/discard projects."""
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
    action: Annotated[Literal["create_primitive", "create_mesh", "transform", "set_color", "shade",
                    "apply_transforms", "set_origin", "snap_to_grid", "rename", "add_socket",
                    "duplicate", "delete", "make_unique", "make_single_user", "parent", "unparent", "move_to_collection", "shape_key_add",
                    "shape_key_value", "shape_key_keyframe", "shape_key_remove"], Field(description="Action")],
    name: Annotated[str, Field(description="Object; unique for create_*")],
    kind: Annotated[Literal["cube", "sphere", "cylinder", "cone", "plane"] | None, Field(description="create_primitive needs kind")] = None,
    location: Annotated[Vector3 | None, Field(description="Position: world; add_socket: local")] = None,
    rotation_degrees: Annotated[Vector3 | None, Field(description="XYZ Euler angles")] = None,
    scale: Annotated[Vector3 | None, Field(description="Nonzero; negative mirrors")] = None,
    vertices: Annotated[list[Vector3] | None, Field(min_length=3, max_length=10000, description="create_mesh needs vertices")] = None,
    faces: Annotated[
        list[Annotated[list[StrictInt], Field(min_length=3, max_length=64)]] | None,
        Field(min_length=1, max_length=20000, description="Zero-based, outward winding"),
    ] = None,
    rgba: Annotated[RGBA | None, Field(description="RGBA in [0,1]")] = None,
    slot: Annotated[StrictInt | None, Field(ge=0, le=31, description="Slot")] = None,
    smooth: Annotated[StrictBool | None, Field(description="shade: smooth; default false")] = None,
    components: Annotated[list[Literal["location", "rotation", "scale"]] | None,
                          Field(min_length=1, max_length=3, description="apply_transforms: default rotation/scale")] = None,
    make_single_user: Annotated[StrictBool | None, Field(description="apply_transforms: copy shared mesh; default false")] = None,
    origin: Annotated[Literal["bounds_bottom_center", "bounds_center", "world_origin", "point"] | None, Field(description="set_origin: default bounds_bottom_center; point needs location")] = None,
    grid: Annotated[Number | None, Field(ge=0.001, le=100, description="snap_to_grid needs spacing (scene units)")] = None,
    new_name: Annotated[str | None, Field(min_length=1, max_length=63, description="shape_key_*: key; parent: parent; move_to_collection: collection; else output name")] = None,
    count: Annotated[StrictInt | None, Field(ge=1, le=256, description="duplicate: copies; default 1")] = None,
    offset: Annotated[Vector3 | None, Field(description="Copy translation; duplicate default [0,0,0]")] = None,
    linked: Annotated[StrictBool | None, Field(description="duplicate: linked; default false")] = None,
    create: Annotated[StrictBool | None, Field(description="move_to_collection: create missing; default true")] = None,
    value: Annotated[Number | None, Field(ge=0, le=1, description="Shape-key value; add default 0")] = None,
    keyframes: Annotated[list[ShapeKeyframe] | None, Field(min_length=1, max_length=32, description="shape_key_keyframe needs frame/value pairs")] = None,
    action_name: Annotated[str | None, Field(min_length=1, max_length=63, description="shape_key_keyframe needs clip")] = None,
    source: Annotated[str | None, Field(min_length=1, max_length=63, description="shape_key_add: source mesh")] = None,
    offsets: Annotated[list[Annotated[list[Number], Field(min_length=4, max_length=4)]] | None,
                       Field(max_length=10000, description="shape_key_add: vertex index/XYZ deltas")] = None,
    recursive: Annotated[StrictBool | None, Field(description='delete: descendants')] = None,
    lease_id: Annotated[LeaseId, Field(description="Lease")] = None,
) -> ObjectEditResult:
    """Create, transform or delete objects and branch data."""
    values = {"kind": kind, "location": location, "rotation_degrees": rotation_degrees,
              "scale": scale, "vertices": vertices, "faces": faces, "rgba": rgba, "slot": slot,
              "smooth": smooth, "components": components, "make_single_user": make_single_user,
              "origin": origin, "grid": grid, "new_name": new_name, "count": count,
              "offset": offset, "linked": linked, "create": create, "value": value,
              "keyframes": keyframes, "action_name": action_name, "source": source,
              "offsets": offsets, "recursive": recursive}
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
        "delete": ("delete_objects", lambda: pick(action, values, (), {"recursive": False})),
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
    action: Annotated[Literal["modifier", "modifier_update", "modifier_remove", "unwrap", "decimate_to", "remesh_quad", "lod_chain",
                    "lightmap_uv", "texel_density", "collision", "cleanup", "boolean",
                    "join", "separate", "extract_faces", "extrude_faces", "unwrap_faces", "set_seams", "move_vertices", "assign_faces", "mirror", "array", "solidify", "uv_transform"], Field(description="Action")],
    name: Annotated[ObjectName, Field(description="Mesh")],
    kind: Annotated[Literal["bevel", "decimate", "subdivision", "voxel_remesh"] | None, Field(description="Modifier")] = None,
    amount: Annotated[Number | None, Field(
        description="Bevel width (0,100], decimate (0,1], subdivision 1-3, voxel [0.005,1]; "
        "move_vertices radius (m).")] = None,
    apply: Annotated[StrictBool | None, Field(description="Bake; no modifiers allowed")] = None,
    angle_limit_degrees: Annotated[Number | None, Field(ge=1, le=89, description="Unwrap split angle")] = None,
    island_margin: Annotated[Number | None, Field(ge=0, le=0.5, description="Unwrap margin")] = None,
    uv_layer: Annotated[str | None, Field(min_length=1, max_length=63, description="UV map")] = None,
    target_triangles: Annotated[StrictInt | None, Field(ge=4, le=500000, description="Triangle cap; excludes amount")] = None,
    target_faces: Annotated[StrictInt | None, Field(ge=16, le=100000, description="Quad face cap")] = None,
    symmetry_axis: Annotated[Literal["X", "Y", "Z"] | None, Field(description="Symmetry axis")] = None,
    preserve: Annotated[list[Preserve] | None, Field(max_length=3, description="decimate/LOD: seams; remesh: sharp/boundary")] = None,
    ratios: Annotated[list[Annotated[Number, Field(gt=0, lt=1)]] | None,
                      Field(min_length=1, max_length=6, description="LOD ratios; excludes triangle_targets")] = None,
    triangle_targets: Annotated[list[Annotated[StrictInt, Field(ge=4)]] | None,
                                Field(min_length=1, max_length=6, description="LOD triangle caps; excludes ratios")] = None,
    rename_source: Annotated[StrictBool | None, Field(description="Suffix source LOD0")] = None,
    lightmap_resolution: Annotated[StrictInt | None, Field(ge=16, le=4096, description="Lightmap pixels")] = None,
    margin_px: Annotated[Number | None, Field(ge=0, le=64, description="Lightmap padding (px)")] = None,
    target_px_per_m: Annotated[Number | None, Field(gt=0, le=100000, description="Density: pixels/metre")] = None,
    texture_resolution: Annotated[StrictInt | None, Field(ge=1, le=4096, description="Pixels")] = None,
    pack: Annotated[StrictBool | None, Field(description="Pack scaled UVs")] = None,
    shape: Annotated[Literal["convex", "box", "sphere"] | None, Field(description="Collision shape")] = None,
    max_hull_vertices: Annotated[StrictInt | None, Field(ge=4, le=255, description="Hull vertices")] = None,
    merge_distance: Annotated[Number | None, Field(ge=0, le=1, description="Merge radius (scene units)")] = None,
    steps: Annotated[list[Step] | None, Field(max_length=5, description="Ordered cleanup")] = None,
    operand: Annotated[str | None, Field(description="Operand mesh")] = None,
    operation: Annotated[Literal["union", "difference", "intersect"] | None, Field(description="Boolean operation")] = None,
    solver: Annotated[Literal["exact", "fast"] | None, Field(description="Boolean solver")] = None,
    keep_operand: Annotated[StrictBool | None, Field(description="Keep boolean operand")] = None,
    self_intersection: Annotated[StrictBool | None, Field(description="Boolean self-intersections")] = None,
    names: Annotated[list[str] | None, Field(min_length=1, max_length=64, description="Meshes to join")] = None,
    by: Annotated[Literal["loose_parts", "materials"] | None, Field(description="Separation rule")] = None,
    new_name: Annotated[ObjectName | None, Field(description="Extracted mesh name")] = None,
    face_indices: Annotated[list[Annotated[StrictInt, Field(ge=0)]] | None,
                            Field(min_length=1, max_length=20000, description="Polygon indices")] = None,
    count: Annotated[StrictInt | None, Field(ge=2, le=1000, description="Array count")] = None,
    offset: Annotated[Vector3 | Annotated[Number, Field(ge=-1, le=1)] | None,
                      Field(description="Vector; solidify [-1,1]")] = None,
    thickness: Annotated[Number | None, Field(gt=0, le=100, description="Solidify thickness")] = None,
    clipping: Annotated[StrictBool | None, Field(description="Mirror clipping")] = None,
    uv_transform: Annotated[UVTransform | None, Field(description="UV transform/selected faces")] = None,
    lease_id: Annotated[LeaseId, Field(description="Lease")] = None,
    expected_mesh_sha256: Annotated[str | None, Field(pattern='^[0-9a-f]{64}$', description='Source geometry SHA256')] = None,
    expected_uv_sha256: Annotated[str | None, Field(pattern='^[0-9a-f]{64}$', description='UV SHA256')] = None,
    uv_region: Annotated[UVRegion | None, Field(description='unwrap_faces/UV density: region and gutters')] = None,
    edge_indices: Annotated[list[Annotated[StrictInt, Field(ge=0)]] | None,
                           Field(min_length=1, max_length=20000, description='set_seams: edge indices')] = None,
    seam: Annotated[StrictBool | None, Field(description='set_seams: seam flag')] = None,
    unwrap_method: Annotated[Literal['smart', 'angle_based', 'conformal', 'minimum_stretch'] | None,
                             Field(description='unwrap_faces method; default smart')] = None,
    vertex_indices: Annotated[list[Annotated[StrictInt, Field(ge=0)]] | None,
                             Field(min_length=1, max_length=20000, description='Source vertices')] = None,
    symmetry_tolerance_m: Annotated[Number | None, Field(gt=0, description='move_vertices: symmetry match tolerance (m)')] = None,
    material_name: Annotated[str | None, Field(min_length=1, max_length=63, description='assign_faces: existing finish')] = None,
    modifier_name: Annotated[RigName | None, Field(description='Existing modifier')] = None,
    modifier_settings: Annotated[dict[str,JsonValue] | None, Field(description='Native modifier controls')] = None,
) -> MeshEditResult:
    """Edit a leased mesh, its UVs or derived geometry."""
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
              'expected_mesh_sha256': expected_mesh_sha256, 'uv_region': uv_region,
              'edge_indices': edge_indices, 'seam': seam, 'unwrap_method': unwrap_method,
              'vertex_indices': vertex_indices, 'symmetry_tolerance_m': symmetry_tolerance_m,
              'material_name': material_name, 'expected_uv_sha256': expected_uv_sha256,
              'modifier_name':modifier_name,'modifier_settings':modifier_settings}
    if action in ('modifier_update','modifier_remove'):
        params=pick(action,values,['modifier_name'],
                    {'amount':None,'modifier_settings':None} if action=='modifier_update' else {})
        if action=='modifier_update' and (amount is None)==(modifier_settings is None):
            raise ValueError('modifier_update requires: amount or modifier_settings, exclusively')
        return await run(call,'update_modifier' if action=='modifier_update' else 'remove_modifier',
                         lease_id=lease_id,name=name,**params)
    if action == 'assign_faces':
        from .mesh_regions import fingerprint, indices

        params = pick(action, values, ['face_indices', 'material_name'], {'expected_mesh_sha256': None})
        indices(params['face_indices'])
        fingerprint(params['expected_mesh_sha256'])
        return await run(call, 'assign_face_material', lease_id=lease_id, name=name, **params)
    if action == 'move_vertices':
        from .mesh_regions import selection
        from .vertex_edit import radius_m

        params = pick(action, values, ['vertex_indices','offset'], {'expected_mesh_sha256': None,'amount': None,
            'symmetry_axis':None,'symmetry_tolerance_m':None})
        if (symmetry_axis is None) != (symmetry_tolerance_m is None):
            raise ValueError('move_vertices symmetry requires both axis and tolerance in metres')
        for field in ('symmetry_axis','symmetry_tolerance_m'):
            if params[field] is None:
                params.pop(field)
        if symmetry_tolerance_m is not None:
            params['symmetry_tolerance_m'] = radius_m(symmetry_tolerance_m)
        if params['amount'] is not None:
            params['amount'] = radius_m(params['amount'])
        else:
            params.pop('amount')
        selection(params['vertex_indices'], params['offset'], expected=params['expected_mesh_sha256'],
                  field='vertex_indices')
        return await run(call, 'move_vertices', lease_id=lease_id, name=name, **params)
    if action == 'set_seams':
        from .mesh_regions import fingerprint, indices

        params = pick(action, values, ['edge_indices', 'seam'], {'expected_mesh_sha256': None})
        indices(params['edge_indices'], field='edge_indices')
        if type(params['seam']) is not bool:
            raise ValueError('seam must be an explicit boolean')
        fingerprint(params['expected_mesh_sha256'])
        return await run(call, 'set_seams', lease_id=lease_id, name=name, **params)
    if action == 'unwrap_faces':
        from .mesh_regions import fingerprint, indices
        from .uv_regions import projection

        params = pick(action, values, ['face_indices', 'uv_region'], {'uv_layer': None,
            'angle_limit_degrees': None, 'expected_mesh_sha256': None, 'unwrap_method': 'smart'})
        params['unwrap_method'], params['angle_limit_degrees'] = projection(
            params['unwrap_method'], params['angle_limit_degrees'])
        indices(params['face_indices'])
        fingerprint(params['expected_mesh_sha256'])
        params['uv_region'] = uv_region.model_dump(mode='json')
        return await run(call, 'unwrap_faces', lease_id=lease_id, name=name, **params)
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
        from .mesh_regions import fingerprint
        from .uv_density import options

        operation = 'transform_uv'
        params = pick(action, values, ['uv_transform'], {'uv_layer': None,
            'target_px_per_m': None, 'uv_region': None, 'expected_mesh_sha256': None, 'expected_uv_sha256': None})
        destination = params['uv_region'].model_dump(mode='json') if params['uv_region'] else None
        options(params['target_px_per_m'], destination, params['uv_transform'].scale)
        fingerprint(params['expected_mesh_sha256'])
        params['uv_region'] = destination
        params = {k: v for k, v in params.items() if v is not None or k == 'uv_layer'}
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
    names: Annotated[list[str] | None, Field(min_length=1, max_length=32, description="assign needs meshes")] = None,
    material_name: Annotated[str | None, Field(min_length=1, max_length=63, description="make_unique: new; assign: new unless update_existing; else existing")] = None,
    base_color_texture: Annotated[str | None, Field(description="Workspace sRGB image")] = None,
    base_color: Annotated[RGBA | None, Field(description="assign: sRGB RGBA")] = None,
    roughness: Annotated[Number | None, Field(description="assign: roughness")] = None,
    metallic: Annotated[Number | None, Field(description="assign: metallic")] = None,
    roughness_texture: Annotated[str | None, Field(description="assign: Non-Color image")] = None,
    metallic_texture: Annotated[str | None, Field(description="assign: Non-Color image")] = None,
    normal_texture: Annotated[str | None, Field(description="assign: Non-Color image")] = None,
    normal_strength: Annotated[Number | None, Field(description="assign: normal scale")] = None,
    emission_texture: Annotated[str | None, Field(description="assign: sRGB image")] = None,
    emission_strength: Annotated[Number | None, Field(description="assign: emission scale")] = None,
    alpha_texture: Annotated[str | None, Field(description="assign: Non-Color image")] = None,
    alpha_mode: Annotated[Literal["opaque", "clip", "blend"] | None, Field(description="assign: transparency")] = None,
    uv_scale: Annotated[Vector2 | None, Field(description="assign: UV scale")] = None,
    uv_offset: Annotated[Vector2 | None, Field(description="assign: UV translation")] = None,
    uv_rotation_degrees: Annotated[Number | None, Field(description="assign: UV rotation")] = None,
    uv_layer: Annotated[str | None, Field(max_length=63,
        description='Sampling/tangent UVs; empty: render-active; keep UV flags')] = None,
    update_existing: Annotated[StrictBool | None, Field(description="assign: managed update; connect: replace occupied inputs")] = None,
    slot: Annotated[StrictInt, Field(ge=0, le=31, description="Slot")] = 0,
    lease_id: Annotated[LeaseId, Field(description="Lease")] = None,
    instance: Annotated[str | None, Field(description="Scene collection instance")] = None,
    link_mode: Annotated[Literal['DATA', 'OBJECT'] | None, Field(description='DATA/OBJECT binding; OBJECT shares geometry')] = None,
    action: Annotated[Literal['assign', 'inspect', 'set_inputs', 'set_image', 'make_unique', 'connect', 'disconnect', 'node_types', 'create_node', 'set_ramp', 'set_node'], Field(description='make_unique copies groups; shares images/actions')] = 'assign',
    group_path: Annotated[list[str] | None, Field(description="Groups, outermost first")] = None,
    node: Annotated[str | None, Field(description="Node; links: destination")] = None,
    node_type: Annotated[str | None, Field(min_length=1,max_length=127,description='Native type ID')] = None,
    node_settings: Annotated[dict[str,JsonValue] | None, Field(max_length=32,description='Native settings')] = None,
    inputs: Annotated[dict[str, JsonValue] | None, Field(description="set_inputs: ID/value; links: input ID/{node,socket} (1..32)")] = None,
    outputs: Annotated[dict[str, JsonValue] | None, Field(description="set_inputs: output ID/value map")] = None,
    image: Annotated[ShaderImage | None, Field(description='set_image: pack native snapshot')] = None,
    offset: Annotated[StrictInt | None, Field(ge=0, description="inspect: first node")] = None,
    limit: Annotated[StrictInt | None, Field(ge=1, le=1000, description="inspect: node cap")] = None,
) -> MaterialAssignment:
    """Assign PBR or edit native shaders.
    Defaults retain links; edits affect shared users and detach tool configuration."""
    if material_name is None:
        raise ValueError('material_name is required')
    shader = {'group_path': group_path, 'node': node, 'inputs': inputs, 'outputs': outputs, 'image': image, 'offset': offset, 'limit': limit,
              'node_type':node_type,'node_settings':node_settings}
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
    if action in {'connect','disconnect'}:
        from .shader_links import bindings

        replace = values.pop('update_existing')
        pick(action,values)
        if action=='disconnect' and replace is not None:
            raise ValueError('disconnect does not accept update_existing')
        params=pick(action,shader,['node','inputs'],{'group_path':[]})
        bindings(params['inputs'])
        return await run(call,'edit_material_links',material_name=material_name,lease_id=lease_id,
                         action=action,update_existing=False if replace is None else replace,**params)
    if action != 'assign':
        pick(action, values)
        if action=='node_types':
            params=pick(action,shader,(),{'group_path':[],'node_type':None,'offset':0,'limit':100})
            return await run(call,'inspect_shader_node_types',material_name=material_name,**params)
        if action=='create_node':
            params=pick(action,shader,['node','node_type'],{'group_path':[],'node_settings':{}})
            return await run(call,'create_shader_node',material_name=material_name,lease_id=lease_id,**params)
        if action in {'set_ramp','set_node'}:
            params=pick(action,shader,['node','node_settings'],{'group_path':[]})
            if not params['node_settings']:raise ValueError(action+' requires nonempty node_settings')
            operation='set_shader_ramp' if action=='set_ramp' else 'set_shader_node'
            return await run(call,operation,material_name=material_name,lease_id=lease_id,**params)
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
    map: Annotated[Literal["normal", "ao", "curvature", "lightmap", "shader"], Field(description="Map; shader needs source")],
    name: Annotated[ObjectName, Field(description="Mesh")],
    path: Annotated[str, Field(description="New workspace PNG; shader allows EXR")],
    high: Annotated[list[str] | None, Field(min_length=1, max_length=64, description="normal/AO sources")] = None,
    resolution: Annotated[StrictInt, Field(ge=64, le=4096, description="Image pixels")] = 1024,
    samples: Annotated[StrictInt, Field(ge=1, le=256, description="Samples/pixel")] = 16,
    margin: Annotated[StrictInt, Field(ge=0, le=64, description="Gutter pixels")] = 4,
    bit_depth: Annotated[Literal[8, 16, 32] | None, Field(description='PNG 8/16, default 16; shader EXR 16/32, default 32')] = None,
    cage_extrusion: Annotated[Number | None, Field(ge=0, le=1, description="Cage distance")] = None,
    max_ray_distance: Annotated[Number | None, Field(ge=0, le=10, description="Projection ray cap")] = None,
    normal_space: Annotated[Literal["tangent", "object"] | None, Field(description="Normal space")] = None,
    uv_layer: Annotated[str | None, Field(min_length=1, max_length=63, description="UV map")] = None,
    isolate: Annotated[StrictBool, Field(description="Isolate bake objects")] = True,
    source: Annotated[ShaderBakeSource | None, Field(description='shader: socket IDs/UV atlas; raw-data/sRGB-color PNG; signed/HDR needs EXR, alpha its own socket')] = None,
    lease_id: Annotated[LeaseId, Field(description="Lease")] = None,
) -> MapBakeResult:
    """Bake geometry maps/shader socket to a new image."""
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
    action: Annotated[Literal["import", "export", "save", "generate", "open"], Field(description="Action")],
    path: Annotated[str, Field(description="Workspace path: existing for import/open, else new")],
    name: Annotated[str | None, Field(min_length=1, max_length=58, description="import needs name prefix")] = None,
    names: Annotated[list[str] | None, Field(max_length=1000, description="export needs objects unless bake_pair")] = None,
    preserve_instances: Annotated[StrictBool | None, Field(description="export: keep supported instancing")] = None,
    include_empties: Annotated[StrictBool | None, Field(description="export: empties")] = None,
    image: Annotated[str | None, Field(description="generate needs workspace image")] = None,
    resolution: Annotated[StrictInt | None, Field(ge=64, le=192, description='generate: TripoSR grid; default 128')] = None,
    lods: Annotated[StrictBool | None, Field(description="export: generated LODs")] = None,
    collision: Annotated[StrictBool | None, Field(description="export: collision proxies")] = None,
    animations: Annotated[StrictBool | None, Field(description="export: animation")] = None,
    baked_animation: Annotated[StrictBool | None, Field(description="export: baked animation")] = None,
    assembly: Annotated[StrictBool | None, Field(description="export: evaluate static instances")] = None,
    animation_sample_step: Annotated[Number | None, Field(gt=0, description="export: frame interval")] = None,
    textures: Annotated[StrictBool | None, Field(description="export: write texture sidecars")] = None,
    triangulate: Annotated[StrictBool | None, Field(description="FBX: triangulate")] = None,
    bake_pair: Annotated[BakePair | None, Field(description='export: <stem>_low.fbx/<stem>_high.fbx')] = None,
    axis: Annotated[Literal["unity", "unreal", "godot"] | None, Field(description='export: axes (default unity)')] = None,
    uv_layer: Annotated[str | None, Field(min_length=1,max_length=63, description='export: UV0 (FBX/GLB)/st (USD), via temporary data')] = None,
    lease_id: Annotated[LeaseId, Field(description="Lease")] = None,
    expected_sha256: Annotated[str | None, Field(pattern='^[0-9a-f]{64}$', description='open: optional target SHA-256')] = None,
) -> AssetResult:
    """Import/export/save/open. Open needs clean source, no file UI/scripts. Only generate is lease-free."""
    values = {"name": name, "names": names, "preserve_instances": preserve_instances,
              "include_empties": include_empties, "image": image, "resolution": resolution,
              "lods": lods, "collision": collision, "animations": animations,
              "textures": textures, "bake_pair": bake_pair, "axis": axis,
              "baked_animation": baked_animation, "animation_sample_step": animation_sample_step,
              'assembly': assembly,'uv_layer':uv_layer,'expected_sha256':expected_sha256,
              'triangulate': triangulate}
    if action == 'export' and triangulate is not None and Path(path).suffix.lower() != '.fbx':
        raise ValueError('triangulate applies only to FBX exports')
    if action == 'open':
        params = pick(action, values, (), {'expected_sha256': None})
        return await run(call, 'open_project', lease_id=lease_id, path=path, **params)
    if action == 'export' and assembly is True:
        values.pop('assembly')
        params = pick(action, values, ['names'], {'axis': None, 'textures': False,'uv_layer':None,
                                                'triangulate': False})
        if params['uv_layer'] is None:params.pop('uv_layer')
        if not params['triangulate']:params.pop('triangulate')
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
                                              "textures": False, "axis": None, "baked_animation": False, "animation_sample_step": None,'uv_layer':None,
                                              'triangulate': False})
    if params['uv_layer'] is None:params.pop('uv_layer')
    else:
        return await run(call,'export_uv_asset',lease_id=lease_id,path=path,**params)
    if (params["lods"] or params["collision"] or params["animations"]
            or params["textures"] or params["axis"] or params["baked_animation"] or params["triangulate"] or params["animation_sample_step"] is not None
            or path.lower().endswith((".usd", ".usda", ".usdc"))):
        return await run(call, "export_asset", lease_id=lease_id, path=path, **params)
    for key in ("lods", "collision", "animations", "textures", "axis", "baked_animation", "animation_sample_step", "triangulate"):
        params.pop(key)
    # A distinct bridge operation makes older bridges fail before writing a file.
    operation = "export_instances" if params["preserve_instances"] else "export_mesh"
    return await run(call, operation, lease_id=lease_id, path=path, **params)


@mcp.tool(annotations=ADDITIVE)
async def asset_library(
    action: Annotated[Literal['inspect', 'append'], Field(description="Action")],
    path: Annotated[str, Field(description="Workspace .blend path")],
    kind: Annotated[Literal['objects', 'collections', 'materials', 'node_groups'], Field(description="Native asset type")] = 'collections',
    names: Annotated[list[str] | None, Field(min_length=1, max_length=256, description="append needs source names")] = None,
    expected_sha256: Annotated[str | None, Field(pattern='^[0-9a-f]{64}$', description="append needs inspected hash")] = None,
    offset: Annotated[StrictInt | None, Field(ge=0, description="inspect: first asset")] = None,
    limit: Annotated[StrictInt | None, Field(ge=1, le=1000, description="Limit")] = None,
    instance_collections: Annotated[StrictBool | None, Field(description='append: shared-definition empties; only collections')] = None,
    lease_id: Annotated[LeaseId, Field(description="Lease")] = None,
) -> AssetLibraryResult:
    """Inspect .blend assets; append independent editable IDs."""
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
    action: Annotated[Literal['inspect', 'set_inputs', 'bake_copy'], Field(description="Action")],
    name: Annotated[str, Field(description="Mesh")],
    modifier: Annotated[str | None, Field(description="Geometry Nodes modifier")] = None,
    inputs: Annotated[dict[str, JsonValue] | None, Field(description="set_inputs needs ID/value map")] = None,
    attributes: Annotated[dict[str, str | None] | None, Field(description="set_inputs: ID/attribute map; null disables")] = None,
    new_name: Annotated[str | None, Field(description="bake_copy needs output name")] = None,
    instance: Annotated[str | None, Field(description='Containing instance; edits share its definition')] = None,
    lease_id: Annotated[LeaseId, Field(description="Lease")] = None,
) -> ProceduralAssetResult:
    """Inspect/edit procedural inputs or snapshot meshes; members via scene_info(definition=true)."""
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
    path: Annotated[str, Field(description="New workspace PNG")],
    names: Annotated[list[str] | None, Field(min_length=1, max_length=1000, description="Objects")] = None,
    views: Annotated[list[View] | None, Field(min_length=1, max_length=6, description="Views; omitted uses defaults")] = None,
    mode: Annotated[Literal["shaded", "wireframe", "uv_checker", "texel_heatmap", "matcap"], Field(description="Shading/diagnostic mode")] = "shaded",
    resolution: Annotated[StrictInt, Field(ge=256, le=2048, description="Sheet width")] = 1024,
    target_px_per_m: Annotated[Number | None, Field(gt=0, le=100000, description="texel_heatmap: target density; default 512")] = None,
    texture_resolution: Annotated[StrictInt | None, Field(ge=1, le=4096, description="Pixels")] = None,
    uv_layer: Annotated[str | None, Field(min_length=1, max_length=63, description="UV map")] = None,
) -> ImageReceipt:
    """Render a multi-view PNG; no lease. Heatmap: blue < target_px_per_m=512 (green) < red."""
    result = await run(call, "review_sheet", path=path, names=names, views=views, mode=mode,
                       resolution=resolution, target_px_per_m=target_px_per_m,
                       texture_resolution=texture_resolution, uv_layer=uv_layer)
    return png_result(result["path"])


@mcp.tool(annotations=MUTATING)
async def level_edit(
    action: Annotated[Literal["terrain", "place", "snap"], Field(description="Action")],
    name: Annotated[str | None, Field(min_length=1, max_length=63,
                                      description="New terrain object")] = None,
    image: Annotated[str | None, Field(max_length=1024,
                                       description="Workspace PNG/JPEG heightmap")] = None,
    size: Annotated[Vector2 | None, Field(description='terrain: XY extent; default [100,100]')] = None,
    height: Annotated[Number | None, Field(ge=0.01, le=1000, description='terrain: height range; default 10')] = None,
    resolution: Annotated[StrictInt | None, Field(ge=2, le=501, description='terrain: vertices/side; default 128')] = None,
    location: Annotated[Vector3 | None, Field(description='terrain: world position; default [0,0,0]')] = None,
    seed: Annotated[StrictInt | None, Field(ge=0, le=1000000, description="terrain: noise seed")] = None,
    octaves: Annotated[StrictInt | None, Field(ge=1, le=8, description="terrain: noise layers")] = None,
    frequency: Annotated[Number | None, Field(ge=1, le=64, description="terrain: noise frequency")] = None,
    placements: Annotated[list[Placement] | None,
                          Field(min_length=1, max_length=256, description="place needs object transforms")] = None,
    collection: Annotated[str | None, Field(min_length=1, max_length=63, description="Collection")] = None,
    names: Annotated[list[ObjectName] | None, Field(min_length=1, max_length=256, description="Objects")] = None,
    terrain: Annotated[str | None, Field(min_length=1, max_length=63, description="snap needs terrain")] = None,
    offset: Annotated[Number | None, Field(ge=-1000, le=1000, description="snap: height above surface")] = None,
    align_to_normal: Annotated[StrictBool | None, Field(description='snap: align normals; default false')] = None,
    lease_id: Annotated[LeaseId, Field(description="Lease")] = None,
) -> LevelEditResult:
    """Build terrain; place/snap objects on terrain."""
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
    name: Annotated[ObjectName, Field(description="Scatter surface mesh")],
    collection: Annotated[str, Field(min_length=1, max_length=63, description="Collection")],
    density: Annotated[Number, Field(gt=0, le=10000, description="Points/m²")],
    seed: Annotated[StrictInt, Field(ge=0, le=1000000, description="Distribution seed")] = 0,
    min_distance: Annotated[Number, Field(ge=0, le=1000, description="Spacing (scene units)")] = 0,
    scale_range: Annotated[tuple[Number, Number], Field(description="Scale bounds")] = (1, 1),
    rotation_jitter_degrees: Annotated[Number, Field(ge=0, le=360, description="Rotation jitter cap")] = 360,
    realize: Annotated[StrictBool, Field(description="Realize instances")] = False,
    lease_id: Annotated[LeaseId, Field(description="Lease")] = None,
) -> ScatterResult:
    """Scatter collection instances with fixed Geometry Nodes."""
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
