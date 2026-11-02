"""Declared response fields and conservative transport failure details."""

from typing import Any, Literal

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict, ValidationError, model_serializer


class Result(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    @model_serializer(mode="wrap")
    def preserve_shape(self, handler):
        """Keep omitted optional fields omitted, preserving the existing wire shape."""
        return {key: value for key, value in handler(self).items() if key in self.model_fields_set}


def failure(name, error):
    cause = error
    while cause.__cause__ is not None:
        cause = cause.__cause__
    rejected = isinstance(cause, (ValueError, ValidationError, FileNotFoundError))
    code = ("INVALID_ARGUMENT" if isinstance(cause, (ValueError, ValidationError))
            else "INPUT_NOT_FOUND" if isinstance(cause, FileNotFoundError)
            else "OUTCOME_UNKNOWN")
    return CallToolResult(isError=True, content=[TextContent(type="text", text=str(error))],
        structuredContent={"error": {"version": 1, "code": code, "operation": name,
            "outcome": "rejected" if rejected else "unknown", "retry_safe": False,
            "next_action": "inspect_inputs" if rejected else "inspect_application_and_outputs"}})


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
    collections: list[dict[str, Any]] | None = None


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
    textures: list[dict[str, Any]] | None = None



def compact_schema(schema):
    """Remove redundant schema titles without changing property names or literal data."""
    if not isinstance(schema, dict):
        return schema
    result = {key: value for key, value in schema.items() if key != "title"}
    for key in ("properties", "patternProperties", "$defs", "dependentSchemas"):
        if key in result:
            result[key] = {name: compact_schema(value) for name, value in result[key].items()}
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        if key in result:
            result[key] = [compact_schema(value) for value in result[key]]
    for key in ("items", "additionalProperties", "not", "if", "then", "else", "contains",
                "unevaluatedProperties", "propertyNames", "contentSchema"):
        if key in result:
            result[key] = compact_schema(result[key])
    return result
