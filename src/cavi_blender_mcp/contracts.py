"""Declared response fields and conservative transport failure details."""

from typing import Any, ClassVar, Literal

from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.types import CallToolResult, TextContent
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    model_serializer,
    model_validator,
)


class Result(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    @model_serializer(mode="wrap")
    def preserve_shape(self, handler):
        """Keep omitted optional fields omitted, preserving the existing wire shape."""
        return {key: value for key, value in handler(self).items() if key in self.model_fields_set}


def failure(name, error):
    cause = error
    while (isinstance(cause, ToolError) and not isinstance(cause, UnexpectedToolError)
           and cause.__cause__ is not None):
        cause = cause.__cause__
    rejected = isinstance(cause, (ValueError, ValidationError, FileNotFoundError))
    code = (
        "INVALID_ARGUMENT"
        if isinstance(cause, (ValueError, ValidationError))
        else "INPUT_NOT_FOUND"
        if isinstance(cause, FileNotFoundError)
        else "OUTCOME_UNKNOWN"
    )
    return CallToolResult(
        isError=True,
        content=[TextContent(type="text", text=str(error))],
        structuredContent={
            "error": {
                "version": 1,
                "code": code,
                "operation": name,
                "outcome": "rejected" if rejected else "unknown",
                "retry_safe": False,
                "next_action": "inspect_inputs" if rejected else "inspect_application_and_outputs",
            }
        },
    )


class SceneInfo(Result):
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


class UVLayout(Result):
    scope: Literal["source_uv_one_texture_set"]
    complete: bool
    unique_tile_ready: bool
    texture_resolution: list[int]
    objects: list[dict[str, Any]]
    overlap: dict[str, Any]
    padding: dict[str, Any]
    not_checked: list[str]


class Ownership(Result):
    active: bool
    owner: str | None
    project_id: str
    claimed_project_id: str | None
    expires_in: float
    lease_id: str | None = None


class AssetResult(Result):
    path: str | None = None
    bytes: int | None = None
    objects: list[str | dict[str, Any]] | None = None
    axis: str | None = None
    pairs: int | None = None
    textures: int | list[dict[str, Any]] | None = None


class VariantResult(Result):
    """Declare existing action branches without adding a discriminator to the wire."""

    shapes: ClassVar[tuple[tuple[str, ...], ...]] = ()
    nullable_shape_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def require_shape(cls, value):
        if isinstance(value, dict):
            fields = {field.alias or name for name, field in cls.model_fields.items()}
            if any(
                item is None and key in fields and key not in cls.nullable_shape_fields
                for key, item in value.items()
            ):
                raise ValueError("Result contains null for a non-null response field")
            if cls.shapes and not any(all(key in value for key in shape) for shape in cls.shapes):
                raise ValueError("Result is missing the fields of an action response")
        return value

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        for key, field in schema.get("properties", {}).items():
            field.pop("default", None)
            if key in cls.nullable_shape_fields:
                continue
            variants = field.get("anyOf")
            if variants and {"type": "null"} in variants:
                rest = [item for item in variants if item != {"type": "null"}]
                field.pop("anyOf")
                field.update(rest[0] if len(rest) == 1 else {"anyOf": rest})
            if not field or set(field) <= {"title"}:
                field["not"] = {"type": "null"}
        if cls.shapes:
            schema["anyOf"] = [{"required": list(shape)} for shape in cls.shapes]
        return schema


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
    triangles_before: int | None = None


class MaterialAssignment(Result):
    material: str
    objects: list[str]
    slot: int
    updated: bool
    material_users: int
    base_color_srgb: list[Number]
    roughness: Number
    metallic: Number
    base_color_texture: Record | None
    textures: dict[str, Record]
    config: Record
    texture_packed: bool


class MapBakeResult(Result):
    bit_depth: Literal[8, 16]
    color_space: Literal["sRGB", "Non-Color"]
    normal_channels: list[str] | None = None
    path: str
    bytes: int
    sha256: str
    map: Literal["normal", "ao", "curvature", "lightmap"]
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


def compact_union(schema):
    """Shorten equivalent union forms; output defaults are documentation only."""
    branches = schema.get("anyOf", [])
    if branches and all(
        set(item) == {"type"} and isinstance(item["type"], str) for item in branches
    ):
        types = list(dict.fromkeys(item["type"] for item in branches))
        if "number" in types and "integer" in types:
            types.remove("integer")
        schema.pop("anyOf")
        schema["type"] = types[0] if len(types) == 1 else types
    elif len(branches) == 2 and {"type": "null"} in branches:
        other = next(item for item in branches if item != {"type": "null"})
        safe = {
            "type",
            "items",
            "additionalProperties",
            "properties",
            "required",
            "minimum",
            "maximum",
            "exclusiveMinimum",
            "exclusiveMaximum",
            "multipleOf",
            "minItems",
            "maxItems",
            "uniqueItems",
            "minLength",
            "maxLength",
            "pattern",
            "format",
            "minProperties",
            "maxProperties",
            "enum",
            "const",
        }
        if isinstance(other.get("type"), str) and set(other) <= safe:
            schema.pop("anyOf")
            schema.update(other)
            schema["type"] = [other["type"], "null"]
            if "const" in schema:
                schema["enum"] = [schema.pop("const"), None]
            elif "enum" in schema:
                schema["enum"] = [*schema["enum"], None]
    return schema


def compact_schema(schema, *, output=False):
    """Remove redundant schema titles without changing property names or literal data."""
    if not isinstance(schema, dict):
        return schema
    result = {
        key: value
        for key, value in schema.items()
        if key != "title" and not (output and key == "default")
    }
    if result.get("additionalProperties") is True:
        result.pop("additionalProperties")
    for key in ("properties", "patternProperties", "$defs", "dependentSchemas"):
        if key in result:
            result[key] = {
                name: compact_schema(value, output=output) for name, value in result[key].items()
            }
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        if key in result:
            result[key] = [compact_schema(value, output=output) for value in result[key]]
    for key in (
        "items",
        "additionalProperties",
        "not",
        "if",
        "then",
        "else",
        "contains",
        "unevaluatedProperties",
        "propertyNames",
        "contentSchema",
    ):
        if key in result:
            result[key] = compact_schema(result[key], output=output)
    return compact_union(result)
