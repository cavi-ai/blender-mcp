# Installation

## Requirements

- macOS or Linux. Windows is not part of the tested surface.
- Blender 5.2.3 LTS. Other releases may work, but native checks target 5.2.3.
- Python 3.11 or newer.
- [`uv`](https://docs.astral.sh/uv/) for the locked environment.
- Node.js 22 or newer, only for MCP evaluation.

## Install the server

```bash
git clone https://github.com/cavi-ai/blender-mcp.git
cd blender-mcp
uv sync --locked
```

This creates `.venv` and installs the `cavi-blender-mcp` entry point.

## Start Blender with the bridge

Use the absolute path to this checkout:

```bash
blender --factory-startup --python /path/to/blender-mcp/scripts/start_bridge.py
```

`--factory-startup` opens a separate default scene without loading or saving
user preferences. The bridge grants access to scene contents, so use it only
with trusted local MCP clients.

To work on an existing project, open its working copy in the dedicated session.
Do not point the bridge at a project you are unwilling to edit.

## Register the MCP server

Register the stdio server in your client. Use absolute paths:

```json
{
  "mcpServers": {
    "blender": {
      "command": "/path/to/blender-mcp/.venv/bin/cavi-blender-mcp"
    }
  }
}
```

Alternatively, let the CLI start and control a dedicated session:

```bash
/path/to/blender-mcp/.venv/bin/cavi-blender-mcp runtime start
```

See [Run a dedicated session](../guides/runtime-and-headless.md) for
`--project`, `--background`, status and restart.

## Check the connection

Call `scene_info` from the client. It reports the Blender version, current file,
workspace and a page of objects.

From a shell:

```bash
/path/to/blender-mcp/.venv/bin/cavi-blender-mcp runtime status
```

`connected: true` means the bridge answered. If it does not, see
[Troubleshooting](../guides/troubleshooting.md).

## Configure the workspace

The workspace defaults to `~/Documents/CaviBlender`. Saves, exports, previews,
imports and generated assets must stay inside it. Set
`CAVI_BLENDER_WORKSPACE` in both Blender's environment and the MCP server's
environment to change it.

[Configuration](../reference/configuration.md) lists every variable.
