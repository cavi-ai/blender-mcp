"""Typed MCP tools for the Blender bridge."""

from typing import Literal

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations

from .client import BridgeClient

mcp = FastMCP(
    "cavi-blender-mcp",
    instructions=(
        "Inspect the scene before editing. Saves and exports refuse existing paths. "
        "Paths are relative to the Blender session workspace. Never retry an uncertain mutation."
    ),
)
READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


def call(operation, **params):
    return BridgeClient().call(operation, params)


@mcp.tool(annotations=READ_ONLY)
def scene_info() -> dict:
    """Inspect Blender version, scene objects, active file, and output workspace."""
    return call("scene_info")


@mcp.tool(annotations=READ_ONLY)
def object_info(name: str) -> dict:
    """Inspect geometry counts, transforms, materials, and modifiers."""
    return call("object_info", name=name)


@mcp.tool()
def create_primitive(
    name: str,
    kind: Literal["cube", "sphere", "cylinder", "cone", "plane"],
    location: tuple[float, float, float] = (0, 0, 0),
) -> dict:
    """Create a named primitive. Existing object names are refused."""
    return call("create_primitive", name=name, kind=kind, location=location)


@mcp.tool()
def transform_object(
    name: str,
    location: tuple[float, float, float] | None = None,
    rotation_degrees: tuple[float, float, float] | None = None,
    scale: tuple[float, float, float] | None = None,
) -> dict:
    """Set explicitly supplied transform fields on one object."""
    return call(
        "transform_object",
        name=name,
        location=location,
        rotation_degrees=rotation_degrees,
        scale=scale,
    )


@mcp.tool()
def set_color(name: str, rgba: tuple[float, float, float, float]) -> dict:
    """Assign an object-specific flat preview material; components range from 0 to 1."""
    return call("set_color", name=name, rgba=rgba)


@mcp.tool()
def add_modifier(name: str, kind: Literal["bevel", "decimate"], amount: float) -> dict:
    """Add a non-destructive bevel (width) or decimate (ratio) modifier."""
    return call("add_modifier", name=name, kind=kind, amount=amount)


@mcp.tool()
def shade_mesh(name: str, smooth: bool = False) -> dict:
    """Choose flat or smooth shading on one mesh."""
    return call("shade_mesh", name=name, smooth=smooth)


@mcp.tool()
def unwrap_mesh(name: str) -> dict:
    """Generate UV coordinates with Blender Smart UV Project."""
    return call("unwrap_mesh", name=name)


@mcp.tool()
def export_mesh(names: list[str], path: str) -> dict:
    """Export only the named meshes as FBX or GLB within the output workspace."""
    return call("export_mesh", names=names, path=path)


@mcp.tool()
def save_project(path: str) -> dict:
    """Save a new .blend file in the output workspace; never overwrite a file."""
    return call("save_project", path=path)


@mcp.tool()
def render_preview(path: str, resolution: int = 512) -> Image:
    """Render a material-color preview of scene meshes to a new workspace PNG."""
    result = call("render_preview", path=path, resolution=resolution)
    return Image(path=result["path"])


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
