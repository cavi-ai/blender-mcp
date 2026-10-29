"""Typed MCP tools for the Blender bridge."""

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations
from pydantic import Field, StrictBool, StrictInt

from .client import BridgeClient
from .generation import generate

mcp = FastMCP(
    "cavi-blender-mcp",
    instructions=(
        "Inspect the scene before editing. Saves and exports refuse existing paths. "
        "Paths are relative to the Blender session workspace. Never retry an uncertain mutation."
    ),
)
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Vector3 = tuple[Number, Number, Number]
ObjectName = Annotated[str, Field(description="Exact object name returned by scene_info.")]
MUTATING = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
ADDITIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


def call(operation, **params):
    return BridgeClient().call(operation, params)


@mcp.tool(annotations=READ_ONLY)
def scene_info() -> dict[str, Any]:
    """Inspect Blender version, scene objects, active file, and output workspace."""
    return call("scene_info")


@mcp.tool(annotations=READ_ONLY)
def object_info(name: ObjectName) -> dict[str, Any]:
    """Inspect geometry counts, transforms, materials, and modifiers."""
    return call("object_info", name=name)


@mcp.tool(annotations=ADDITIVE)
def create_primitive(
    name: Annotated[str, Field(description="Unique nonempty object name, at most 63 characters.")],
    kind: Annotated[
        Literal["cube", "sphere", "cylinder", "cone", "plane"],
        Field(description="Primitive mesh shape to create."),
    ],
    location: Annotated[Vector3, Field(description="Position in Blender scene units.")] = (0, 0, 0),
) -> dict[str, Any]:
    """Create a named primitive. Existing object names are refused."""
    return call("create_primitive", name=name, kind=kind, location=location)


@mcp.tool(annotations=ADDITIVE)
def generate_mesh(
    image: Annotated[
        str, Field(description="Workspace image of one isolated object on white or alpha.")
    ],
    path: Annotated[str, Field(description="New workspace .glb path; existing files refused.")],
    resolution: Annotated[StrictInt, Field(ge=64, le=192)] = 128,
) -> dict[str, Any]:
    """Reconstruct an original colored mesh with locally configured TripoSR weights.

    Runs offline on CPU in a separate worker, capped at 180 seconds. Requires configured
    CAVI_TRIPOSR_PYTHON, CAVI_TRIPOSR_SOURCE and CAVI_TRIPOSR_WEIGHTS. Never downloads weights.
    """
    workspace = call("scene_info")["workspace"]
    return generate(workspace, image, path, resolution)


@mcp.tool(annotations=ADDITIVE)
def create_mesh(
    name: Annotated[str, Field(min_length=1, max_length=63)],
    vertices: Annotated[list[Vector3], Field(min_length=3, max_length=10000)],
    faces: Annotated[
        list[Annotated[list[StrictInt], Field(min_length=3, max_length=64)]],
        Field(min_length=1, max_length=20000),
    ],
) -> dict[str, Any]:
    """Create custom geometry from local-space vertices and zero-based face indices.

    Use outward face winding. Rejects invalid topology, duplicate names and oversized payloads.
    Disconnected shells are allowed for later voxel remeshing. Does not execute code.
    """
    return call("create_mesh", name=name, vertices=vertices, faces=faces)


@mcp.tool(annotations=MUTATING)
def transform_object(
    name: ObjectName,
    location: Annotated[
        Vector3 | None, Field(description="New position; omit to preserve it.")
    ] = None,
    rotation_degrees: Annotated[
        Vector3 | None, Field(description="XYZ Euler rotation in degrees; omit to preserve it.")
    ] = None,
    scale: Annotated[
        Vector3 | None, Field(description="Positive XYZ scale; omit to preserve it.")
    ] = None,
) -> dict[str, Any]:
    """Set explicitly supplied transform fields on one object."""
    return call(
        "transform_object",
        name=name,
        location=location,
        rotation_degrees=rotation_degrees,
        scale=scale,
    )


@mcp.tool(annotations=MUTATING)
def set_color(
    name: ObjectName,
    rgba: Annotated[
        tuple[Number, Number, Number, Number],
        Field(description="Red, green, blue and alpha components, each from 0 to 1."),
    ],
) -> dict[str, Any]:
    """Assign an object-specific flat preview material; components range from 0 to 1."""
    return call("set_color", name=name, rgba=rgba)


@mcp.tool(annotations=MUTATING)
def add_modifier(
    name: ObjectName,
    kind: Annotated[
        Literal["bevel", "decimate", "subdivision", "voxel_remesh"],
        Field(description="Modifier type to add."),
    ],
    amount: Annotated[
        Number,
        Field(
            description="Bevel width (0,100], decimate ratio (0,1], subdivision integer 1–3, "
            "or voxel size [0.005,1] in local units. Evaluated geometry is bounded."
        ),
    ],
    apply: Annotated[StrictBool, Field(description="Bake into single-user mesh geometry.")] = False,
) -> dict[str, Any]:
    """Add a surface modifier, optionally baking it on an object without existing modifiers."""
    return call("add_modifier", name=name, kind=kind, amount=amount, apply=apply)


@mcp.tool(annotations=MUTATING)
def shade_mesh(
    name: ObjectName,
    smooth: Annotated[
        StrictBool, Field(description="True for smooth shading; false for flat shading.")
    ] = False,
) -> dict[str, Any]:
    """Choose flat or smooth shading on one mesh."""
    return call("shade_mesh", name=name, smooth=smooth)


@mcp.tool(annotations=MUTATING)
def unwrap_mesh(name: ObjectName) -> dict[str, Any]:
    """Generate UV coordinates with Blender Smart UV Project."""
    return call("unwrap_mesh", name=name)


@mcp.tool(annotations=ADDITIVE)
def export_mesh(
    names: Annotated[
        list[str], Field(description="Between 1 and 1000 exact mesh names to export.")
    ],
    path: Annotated[
        str,
        Field(
            description="New output path relative to the configured workspace; existing files are refused."
        ),
    ],
) -> dict[str, Any]:
    """Export only the named meshes as FBX or GLB within the output workspace."""
    return call("export_mesh", names=names, path=path)


@mcp.tool(annotations=ADDITIVE)
def save_project(
    path: Annotated[
        str,
        Field(
            description="New output path relative to the configured workspace; existing files are refused."
        ),
    ],
) -> dict[str, Any]:
    """Save a new .blend file in the output workspace; never overwrite a file."""
    return call("save_project", path=path)


@mcp.tool(annotations=ADDITIVE)
def render_preview(
    path: Annotated[
        str,
        Field(
            description="New output path relative to the configured workspace; existing files are refused."
        ),
    ],
    resolution: Annotated[
        StrictInt, Field(description="Square PNG size in pixels, between 64 and 2048.")
    ] = 512,
    names: Annotated[list[str] | None, Field(min_length=1, max_length=1000)] = None,
    direction: Annotated[
        Vector3, Field(description="Nonzero camera direction from the model center.")
    ] = (1.5, -2, 1.4),
    color_mode: Literal["material", "vertex"] = "material",
) -> Image:
    """Render scene meshes or named meshes; restore visibility and camera afterward."""
    result = call(
        "render_preview",
        path=path,
        resolution=resolution,
        names=names,
        direction=direction,
        color_mode=color_mode,
    )
    return Image(path=result["path"])


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
