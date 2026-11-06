"""Declared response fields for the Blender tools."""

from typing import Any, ClassVar, Literal

from cavi_mcp_core.contracts import Result, VariantResult
from pydantic import model_validator


class SceneInfo(Result):
    bridge: dict[str, Any] | None = None
    source_state: dict[str, Any] | None = None
    name: str | None = None
    type: str | None = None
    version: str | None = None
    file: str | None = None
    workspace: str | None = None
    total: int | None = None
    offset: int | None = None
    limit: int | None = None
    objects: list[dict[str, Any]] | None = None
    collections: list[str] | list[dict[str, Any]] | None = None
    instance_collection: str | None = None
    instance_offset: list[float] | None = None
    scene_instances: list[str] | None = None


class MeshQuality(Result):
    scope: Literal["static_source_current_frame"]
    frame: int
    file: str
    dirty: bool
    texture_resolution: list[int]
    density_unit: Literal["pixels_per_meter"]
    scene_unit_meters: float
    objects: list[dict[str, Any]]
    not_checked: list[str]


class UVLayout(VariantResult):
    scopes: ClassVar = ('source_uv_one_texture_set', 'source_uv_udim_coverage')
    shapes = (('unique_tile_ready', 'texture_resolution', 'overlap', 'padding'), ('coverage',))
    nullable_shape_fields = frozenset({'material'})
    material: str | None = None
    scope: Literal['source_uv_one_texture_set', 'source_uv_udim_coverage']
    complete: bool
    objects: list[dict[str, Any]]
    not_checked: list[str]
    unique_tile_ready: bool | None = None
    texture_resolution: list[int] | None = None
    overlap: dict[str, Any] | None = None
    padding: dict[str, Any] | None = None
    coverage: dict[str, Any] | None = None

    @model_validator(mode='before')
    @classmethod
    def require_scope_fields(cls, value):
        if isinstance(value, dict) and value.get('scope') in cls.scopes:
            fields = cls.shapes[cls.scopes.index(value['scope'])]
            if not all(key in value for key in fields):
                raise ValueError('UV result is missing the fields required by its scope')
        return value

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = super().__get_pydantic_json_schema__(core_schema, handler)
        for scope, branch in zip(cls.scopes, schema['anyOf'], strict=True):
            branch['properties'] = {'scope': {'const': scope}}
        return schema


class Ownership(Result):
    active: bool
    owner: str | None
    project_id: str
    claimed_project_id: str | None
    expires_in: float
    idle_seconds: float | None = None
    previous_owner: str | None = None
    lease_id: str | None = None


class AssetResult(Result):
    sha256: str | None = None
    project_id: str | None = None
    opened: bool | None = None
    uv_maps: list[dict[str,Any]] | None = None
    path: str | None = None
    bytes: int | None = None
    objects: list[str | dict[str, Any]] | None = None
    axis: str | None = None
    pairs: int | None = None
    textures: int | list[dict[str, Any]] | None = None


class AssetLibraryResult(Result):
    path: str
    sha256: str
    bytes: int | None = None
    kind: str | None = None
    names: list[str] | None = None
    roots: list[dict[str, Any]] | None = None
    created_counts: dict[str, int] | None = None
    items: list[dict[str, Any]] | None = None
    items_truncated: bool | None = None
    images: list[dict[str, Any]] | None = None
    instances: list[dict[str, Any]] | None = None


class SceneEditResult(VariantResult):
    nullable_shape_fields = frozenset({'world'})
    shapes = (('name', 'type'), ('world', 'strength'),
              ('path', 'engine', 'width', 'height', 'bit_depth'))
    name: str | None = None
    type: str | None = None
    world: str | None = None
    strength: float | None = None
    path: str | None = None
    engine: str | None = None
    width: int | None = None
    height: int | None = None
    bit_depth: int | None = None


Number = int | float
Record = dict[str, Any]
OBJECT_FIELDS = (
    "name",
    "type",
    "location",
    "rotation_degrees",
    "rotation_mode",
    "scale",
    "dimensions",
    "parent",
    "children",
    "collections",
    "modifiers",
)


class ObjectFields(VariantResult):
    nullable_shape_fields = frozenset({"parent"})
    name: str | None = None
    type: str | None = None
    location: list[Number] | None = None
    rotation_degrees: list[Number] | None = None
    scale: list[Number] | None = None
    dimensions: list[Number] | None = None
    parent: str | None = None
    vertices: int | None = None
    polygons: int | None = None
    materials: list[str | None] | None = None
    shape_key_action: str | None = None


class SkinClearance(Result):
    scope: Literal["sampled_garment_clearance"]
    body: str
    garments: list[Record]
    complete: bool
    passed: bool
    frames: list[Number]


class RigMotionComparison(Result):
    scope: Literal["sampled_evaluated_rig_motion"]
    source: str
    candidate: str
    passed: bool
    max_error_m: Number
    tolerance_m: Number
    frames: list[Number]
    meshes: list[Record]


class RigInspection(Result):
    file: str | None
    dirty: bool
    blender_version: str
    frame: int
    fps: Number
    armature: str
    pose_position: str
    root_bones: list[str]
    deform_bones: int
    bones: list[Record]
    meshes: list[Record]
    actions: list[Record]
    action_count: int
    clips: list[Record]
    active_action: str | None
    nla_enabled: bool
    nla_tracks: list[Record] | None = None
    not_checked: list[str]
    project_id: str
    analyzed_action: str | None = None
    animation_checks: dict[str, Record | list[Record]] | None = None


