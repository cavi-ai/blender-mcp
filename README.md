# Cavi Blender MCP

Typed MCP tools for Blender scene inspection, mesh editing, previews, and game asset export.

## Install

Requires Python 3.11+, uv, and Blender. The native smoke was exercised on Blender 5.2.2 LTS; other Blender versions are unverified. Dependencies are pinned in `uv.lock`.

```sh
uv sync --locked
```

Start a dedicated Blender session with the bridge. Use your Blender executable and the absolute path to this checkout:

```sh
blender --factory-startup --python /path/to/blender-mcp/scripts/start_bridge.py
```

`--factory-startup` opens a separate default scene without loading or saving user preferences. To use an existing project, explicitly open its working copy in this dedicated session. The bridge grants access to scene contents; use only trusted local MCP clients.

Register the stdio server in your MCP client:

```json
{"mcpServers":{"blender":{"command":"/path/to/blender-mcp/.venv/bin/cavi-blender-mcp"}}}
```

Call `scene_info` first. The bridge must be running inside Blender; the MCP server does not launch an application or authenticate accounts.

## Tools

- `scene_info`, `object_info`: inspect scene and geometry.
- `create_primitive`, `transform_object`, `set_color`: create and edit objects.
- `add_modifier`, `shade_mesh`, `unwrap_mesh`: non-destructive bevel/decimate, shading, UVs.
- `export_mesh`: export named meshes as FBX or GLB.
- `save_project`: save a new Blender project.
- `render_preview`: render a PNG and return an MCP image.

Materials are Blender preview colors. Exported assets still need the destination game's materials, scale, collision and import settings.
Material, shading and UV edits refuse shared mesh data to avoid changing linked objects implicitly. Make the mesh single-user in Blender before editing it.

## File and connection boundaries

`CAVI_BLENDER_WORKSPACE` selects the output workspace, defaulting to `~/Documents/CaviBlender`. Save/export/preview paths must remain inside it, including through symbolic links. Existing files are refused. Parent directories must already exist.

The bridge binds only to `127.0.0.1` on an ephemeral port and requires a random session token. `CAVI_BLENDER_CONNECTION` selects its private connection file, defaulting to `~/.cavi/blender-mcp/connection.json`. Keep it out of repositories. Separate concurrent sessions require separate connection files configured in both Blender and the MCP server.

There is no arbitrary Python tool, telemetry or external asset download. Changes are not retried after a timeout; inspect the scene before resubmitting an uncertain mutation. Blender operations run on the main thread. The bridge stops when its Blender process exits.

## Validation

```sh
uv run --locked python -m unittest discover -s tests
uv run --locked ruff check .
blender --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py -- /path/to/empty/test-workspace
```

The native smoke creates a disposable scene, edits a mesh, unwraps UVs, exports FBX/GLB, saves a project, and renders a preview. It does not edit a game project.
