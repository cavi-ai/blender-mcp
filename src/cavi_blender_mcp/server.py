"""Typed MCP tools for the Blender bridge."""

from functools import partial
from typing import Annotated, Any, Literal

import anyio
from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations
from pydantic import Field, StrictBool, StrictInt

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
     "render_preview"}
)


def call(operation, **params):
    client = BridgeClient()
    if operation not in LEASE_FREE:
        # Legacy bridges reject this envelope instead of ignoring a lease parameter.
        return client.call("owned_edit", {"operation": operation, "params": params})
    return client.call(operation, params)


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
) -> dict[str, Any]:
    """Measure static mesh budgets, texel density, UV stretch and material sharing.

    Uses the render-active UV layer unless named. Refuses modifiers, rigs and shape keys.
    """
    return await run(call, "inspect_mesh_quality", names=names,
                     texture_resolution=texture_resolution, uv_layer=uv_layer)


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
    action: Literal["create_primitive", "create_mesh", "transform", "set_color", "shade"],
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
    lease_id: LeaseId = None,
) -> dict[str, Any]:
    """Create or edit one object. Params per action:
    create_primitive: kind, location; create_mesh: vertices, faces;
    transform: location, rotation_degrees, scale; set_color: rgba, slot=0; shade: smooth=false.
    """
    values = {"kind": kind, "location": location, "rotation_degrees": rotation_degrees,
              "scale": scale, "vertices": vertices, "faces": faces, "rgba": rgba, "slot": slot,
              "smooth": smooth}
    operation, params = {
        "create_primitive": ("create_primitive",
                             lambda: pick(action, values, ["kind"], {"location": (0, 0, 0)})),
        "create_mesh": ("create_mesh", lambda: pick(action, values, ["vertices", "faces"])),
        "transform": ("transform_object", lambda: pick(action, values, (), {
            "location": None, "rotation_degrees": None, "scale": None})),
        "set_color": ("set_color", lambda: pick(action, values, ["rgba"], {"slot": 0})),
        "shade": ("shade_mesh", lambda: pick(action, values, (), {"smooth": False})),
    }[action]
    return await run(call, operation, lease_id=lease_id, name=name, **params())


@mcp.tool(annotations=MUTATING)
async def mesh_edit(
    action: Literal["modifier", "unwrap"],
    name: ObjectName,
    kind: Literal["bevel", "decimate", "subdivision", "voxel_remesh"] | None = None,
    amount: Annotated[Number | None, Field(
        description="Bevel width (0,100], decimate ratio (0,1], subdivision 1-3, voxel size "
        "[0.005,1].")] = None,
    apply: Annotated[StrictBool | None, Field(description="Bake; needs no modifiers.")] = None,
    angle_limit_degrees: Annotated[Number | None, Field(ge=1, le=89)] = None,
    island_margin: Annotated[Number | None, Field(ge=0, le=0.5)] = None,
    uv_layer: Annotated[str | None, Field(min_length=1, max_length=63)] = None,
    lease_id: LeaseId = None,
) -> dict[str, Any]:
    """Edit mesh surface. Params per action:
    modifier: kind, amount, apply=false (stack max 16);
    unwrap: Smart UV Project + pack; angle_limit_degrees=66, island_margin=0.02, uv_layer.
    """
    values = {"kind": kind, "amount": amount, "apply": apply,
              "angle_limit_degrees": angle_limit_degrees, "island_margin": island_margin,
              "uv_layer": uv_layer}
    if action == "modifier":
        operation = "add_modifier"
        params = pick(action, values, ["kind", "amount"], {"apply": False})
    else:
        operation = "unwrap_mesh"
        params = pick(action, values, (), {"angle_limit_degrees": 66, "island_margin": 0.02,
                                           "uv_layer": None})
    return await run(call, operation, lease_id=lease_id, name=name, **params)


@mcp.tool(annotations=MUTATING)
async def assign_material(
    names: Annotated[list[str], Field(min_length=1, max_length=32)],
    material_name: Annotated[str, Field(min_length=1, max_length=63)],
    base_color_texture: Annotated[str | None, Field(description="Workspace sRGB PNG.")] = None,
    base_color: RGBA = (1, 1, 1, 1),
    roughness: Number = .5,
    metallic: Number = 0,
    slot: Annotated[StrictInt, Field(ge=0, le=31)] = 0,
    lease_id: LeaseId = None,
) -> dict[str, Any]:
    """Assign a new material to exact mesh slots; packs the PNG and preserves other slots."""
    return await run(call, "assign_material", names=names, material_name=material_name,
                     base_color_texture=base_color_texture, base_color=base_color,
                     roughness=roughness, metallic=metallic, slot=slot, lease_id=lease_id)


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
    lease_id: LeaseId = None,
) -> dict[str, Any]:
    """Move assets in or out. Params per action:
    import: static GLB path, name (new prefix); export: names, .fbx/.glb path,
    preserve_instances (FBX), include_empties; save: .blend path;
    generate: image, .glb path, resolution=128 (local TripoSR, no lease).
    """
    values = {"name": name, "names": names, "preserve_instances": preserve_instances,
              "include_empties": include_empties, "image": image, "resolution": resolution}
    if action == "generate":
        params = pick(action, values, ["image"], {"resolution": 128})
        workspace = (await run(call, "scene_info", limit=1))["workspace"]
        return await run(generate, workspace, params["image"], path, params["resolution"])
    if action == "import":
        return await run(call, "import_mesh", lease_id=lease_id, path=path,
                         **pick(action, values, ["name"]))
    if action == "save":
        pick(action, values)
        return await run(call, "save_project", lease_id=lease_id, path=path)
    params = pick(action, values, ["names"], {"preserve_instances": False,
                                              "include_empties": False})
    # A distinct bridge operation makes older bridges fail before writing a file.
    operation = "export_instances" if params["preserve_instances"] else "export_mesh"
    return await run(call, operation, lease_id=lease_id, path=path, **params)


def main():
    import sys

    if len(sys.argv) > 1:
        from .cli import main as cli_main

        raise SystemExit(cli_main())
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