class ObjectEditResult(ObjectFields):
    nullable_shape_fields = frozenset(
        {"parent", "previous_parent", "mesh", "shape_key_action", "action_slot"}
    )
    shapes = (OBJECT_FIELDS, ("source", "count", "linked", "offset", "objects"))
    source: str | None = None
    count: int | None = None
    linked: bool | None = None
    offset: list[Number] | None = None
    objects: list[str] | None = None
    action: str | None = None
    frame_range: list[Number] | None = None
    frames: list[Number] | None = None
    mesh_copy: Record | None = None


class RigEditResult(ObjectFields):
    nullable_shape_fields = frozenset(
        {"parent", "active_action", "action_slot", "shape_key_action"}
    )
    shapes = (
        OBJECT_FIELDS,
        ("armature", "bone_count", "bindings", "meshes"),
        ("action", "previous"),
        ("deleted", "action_count"),
    )
    armature: str | None = None
    bone_count: int | None = None
    bones: list[Record] | None = None
    bindings: int | None = None
    meshes: list[Record] | None = None
    action: str | None = None
    frame_range: list[Number] | None = None
    frames: list[Number] | None = None
    keyed_bones: list[str] | None = None
    source: str | None = None
    source_action: str | None = None
    mapped: list[Record] | None = None
    active_action: str | None = None
    nla_enabled: bool | None = None
    previous: str | None = None
    deleted: str | None = None
    action_count: int | None = None
    calibration: Record | None = None
    strip_settings: Record | None = None
    animation_target: Literal['OBJECT', 'SHAPE_KEYS'] | None = None
    animation_owner: str | None = None


class ProceduralAssetResult(Result):
    name: str
    modifiers: list[Record]
    source: str | None = None
    instance: str | None = None
    definition: str | None = None
    scope: str | None = None
    frame: Number | None = None
    triangles: int | None = None
    materials: list[str | None] | None = None
    material_triangles: list[Record] | None = None


class MeshEditResult(ObjectFields):
    nullable_shape_fields = frozenset(
        {"parent", "symmetry_axis", "density_before", "density_after", "shape_key_action"}
    )
    shapes = (
        OBJECT_FIELDS,
        ("collection", "base", "levels", "source_renamed", "warnings"),
        ("source", "shape", "count", "objects", "uniform_scale"),
        ("source", "by", "count", "parts", "triangles_before"),
    )
    triangles: int | None = None
    warnings: list[str] | None = None
    collection: str | None = None
    base: str | None = None
    levels: list[Record] | None = None
    source_renamed: bool | None = None
    uv_layer: str | None = None
    texture_resolution: int | None = None
    source: str | None = None
    shape: str | None = None
    count: int | None = None
    objects: list[Record] | None = None
    uniform_scale: bool | None = None
    by: Literal["loose_parts", "materials"] | None = None
    parts: list[Record] | None = None
    face_indices: list[int] | None = None
    triangles_before: int | None = None
    uv_transform: Record | None = None


class MaterialAssignment(VariantResult):
    shapes = (('material', 'objects', 'slot', 'updated', 'material_users', 'base_color_srgb',
               'roughness', 'metallic', 'base_color_texture', 'textures', 'config', 'texture_packed'),
              ('material', 'nodes', 'total', 'links'))
    nullable_shape_fields = frozenset({'base_color_texture'})
    material: str
    objects: list[str] | None = None
    slot: int | None = None
    updated: bool | None = None
    material_users: int | None = None
    base_color_srgb: list[Number] | None = None
    roughness: Number | None = None
    metallic: Number | None = None
    base_color_texture: Record | None = None
    textures: dict[str, Record] | None = None
    config: Record | None = None
    texture_packed: bool | None = None
    bindings: list[dict[str, Any]] | None = None
    reserved_empty_slots: list[str] | None = None
    instance: str | None = None
    nodes: list[dict[str, Any]] | None = None
    total: int | None = None
    links: list[dict[str, Any]] | None = None
    changed_inputs: list[str] | None = None
    material_copy: Record | None = None


class MapBakeResult(Result):
    bit_depth: Literal[8, 16, 32]
    color_space: str
    source: Record | None = None
    normal_channels: list[str] | None = None
    path: str
    bytes: int
    sha256: str
    map: Literal["normal", "ao", "curvature", "lightmap", "shader"]
    resolution: int
    samples: int
    margin: int
    cage_extrusion: Number
    max_ray_distance: Number
    normal_space: str | None
    uv_layer: str
    low: str
    high: list[str]
    selected_to_active: bool
    isolate: bool


class LevelEditResult(VariantResult):
    nullable_shape_fields = frozenset({"collection"})
    shapes = (
        (
            "name",
            "resolution",
            "size",
            "height",
            "minimum",
            "maximum",
            "vertices",
            "triangles",
            "source",
        ),
        ("collection", "count", "objects"),
        ("terrain", "offset", "aligned", "objects"),
    )
    name: str | None = None
    resolution: int | None = None
    size: list[Number] | None = None
    height: Number | None = None
    minimum: Number | None = None
    maximum: Number | None = None
    vertices: int | None = None
    triangles: int | None = None
    source: Literal["image", "noise"] | None = None
    image: Record | None = None
    collection: str | None = None
    count: int | None = None
    objects: list[Record] | None = None
    terrain: str | None = None
    offset: Number | None = None
    aligned: bool | None = None


class ScatterResult(Result):
    name: str
    modifier: str
    node_group: str
    collection: str
    estimated_instances: int
    instances: int | None
    evaluated_triangles: int | None
    realize: bool
    seed: int
