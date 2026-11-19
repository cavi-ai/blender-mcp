# Installation

## Requirements

- macOS or Linux. Windows is not part of the tested surface.
- Blender 5.3.0. Other releases may work, but native checks target 5.3.0.
- Python 3.15 or newer.
- [`uv`](https://docs.astral.sh/uv/) to install the server.
- Node.js 26 or newer, only for MCP evaluation.

## Install the server

```bash
uv tool install cavi-blender-mcp==0.58.0
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

New sessions use `CAVI_BLENDER_BIN`, then on macOS `/Applications/Blender.app`,
then `blender` from `PATH`, with factory settings and no user preference changes.
An existing connected session may be reused; `--project` refuses to replace a
different connected project. The bridge grants access to scene contents, so use
it only with trusted local MCP clients and projects you intend to edit.

See [Run a dedicated session](../guides/runtime-and-headless.md) for project
startup, `--background`, separate connections, status and restart.

## Use your own Blender

To work in your usual Blender, with your preferences and add-ons, close Blender
and install the extension:

```bash
cavi-blender-mcp extension install
```

The command installs and enables the CAVI Blender MCP extension in Blender's
`user_default` repository through Blender's own extension command. Close Blender
first: a running Blender saves its preferences when it quits and would disable
the extension again. To install from Blender instead, build the archive and
choose **Edit > Preferences > Get Extensions > Install from Disk**:

```bash
cavi-blender-mcp extension build --output ~/Downloads
```

Every interactive Blender session then starts the bridge once its window opens.
Background runs, such as command-line renders, never start it. `runtime start`
and `scene_info` connect to that session instead of launching another Blender.
The **CAVI** tab in the 3D Viewport sidebar shows whether the bridge is running,
its workspace, and Start and Stop buttons. One session owns the connection at a
time; a second Blender shows the refusal in that tab.

The extension contains no bridge code. It loads the server package that built
it, so `runtime status` reports a matching bridge. Restart Blender after
upgrading the server, and run `extension install` again if the server moves.

Your preferences, add-ons and auto-run setting for embedded scripts apply in
this session, unlike `runtime start`, which uses factory settings with auto-run
disabled. Blender opened from the Dock or a desktop launcher does not read shell
variables, so the bridge uses the default workspace and connection unless
Blender's environment sets `CAVI_BLENDER_WORKSPACE` and `CAVI_BLENDER_CONNECTION`
to the same values as the MCP server's.

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
[v0.58.0 tag](https://github.com/cavi-ai/blender-mcp/tree/v0.58.0).

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
