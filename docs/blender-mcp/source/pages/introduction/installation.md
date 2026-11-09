# Installation

## Requirements

- macOS or Linux. Windows is not part of the tested surface.
- Blender 5.2.3 LTS. Other releases may work, but native checks target 5.2.3.
- Python 3.15 or newer.
- [`uv`](https://docs.astral.sh/uv/) to install the server.
- Node.js 22 or newer, only for MCP evaluation.

## Install the server

```bash
uv tool install cavi-blender-mcp==0.57.0
```

This installs the `cavi-blender-mcp` entry point on your `PATH`.

## Start Blender with the bridge

For a new scene:

```bash
cavi-blender-mcp runtime start
```

To start with an existing project, put a working copy inside the configured
workspace (`~/Documents/CaviBlender` by default), then select that file at launch:

```bash
cavi-blender-mcp runtime start --project working-copy.blend
```

New sessions use `blender` from `PATH`, `CAVI_BLENDER_BIN`, or on macOS
`/Applications/Blender.app`, with factory settings and no user preference changes.
An existing connected session may be reused; `--project` refuses to replace a
different connected project. The bridge grants access to scene contents, so use
it only with trusted local MCP clients and projects you intend to edit.

See [Run a dedicated session](../guides/runtime-and-headless.md) for project
startup, `--background`, separate connections, status and restart.

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

Ask your agent to inspect the connected Blender scene. It should report the
Blender version, current file, workspace and objects.

From a shell:

```bash
cavi-blender-mcp runtime status
```

`connected: true` means the bridge answered. If it does not, see
[Troubleshooting](../guides/troubleshooting.md).

## Install from source

Use Python 3.15 or newer for the current development checkout. For the published
package's source and documentation, use the
[v0.57.0 tag](https://github.com/cavi-ai/blender-mcp/tree/v0.57.0).

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
