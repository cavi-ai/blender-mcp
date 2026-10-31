# Installation

## Requirements

- macOS or Linux. Windows is not part of the tested surface.
- Blender 5.2.3 LTS. Other releases may work, but native checks target 5.2.3.
- Python 3.11 or newer.
- [`uv`](https://docs.astral.sh/uv/) to install the server.
- Node.js 22 or newer, only for MCP evaluation.

## Install the server

```bash
uv tool install cavi-blender-mcp
```

This installs the `cavi-blender-mcp` entry point on your `PATH`.

## Start Blender with the bridge

```bash
cavi-blender-mcp runtime start
```

It runs `blender` from `PATH`, `CAVI_BLENDER_BIN`, or on macOS
`/Applications/Blender.app`, with `--factory-startup` so the session opens a
separate default scene without loading or saving user preferences. The bridge
grants access to scene contents, so use it only with trusted local MCP clients.

To work on an existing project, open its working copy in the dedicated session.
Do not point the bridge at a project you are unwilling to edit. See
[Run a dedicated session](../guides/runtime-and-headless.md) for `--project`,
`--background`, status and restart.

## Register the MCP server

Register the stdio server in your client:

```json
{
  "mcpServers": {
    "blender": {
      "command": "cavi-blender-mcp"
    }
  }
}
```

If your client does not inherit your shell's `PATH`, use the absolute path that
`which cavi-blender-mcp` prints.

## Check the connection

Call `scene_info` from the client. It reports the Blender version, current file,
workspace and a page of objects.

From a shell:

```bash
cavi-blender-mcp runtime status
```

`connected: true` means the bridge answered. If it does not, see
[Troubleshooting](../guides/troubleshooting.md).

## Install from source

```bash
git clone https://github.com/cavi-ai/blender-mcp.git
cd blender-mcp
uv sync --locked
blender --factory-startup --python scripts/start_bridge.py
```

This creates `.venv` with the `cavi-blender-mcp` entry point; register
`.venv/bin/cavi-blender-mcp` by its absolute path.

## Configure the workspace

The workspace defaults to `~/Documents/CaviBlender`. Saves, exports, previews,
imports and generated assets must stay inside it. Set
`CAVI_BLENDER_WORKSPACE` in both Blender's environment and the MCP server's
environment to change it.

[Configuration](../reference/configuration.md) lists every variable.
